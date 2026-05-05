from ..database.database import search_exercise_base, search_exercise_detail
from ..agent.coach_agent import CoachAgent
from ..models.schema import ExerciseDetail, CoachRecommendation

class CoachService:
    def __init__(self):
        self.agent = CoachAgent()

    # 路径 A: 直接查询数据库
    async def get_exercises(self, **filters):
        # 这里的 filters 包含 target, equipment, difficulty 等
        return search_exercise_base(**filters)

    async def get_exercise_detail(self, exercise_id: str):
        return search_exercise_detail(exercise_id)

    # 路径 B: AI 驱动的推荐
    async def get_ai_recommendation(self, user_input: str) -> CoachRecommendation:
        # 1. 意图解析 (Agent)
        params = self.agent.parse_user_intent(user_input)
        
        # 2. 调用本 Service 的查询方法 (Repo)
        exercises = await self.get_exercises(
            target=params.get("target"),
            equipment=params.get("equipment"),
            difficulty=params.get("difficulty"),
            limit=5
        )
        
        # 3. 结合结果生成教练语录 (Agent)
        advice = self.agent.generate_advice(exercises, user_input)
        
        return CoachRecommendation(
            user_intent=params,
            planned_exercises=exercises,
            warmup_tips=advice.get("warmup"),
            safety_notes=advice.get("safety")
        )
