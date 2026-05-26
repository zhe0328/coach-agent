from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import redis.asyncio as aioredis

from app.config import settings
from app.models.memory import ChatMessage, WorkingMemory
from app.agent.utils.logger import logger, LogColor

if TYPE_CHECKING:
    from app.tools.sql_tool import SQLTool


class WorkingMemoryManager:
    """
    工作记忆中枢 (Working Memory Manager)

    Redis 为热缓存；MySQL chat_records 为冷存储。
    当用户续聊旧 session 且 Redis 已过期或未命中时，从 MySQL 回填最近 K 轮对话并写回 Redis。
    """

    def __init__(
        self,
        max_history_turns: int = 4,
        ttl_seconds: int = 1800,
        sql_tool: Optional["SQLTool"] = None,
    ):
        self.redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        self.max_history_len = max_history_turns * 2  # user + assistant per turn
        self.ttl = ttl_seconds
        self._sql_tool = sql_tool

    def _redis_key(self, session_id: str) -> str:
        return f"working_memory:{session_id}"

    def _parse_working_memory(self, raw_json: str) -> WorkingMemory:
        if hasattr(WorkingMemory, "model_validate_json"):
            return WorkingMemory.model_validate_json(raw_json)
        return WorkingMemory.parse_raw(raw_json)

    def _get_sql_tool(self) -> "SQLTool":
        if self._sql_tool is None:
            from app.tools.sql_tool import SQLTool

            self._sql_tool = SQLTool()
        return self._sql_tool

    def records_to_chat_history(self, records: list[dict[str, Any]]) -> list[ChatMessage]:
        """将 MySQL chat_records 行转为 WorkingMemory 可用的对话列表。"""
        sorted_rows = sorted(records, key=lambda row: row.get("id") or 0)
        history: list[ChatMessage] = []

        for row in sorted_rows:
            role = row.get("role")
            content = (row.get("content") or "").strip()

            if role not in ("user", "assistant") or not content:
                continue

            history.append(ChatMessage(role=role, content=content))

        return history

    def _apply_sliding_window(self, memory: WorkingMemory) -> WorkingMemory:
        if len(memory.chat_history) > self.max_history_len:
            excess = len(memory.chat_history) - self.max_history_len
            memory.chat_history = memory.chat_history[excess:]
            logger.info(
                f"[WorkingMemory] ✂️ 会话 [{memory.session_id}] 历史裁剪，移除 {excess} 条旧消息。"
            )
        return memory

    async def hydrate_from_persistence(self, session_id: str) -> WorkingMemory:
        """
        从 MySQL chat_records 恢复该 session 的近期对话，并写入 Redis。
        若无历史记录则返回空白 WorkingMemory（不写 Redis）。
        """
        memory = WorkingMemory(session_id=session_id)

        try:
            records = await self._get_sql_tool().get_session_details(session_id)
        except Exception as e:
            logger.error(
                f"[WorkingMemory] 从 MySQL 拉取会话 [{session_id}] 历史失败: {e}"
            )
            return memory

        if not records:
            logger.info(
                f"{LogColor.TOOL}[WorkingMemory] 🧠 Redis 未命中，MySQL 亦无历史。"
                f"为新会话 [{session_id}] 初始化空白工作记忆。{LogColor.RESET}"
            )
            return memory

        memory.chat_history = self.records_to_chat_history(records)
        memory = self._apply_sliding_window(memory)

        await self.save_session_memory(session_id, memory)

        logger.info(
            f"{LogColor.TOOL}[WorkingMemory] 🔄 已从 MySQL 回填 "
            f"{len(memory.chat_history)} 条消息至 Redis，session=[{session_id}]{LogColor.RESET}"
        )
        return memory

    async def get_session_memory(self, session_id: str) -> WorkingMemory:
        """
        获取会话工作记忆：
        1. Redis 命中 → 直接返回
        2. Redis 未命中 → 从 MySQL chat_records 回填并缓存
        """
        redis_key = self._redis_key(session_id)

        try:
            raw_json = await self.redis.get(redis_key)
            if raw_json:
                return self._parse_working_memory(raw_json)
        except Exception as e:
            logger.error(
                f"[WorkingMemory] 读取 Redis 会话 [{session_id}] 失败: {e}，尝试 MySQL 回填。"
            )

        return await self.hydrate_from_persistence(session_id)

    async def save_session_memory(self, session_id: str, memory: WorkingMemory) -> None:
        """滑窗裁剪后写入 Redis，并刷新 TTL。"""
        redis_key = self._redis_key(session_id)
        memory = self._apply_sliding_window(memory)

        try:
            payload = (
                memory.model_dump_json()
                if hasattr(memory, "model_dump_json")
                else memory.json()
            )
            await self.redis.set(redis_key, payload, ex=self.ttl)
        except Exception as e:
            logger.error(
                f"[WorkingMemory] 写入 Redis 会话 [{session_id}] 失败: {e}"
            )

    def compile_to_llm_messages(self, memory: WorkingMemory) -> list[dict[str, str]]:
        """将 chat_history 转为 OpenAI/Qwen messages 数组。"""
        return [{"role": msg.role, "content": msg.content} for msg in memory.chat_history]
