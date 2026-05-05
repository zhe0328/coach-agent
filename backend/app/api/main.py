from fastapi import FastAPI, Query
from typing import Optional
from ..services.coach_service import CoachService
from ..models.schema import ExerciseBase, ExerciseDetail

app = FastAPI()
coach_service = CoachService()

# --- 数据库直接查询接口 ---


@app.get("/exercises", response_model=list[ExerciseBase])
async def list_exercises(
    target: Optional[str] = None,
    equipment: Optional[str] = None,
    difficulty: Optional[str] = None,
    body_part: Optional[str] = None,
    category: Optional[str] = None,
    name: Optional[str] = None
):
    """直接获取数据库结果"""
    return await coach_service.get_exercises(
        target=target,
        equipment=equipment,
        difficulty=difficulty,
        body_part=body_part,
        category=category,
        name=name
    )


@app.get("/exercises/{exercise_id}", response_model=ExerciseDetail)
async def get_exercise(exercise_id: str):
    """获取特定动作详情"""
    return await coach_service.get_exercise_detail(exercise_id)


# --- AI 对话接口 ---


@app.post("/coach/chat")
async def chat_recommend(message: str):
    """AI 解析并从数据库匹配结果"""
    return await coach_service.get_ai_recommendation(message)
