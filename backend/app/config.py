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
    
    # 系统配置
    DEBUG: bool = False

    # 读取 .env 文件
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

# 实例化单例，供其他模块直接引用
settings = Settings()
