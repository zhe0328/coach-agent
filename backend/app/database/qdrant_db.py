from qdrant_client import QdrantClient
from app.config import settings

class QdrantManager:
    # 单例模式能防止 API 并发时产生过多的连接
    _instance = None

    @classmethod
    def get_client(cls) -> QdrantClient:
        if cls._instance is None:
            cls._instance = QdrantClient(
                url=settings.QDRANT_BASE_URL,
                api_key=settings.QDRANT_API_KEY,
                timeout=60 # 处理你之前的超时问题
            )
        return cls._instance
