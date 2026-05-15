# app/database/chroma_db.py
import os
import threading
import chromadb
from app.agent.utils.logger import logger, LogColor

class ChromaManager:
    _instance = None
    _lock = threading.Lock()  # 线程锁，确保高并发多线程下绝对的单例安全

    def __new__(cls, *args, **kwargs):
        """
        双重检查锁定（Double-Checked Locking）单例模式
        确保高并发访问时，整个 Python 进程生命周期内只初始化一个本地持久化 Client
        """
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(ChromaManager, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        # 拦截重复初始化
        if not hasattr(self, 'initialized'):
            # 1. 动态定位本地存储路径：在项目根目录下的 data/chroma 文件夹中
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # 向上追溯到根目录下的 data/chroma
            self.persist_path = os.path.join(current_dir, "../../data/chroma")
            
            logger.info(f"{LogColor.TOOL}[ChromaManager] 💾 正在启动 Serverless 本地文件持久化引擎... 目录: {self.persist_path}{LogColor.RESET}")
            
            # 2. 初始化持久化客户端（彻底取代原先 Qdrant 6333 端口的分布式网络连接）
            self.client = chromadb.PersistentClient(path=self.persist_path)
            
            # 3. 前置预创建并预热核心业务集合（Collections），对齐你未来的动作与图书存书业务
            self.exercise_collection = self.client.get_or_create_collection(
                name="exercise_knowledge",
                metadata={"hnsw:space": "cosine"} # 使用最适配健身文本语义重排的余弦相似度
            )
            self.book_collection = self.client.get_or_create_collection(
                name="fitness_books",
                metadata={"hnsw:space": "cosine"}
            )
            
            self.initialized = True
            logger.info(f"{LogColor.TOOL}[ChromaManager] 🎉 本地高维向量 HNSW 空间内核初始化成功，连接池单例已就绪。{LogColor.RESET}")

    def get_client(self) -> chromadb.PersistentClient:
        """获取底层的全局持久化客户端"""
        return self.client

    def get_exercise_collection(self):
        """获取标准动作/百科知识库集合"""
        return self.exercise_collection

    def get_book_collection(self):
        """获取未来存放长文本大部头健身书籍的知识库集合"""
        return self.book_collection
