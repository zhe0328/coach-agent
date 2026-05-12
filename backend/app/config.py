from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # 数据库配置
    DB_HOST: str = "localhost"
    DB_USERNAME: str = "root"
    DB_PASSWORD: str
    DB_DATABASE: str = "coach_agent_db"
    DB_PORT: int = 3306

    # AI 配置
    OPENAI_API_KEY: str
    OPENAI_BASE_URL: Optional[str] = "https://openai.com"

    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: Optional[str] = "https://api.deepseek.com"

    QDRANT_API_KEY: str
    QDRANT_BASE_URL: Optional[str] = "https://xyz-example.eu-central.aws.cloud.qdrant.io"

    NEO4J_BASE_URL: Optional[str] = "neo4j+ssc://xxx.databases.neo4j.io"
    NEO4J_USERNAME: str
    NEO4J_PASSWORD: str

    LLM_MODEL_NAME: str
    
    # 系统配置
    DEBUG: bool = False

    # CORS配置
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"

    # 读取 .env 文件
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    def get_cors_origins_list(self) -> list[str]:
        """获取CORS origins列表"""
        return [origin.strip() for origin in self.cors_origins.split(',')]


# 实例化单例，供其他模块直接引用
settings = Settings()

def get_settings() -> Settings:
    """获取配置实例"""
    return settings
