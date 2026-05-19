from typing import Dict
import redis.asyncio as aioredis
from app.models.memory import WorkingMemory
from app.config import settings
from app.agent.utils.logger import logger, LogColor

class WorkingMemoryManager:
    """
    工作记忆中枢 (Working Memory Manager)
    职责：基于 Session ID 持久化维护会话活性，支持自愈状态机的流转与滑窗裁剪
    """
    def __init__(self, max_history_turns: int = 4, ttl_seconds: int = 1800):
        # 生产环境推荐替换为：self.redis_client = ...
        # 本地开发使用高性能内存字典进行物理隔离
        redis_url = settings.REDIS_URL
        self.redis = aioredis.from_url(redis_url, decode_responses=True)
        self.max_history_len = max_history_turns * 2  # 一轮包含 user + assistant 两条，所以乘以 2
        self.ttl = ttl_seconds # 默认工作记忆存活 30 分钟

    async def get_session_memory(self, session_id: str) -> WorkingMemory:
        """获取或静默创建该会话的工作记忆"""
        redis_key = f"working_memory:{session_id}"
        try:
            # 从 Redis 抓取固化的 JSON 字符串
            raw_json = await self.redis.get(redis_key)
            
            if raw_json:
                return WorkingMemory.parse_raw(raw_json)
                
            # 若不存在，说明是全新会话，直接初始化一个白板对象
            logger.info(f"{LogColor.TOOL}[WorkingMemory] 🧠 Redis 未命中。已为新会话 [{session_id}] 独立开辟无污染缓存空间。{LogColor.RESET}")
            return WorkingMemory(session_id=session_id)
            
        except Exception as e:
            logger.error(f"[WorkingMemory] 从 Redis 读取会话 [{session_id}] 失败: {e}，触发内存级降级容灾。")
            return WorkingMemory(session_id=session_id)

    async def save_session_memory(self, session_id: str, memory: WorkingMemory):
        """
        [异步方法]：执行滑窗裁剪，并将最新的记忆状态固化回 Redis，刷新 TTL 倒计时
        """
        redis_key = f"working_memory:{session_id}"
        
        # 1. 严格执行 FIFO 滑窗裁剪（保持最近 K 轮对话，防止上下文肥大）
        if len(memory.chat_history) > self.max_history_len:
            excess = len(memory.chat_history) - self.max_history_len
            memory.chat_history = memory.chat_history[excess:]
            logger.info(f"[WorkingMemory] ✂️ 触发会话 [{session_id}] 历史滚动裁剪，已自动剔除 {excess} 条过期流。")
            
        try:
            # 2. 序列化为高密度的标准 JSON 字符串
            serialized_json = memory.model_dump_json()
            
            # 3. 物理写入 Redis，并强行绑定 EX (过期秒数)，刷新 30 分钟的生命周期倒计时！
            await self.redis.set(redis_key, serialized_json, ex=self.ttl)
            
        except Exception as e:
            logger.error(f"[WorkingMemory] 将会话 [{session_id}] 固化至 Redis 遭遇异常: {e}")

    def compile_to_llm_messages(self, memory: WorkingMemory) -> list:
        """将当前工作记忆里的 chat_history 转化为标准 OpenAI/Qwen 的 messages 数组格式"""
        messages = []
        for msg in memory.chat_history:
            messages.append({"role": msg.role, "content": msg.content})
        return messages
