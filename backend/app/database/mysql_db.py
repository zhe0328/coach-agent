import mysql.connector
from ..config import settings


import mysql.connector.pooling
from app.config import settings

class MySQLManager:
    """
    使用连接池管理 MySQL 连接
    单例模式管理池本身，连接则通过池动态分发
    """
    _pool = None

    @classmethod
    def _get_pool(cls):
        if cls._pool is None:
            # 初始化连接池
            cls._pool = mysql.connector.pooling.MySQLConnectionPool(
                pool_name="coach_pool",
                pool_size=10,  # 允许 10 个并发连接
                host=settings.DB_HOST,
                user=settings.DB_USERNAME,
                password=settings.DB_PASSWORD,
                database=settings.DB_DATABASE,
                charset='utf8mb4',
                collation='utf8mb4_unicode_ci'
            )
        return cls._pool

    @classmethod
    def get_connection(cls):
        return cls._get_pool().get_connection()
