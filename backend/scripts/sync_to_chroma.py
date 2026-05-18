# app/database/chroma_sync.py
import mysql.connector
import json
import dashscope
from dashscope import TextEmbedding
from app.config import settings
from app.database.chroma_db import ChromaManager
from app.agent.utils.logger import logger, LogColor

# 显式注入通义千问的鉴权密钥
dashscope.api_key = settings.DASHSCOPE_API_KEY 

class ChromaSync:
    def __init__(self):
        self.mysql_conn = mysql.connector.connect(
            host=settings.DB_HOST,
            user=settings.DB_USERNAME,
            password=settings.DB_PASSWORD,
            database=settings.DB_DATABASE,
        )
        self.chroma_manager = ChromaManager()
        self.collection = self.chroma_manager.get_exercise_collection()

    def close(self):
        self.mysql_conn.close()

    def _get_qwen_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        调用通义千问原生中文高维向量接口，彻底压低网络延迟，保障中文语义精准度
        """
        try:
            # 使用千问最新、最推荐的通用文本向量模型 text-embedding-v4
            response = TextEmbedding.call(
                model=TextEmbedding.Models.text_embedding_v4,
                input=texts
            )
            if response.status_code == 200:
                # 提取千问返回的特征稠密向量列表
                return [record['embedding'] for record in response.output['embeddings']]
            else:
                raise Exception(f"千问 API 报错: {response.message}")
        except Exception as e:
            logger.error(f"[ChromaSync] 唤醒通义千问 Embedding 失败: {e}")
            raise e

    def run_sync(self):
        logger.info(f"{LogColor.TOOL}[ChromaSync] 🔄 正在清空旧的本地 Chroma 动作语义知识库...{LogColor.RESET}")
        try:
            existing_ids = self.collection.get()["ids"]
            if existing_ids:
                self.collection.delete(ids=existing_ids)
        except Exception as e:
            logger.warning(f"[ChromaSync] 清空旧库捕获异常: {e}")
            raise e

        cursor = self.mysql_conn.cursor(dictionary=True)
        query = """
            SELECT e.id, e.name_zh, e.difficulty, e.description_zh, e.instructions_zh,
                t.name_zh as target_muscle, b.name_zh as body_part, eq.name_zh as equipment_name
            FROM exercises e
            JOIN targets t ON e.target_id = t.id
            JOIN body_parts b ON e.body_part_id = b.id
            JOIN equipments eq on e.equipment_id = eq.id
            """
        cursor.execute(query)
        exercises = cursor.fetchall()
        cursor.close()

        logger.info(f"{LogColor.TOOL}[ChromaSync] 📥 从 MySQL 召回 {len(exercises)} 条资产，开始构建中文语义切片...{LogColor.RESET}")

        ids = []
        documents = []
        metadatas = []

        for ex in exercises:
            instructions = ex['instructions_zh']
            instructions = json.loads(instructions)
            description = ex['description_zh'] or "暂无详细描述"
            dense_text = (
                f"动作名称：{ex['name_zh']}。训练部位：{ex['body_part']}。主目标肌群：{ex['target_muscle']}。器材：{ex['equipment_name']}"
                f"动作简介：{description}。执行步骤规范：{instructions}"
            )
            ids.append(str(ex['id']))
            documents.append(dense_text)
            metadatas.append({
                "name": ex['name_zh'],
                "difficulty": ex['difficulty'],
                "target_muscle": ex['target_muscle'],
                "body_part": ex['body_part'],
                "equipment": ex['equipment_name']
            })

        if ids:
            logger.info(f"{LogColor.TOOL}[ChromaSync] 🧠 正在通过【通义千问 (text-embedding-v4)】批量换算中文高维向量...{LogColor.RESET}")
            
            # 千问 API 同样支持批量分批，这里设置每批 10 条，兼顾稳定与带宽
            batch_size = 10
            embeddings = []
            for i in range(0, len(documents), batch_size):
                batch_texts = documents[i:i+batch_size]
                batch_embeddings = self._get_qwen_embeddings(batch_texts)
                embeddings.extend(batch_embeddings)

            # 显式注入千问向量，100% 绕过 Chroma 默认模型的网络下载限制
            self.collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings, 
                metadatas=metadatas
            )
            logger.info(f"{LogColor.TOOL}[ChromaSync] 🎉 成功同步 {len(ids)} 个具有【千问原生中文语义特征】的动作切片至本地 ChromaDB！{LogColor.RESET}")
        else:
            logger.warning("[ChromaSync] 未提取到有效数据。")

if __name__ == "__main__":
    syncer = ChromaSync()
    try:
        syncer.run_sync()
    finally:
        syncer.close()
