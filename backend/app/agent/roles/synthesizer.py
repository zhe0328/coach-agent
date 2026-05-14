from openai import OpenAI
from ...config import settings
from ...models.schema import CoachResponse

class CoachSynthesizer:
    def __init__(self, client, skill_guide):
        self.client = client
        self.model = settings.LLM_MODEL_NAME
        self.skill_guide = skill_guide

    async def generate_response(self, user_input: str, tool_outputs: list, logic_chain: str):
        """
        JD 亮点：结合多路检索结果与 SKILL.md 生成专业回复
        tool_outputs 格式: [{"type": "sql", "data": [...]}, {"type": "graph", "data": [...]}]
        """
        
        # 1. 格式化上下文
        context_str = self._format_context(tool_outputs)
        print("context_str:")
        print(context_str)
        
        # 2. 构造 System Prompt (注入 SKILL.md)
        system_prompt = f"""
        你是一位具备生理学背景的资深体能教练。
        
        【执行准则】
        {self.skill_guide}
        
        【任务要求】
        请结合检索到的动作数据和安全逻辑，为用户生成建议。
        """

        # 3. 构造 User Prompt
        user_prompt = f"""
        用户的问题: "{user_input}"
        
        编排器思考路径: {logic_chain}
        
        检索到的原始信息:
        {context_str}
        
        请根据以上信息，生成最终的教练建议：
        
        ## 格式绝对禁止
        严禁在生成的文本中包含任何形如 `\u001b[32m`的终端颜色控制字符（ANSI Escape Codes）。统一且仅能使用标准的 Markdown 加粗语法, 各段落间不需要额外空行。
        """

        # 4. 调用强模型生成 (支持 Streaming 更好)
        response = self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7, # 保持一定的教练亲和力
            response_format=CoachResponse
        )
        
        return response.choices[0].message.content

    def _format_context(self, outputs: list) -> str:
        """将不同工具的输出归一化为 LLM 可理解的文本块"""
        formatted = []
        for out in outputs:
            t = out["type"]
            data = out.get("data")
            
            if t == "sql":
                formatted.append(f"[基础动作库结果]: {data}")
            elif t == "rag":
                formatted.append(f"[深度动作百科/步骤]: {data}")
            elif t == "graph":
                formatted.append(f"[生理逻辑/伤病风险提示]: {data}")
        
        return "\n".join(formatted)
