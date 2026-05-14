from ..agent import orchestrator
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from ..tools.sql_tool import SQLTool
from ..config import get_settings
from ..agent.orchestrator import CoachOrchestrator
from ..models.schema import ChatRequest, ExerciseDetail
from openai import OpenAI
import json
import os

settings = get_settings()

app = FastAPI()

client = OpenAI(
    api_key=settings.OPENAI_API_KEY,  # 你的 aihubmix key
    base_url=settings.OPENAI_BASE_URL,  # 你的 aihubmix 代理地址
)
orchestrator = CoachOrchestrator(client)

sql_tool = SQLTool()

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
async def chat_static(request: ChatRequest):
    response = await orchestrator.execute(request.message)
    return {"data": response}
