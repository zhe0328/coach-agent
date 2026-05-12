from ..agent import orchestrator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from ..config import get_settings
from ..agent.orchestrator import CoachOrchestrator
from ..models.schema import ChatRequest
from openai import OpenAI
import json
# from ..services.coach_service import CoachService

settings = get_settings()

app = FastAPI()

client = OpenAI(
    api_key=settings.OPENAI_API_KEY,      # 你的 aihubmix key
    base_url=settings.OPENAI_BASE_URL     # 你的 aihubmix 代理地址
)
# coach_service = CoachService()
orchestrator = CoachOrchestrator(client)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 数据库直接查询接口 ---


# @app.get("/exercises", response_model=list[ExerciseBase])
# async def list_exercises(
#     target: Optional[str] = None,
#     equipment: Optional[str] = None,
#     difficulty: Optional[str] = None,
#     body_part: Optional[str] = None,
#     category: Optional[str] = None,
#     name: Optional[str] = None
# ):
#     """直接获取数据库结果"""
#     return await coach_service.get_exercises(
#         target=target,
#         equipment=equipment,
#         difficulty=difficulty,
#         body_part=body_part,
#         category=category,
#         name=name
#     )


# @app.get("/exercises/{exercise_id}", response_model=ExerciseDetail)
# async def get_exercise(exercise_id: str):
#     """获取特定动作详情"""
#     return await coach_service.get_exercise_detail(exercise_id)


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
    return {"response": response}