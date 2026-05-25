from ..agent import orchestrator
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from ..tools.sql_tool import SQLTool
from ..tools.graph_tool import GraphTool
from ..config import get_settings
from ..agent.orchestrator import CoachOrchestrator
from ..models.schema import ChatRequest, ExerciseDetail, UserProfileRequest, UserSignupRequest, AuthResponse, UserLoginRequest
from ..agent.utils.logger import logger, LogColor
from openai import OpenAI
import json
import os
import bcrypt

settings = get_settings()

app = FastAPI()

client = OpenAI(
    api_key=settings.OPENAI_API_KEY,  # 你的 aihubmix key
    base_url=settings.OPENAI_BASE_URL,  # 你的 aihubmix 代理地址
)
orchestrator = CoachOrchestrator(client)

sql_tool = SQLTool()

graph_tool = GraphTool()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "../../../static") 
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# --- 数据库直接查询接口 ---
@app.get("/v1/exercises/{exercise_id}", response_model=ExerciseDetail)
async def get_exercise(exercise_id: str):
    """获取特定动作详情"""
    try:
        # 直接调用你编写好的异步函数
        result = await sql_tool.search_exercise_detail(exercise_id)

        # 容错处理：如果没找到对应 ID 的动作
        if not result:
            raise HTTPException(
                status_code=404, detail=f"Exercise with id {exercise_id} not found"
            )

        return result

    except Exception as e:
        # 异常捕获，确保生产环境稳定
        print(f"API Error fetching exercise {exercise_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# --- AI 对话接口 ---
@app.post("/v1/chat")
async def chat_endpoint(request: ChatRequest):
    """
    JD 亮点：流式响应接口 (StreamingResponse)
    大幅降低首字延迟 (TTFT)，提升用户体验
    """

    async def generate():
        # 调用编排器获取流式结果
        # 注意：这里需要我们在 Orchestrator 的 synthesize 中开启 stream=True
        async for chunk in orchestrator.execute_stream(request.message):
            if chunk:
                # 以 SSE (Server-Sent Events) 格式发送
                yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

# 传统的非流式接口 (用于简单测试或低频场景)
@app.post("/v1/chat/static")
async def chat_static(request: ChatRequest, background_tasks: BackgroundTasks):
    print("request: ", request)
    response = await orchestrator.execute(request.user_id, request.session_id, request.message, background_tasks)
    return {"data": response}

# --- Auth接口 ---
@app.post("/v1/user/signup", response_model=AuthResponse)
async def sign_up_user(request: UserSignupRequest, background_tasks: BackgroundTasks):
    print("request:", request)
    try:
        logger.info(f"{LogColor.TOOL}[AuthAPI] 👤 接收到新用户注册与身体问卷初始化请求，用户名: '{request.username}'{LogColor.RESET}")
        new_user_id = await sql_tool.init_user(request)

        injuries_list = [i.strip() for i in request.injuries.split(",") if i.strip()] if request.injuries else []
        equipments_list = [e.strip() for e in request.equipments.split(",") if e.strip()] if request.equipments else ["自重"]
        
        
        if background_tasks:
            background_tasks.add_task(
                graph_tool.init_user_semantic_memory,
                user_id=new_user_id, name=request.username, level=request.fitness_level,
                injuries=injuries_list, equipments=equipments_list
            )

        return AuthResponse(
            user_id=new_user_id,
            username=request.username,
            status="success"
        )
    except Exception as e:
        logger.error(f"[AuthAPI] 注册事务全盘崩溃打回: {e}")
        # 如果是因为重名或者数据库约束引发冲突，无情拦截
        raise HTTPException(status_code=400, detail=f"注册失败或用户名已被占用: {str(e)}")

@app.post("/v1/user/login", response_model=AuthResponse)
async def login(request: UserLoginRequest):
    logger.info(f"[AuthAPI] 🔑 收到用户登录请求，尝试验证账户: '{request.username}'")
    user_data: dict = await sql_tool.get_user_credentials_by_name(request.username)
    
    if not user_data:
        raise HTTPException(status_code=401, detail="账户不存在或密码验证失败")
        
    db_password_hash = user_data.get("password_hash")
    db_user_id = user_data.get("user_id")

    is_password_valid = bcrypt.checkpw(
        request.password.encode('utf-8'),
        db_password_hash.encode('utf-8')
    )
    
    if not is_password_valid:
        logger.warning(f"[AuthAPI] ❌ 账户 '{request.username}' 密码验证失败！")
        raise HTTPException(status_code=401, detail="账户不存在或密码验证失败")
        
    logger.info(f"✅ [AuthAPI] 账户 '{request.username}' (ID: {db_user_id}) 鉴权通过。分布式工作记忆已准备唤醒。")
    return AuthResponse(
        user_id=db_user_id,
        username=request.username,
        status="success"
    )


@app.post("/v1/user/profile/update")
async def update_profile(request: UserProfileRequest, background_tasks: BackgroundTasks):
    """
    3. 个人中心画像修改/追加痛点中心
    职责：同步强刷 MySQL 历史备份快照，并异步刷新 Neo4j 的语义演进线
    """
    logger.info(f"{LogColor.TOOL}[AuthAPI] ⚙️ 收到用户 ID: {request.user_id} 的语义记忆动态演进更新请求{LogColor.RESET}")
    
    try:
        # 3.1 物理强刷 MySQL 的基础画像，将其作为纸面底稿持久化
        await sql_tool.update_user_profile(request)
        
        # 3.2 💡 异步命令你的大一统 graph_tool 物理执行 Cypher 的「边关系彻底解绑与重新合并」！
        injuries_list = [i.strip() for i in request.injuries.split(",") if i.strip()] if request.injuries else []
        equipments_list = [e.strip() for e in request.equipments.split(",") if e.strip()] if request.equipments else ["自重"]
        
        if background_tasks:
            background_tasks.add_task(
                graph_tool.init_user_semantic_memory,
                user_id=request.user_id, name=request.username, level=request.fitness_level,
                injuries=injuries_list, equipments=equipments_list
            )

        return {"status": "success", "message": "长效语义画像与生理防线升级完毕"}
        
    except Exception as e:
        logger.error(f"[AuthAPI] 画像动态演进发生崩溃: {e}")
        raise HTTPException(status_code=500, detail=f"长效记忆更新失败: {str(e)}")

@app.get("/v1/user/profile/{id}", response_model = UserProfileRequest)
async def get_profile(id: int):
    try:
        # 直接调用你编写好的异步函数
        result = await sql_tool.search_profile(id)

        # 容错处理：如果没找到对应 ID 的动作
        if not result:
            raise HTTPException(
                status_code=404, detail=f"User with id {id} not found"
            )

        return result

    except Exception as e:
        # 异常捕获，确保生产环境稳定
        print(f"API Error fetching user {id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
