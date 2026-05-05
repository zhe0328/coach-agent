import json
from openai import OpenAI
from ..config import settings

class CoachAgent:
    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def parse_user_intent(self, user_input: str):
        # 逻辑同前：将用户口语转化为 target, equipment, difficulty 的 JSON
        # ... 
        return {"target": "胸肌", "equipment": "哑铃", "difficulty": "beginner"}

    def generate_advice(self, exercises, user_input: str):
        """基于查到的数据提供专业指导（SKILL.md 逻辑在此体现）"""
        # 这里的 Prompt 可以要求 LLM 只输出具体的训练建议
        # 返回格式可以设计为字典供 Service 组装模型
        return {
            "warmup": "针对所选动作，建议先进行肩袖肌群激活。",
            "safety": "哑铃推举时注意腰椎不要过度超伸。"
        }
