from unicodedata import category
from ..database.database import search_exercise_base, search_exercise_detail
from ..agent.coach_agent import CoachAgent
from ..models.schema import ExerciseBase, ExerciseDetail, CoachRecommendation

class CoachService:
    def __init__(self):
        self.agent = CoachAgent()

    # 路径 A: 直接查询数据库
    async def get_exercises(self, **filters) -> list[ExerciseBase]:
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
            category=params.get("category"),
            body_part=params.get("body_part"),
            limit=5
        )

        print("exercises type:", type(exercises))
        
        if not exercises:
            return CoachRecommendation(
                user_intent=params,
                planned_exercises=[],
                warmup_tips="抱歉，未能匹配到合适的动作。",
                safety_notes="请尝试更换器材或训练目标关键词。"
            )

        # 4. 专业逻辑生成：将查到的动作对象列表和原始输入传给 Agent
        # Agent 会根据这些数据和 SKILL.md 生成具体的建议
        advice = self.agent.generate_advice(exercises, user_input)

        print("advice type:", type(advice))
        
        # 5. 组装并返回统一的模型对象
        return CoachRecommendation(
            user_intent=params,
            planned_exercises=exercises,
            warmup_tips=advice.get("warmup", "常规动态拉伸。"),
            safety_notes=advice.get("safety", "注意动作规范，避免借力。"),
            routine=advice.get("routine", "建议 3 组，每组 12-15 次。") # 扩展了建议字段
        )
