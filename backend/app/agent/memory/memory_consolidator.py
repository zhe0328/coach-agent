# app/agent/memory_consolidator.py
import json
from pydantic import BaseModel
from typing import Any
from app.agent.utils.logger import logger, LogColor
from app.models.memory import InjurySnifferSchema

class MemoryConsolidator:
    def __init__(self, graph_tool, client):
        self.graph_tool = graph_tool  # 挂载最新的完全体图工具类
        self.client = client
        self.model = "gpt-4o-mini"

    async def consolidate_session_to_graph(self, user_id: int, user_query: str):
        """[FastAPI 后台长驻线程]：压榨对话价值，让图谱中的用户语义画像自我进化"""
        system_prompt = "你是一个体育科学数据审计员。请精确分析用户的最新输入，看其是否暴露了新伤病或新买的器械。"
        
        try:
            # 1. 调遣大模型嗅探强契约
            response = await self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"用户原话: '{user_query}'"}
                ],
                response_format=InjurySnifferSchema,
                temperature=0.0
            )
            res = response.choices.message.parsed
            if not res: return

            if res.has_new_injury and res.joint and len(res.joint) > 0:
                await self.graph_tool.append_injury_list_to_profile(user_id, res.joint)
                
            if res.has_new_equipment and res.equipment_name and len(res.equipment_name) > 0:
                await self.graph_tool.append_equipment_list_to_profile(user_id, res.equipment_name)

        except Exception as e:
            logger.error(f"[Consolidator] 后台长效语义记忆异步演进断裂: {e}")
