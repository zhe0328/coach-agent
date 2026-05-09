import json
import os
from openai import OpenAI
from ..config import settings

class CoachAgent:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL
        )
        # 加载逻辑框架 SKILL.md
        self.skill_guide = self._load_skill_guide()

    def _load_skill_guide(self):
        """读取本地的逻辑框架文档"""
        try:
            # 假设 SKILL.md 在项目根目录或 agent 目录下
            path = os.path.join(os.path.dirname(__file__), "SKILL.md")
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return "你是一位专业的健身教练，遵循科学的体能训练逻辑。"

    def parse_user_intent(self, user_input: str) -> dict:
        """
        意图识别：将用户的口语化需求转化为数据库查询参数
        """
        system_prompt = """
        你是一个健身需求解析器。请从用户输入中提取以下字段并返回 JSON 格式：
        - target: 目标肌肉 (如: 内收肌群, 腘绳肌, 腿背阔肌, 腹外斜肌)
        - equipment: 器材 (如: 哑铃, 杠铃, 徒手, 壶铃)
        - difficulty: 难度 (仅限: beginner, intermediate, advanced)
        - category: 运动类别 (如: 力量训练, 有氧运动)
        - body_part: 身体部位（如：背部，肩部，腰腹）
        
        注意：如果用户未提及某项，请设为 null。
        """
        
        response = self.client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            stream=False,
            reasoning_effort="low",
            response_format={"type": "json_object"}
        )
        print(response.choices[0].message.content)
        print("----------")
        return json.loads(response.choices[0].message.content)

    def generate_advice(self, exercises, user_input: str) -> dict:
        """
        基于检索出的动作和 SKILL.md 逻辑，生成专业的训练建议
        """
        # 将动作对象转换为简要描述，供 LLM 参考
        ex_summary = [
            f"动作: {ex.name_zh}, 目标: {ex.target_zh}, 难度: {ex.difficulty}" 
            for ex in exercises
        ]
        
        system_prompt = f"""
        你是一位顶级体能教练。你的训练逻辑遵循以下指南：
        {self.skill_guide}
        
        请根据用户需求和我们找到的动作，给出专业的建议。
        返回 JSON 格式，包含以下字段：
        - warmup: 针对这些动作的具体热身建议
        - safety: 关键的伤病预防与动作细节注意点
        - routine: 建议的组数和次数方案
        """
        
        user_msg = f"用户需求：{user_input}\n备选动作：{json.dumps(ex_summary, ensure_ascii=False)}"

        response = self.client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg}
            ],
            stream=False,
            reasoning_effort="high",
            response_format={"type": "json_object"}
        )
        print(response.choices[0].message.content)
        print("------------")
        return json.loads(response.choices[0].message.content)
