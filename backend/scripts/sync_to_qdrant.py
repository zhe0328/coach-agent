import json
import mysql.connector
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from openai import OpenAI
from ..app.config import settings


class QdrantRAGSync:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL
        )
        self.qdrant = QdrantClient(
            url=settings.QDRANT_BASE_URL,
            api_key=settings.QDRANT_API_KEY,
            cloud_inference=False,
            timeout=120
        )
        self.collection_name = "exercises"

        # MySQL 连接
        self.db = mysql.connector.connect(
            host=settings.DB_HOST,
            user=settings.DB_USERNAME,
            password=settings.DB_PASSWORD,
            database=settings.DB_DATABASE,
        )

    def _get_embedding(self, text):
        """获取 OpenAI Embedding"""
        text = text.replace("\n", " ")
        return (
            self.client.embeddings.create(input=[text], model="text-embedding-3-small")
            .data[0]
            .embedding
        )

    def init_collection(self):
        """初始化 Qdrant 集合"""
        self.qdrant.recreate_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
        )

    def run_sync(self):
        cursor = self.db.cursor(dictionary=True)
        query = """
        SELECT e.id, e.name_zh, e.difficulty, e.description_zh, e.instructions_zh,
               t.name_zh as target_zh, eq.name_zh as equipment_zh
        FROM exercises e
        JOIN targets t ON e.target_id = t.id
        JOIN equipments eq ON e.equipment_id = eq.id
        """
        cursor.execute(query)
        rows = cursor.fetchall()

        batch_size = 50  # 每批向量化并上传的数量
        total = len(rows)
        print(f"开始同步，总计 {total} 条数据...")

        for i in range(0, total, batch_size):
            batch_rows = rows[i : i + batch_size]

            # 1. 构造该批次的文本列表
            texts_to_embed = []
            payloads = []
            ids = []

            for row in batch_rows:
                instructions = (
                    json.loads(row["instructions_zh"])
                    if isinstance(row["instructions_zh"], str)
                    else row["instructions_zh"]
                )
                steps_text = " ".join(
                    [f"{j+1}.{step}" for j, step in enumerate(instructions)]
                )
                combined_text = f"动作：{row['name_zh']}。目标肌肉：{row['target_zh']}。器材：{row['equipment_zh']}。描述：{row['description_zh']}。步骤：{steps_text}"
                texts_to_embed.append(combined_text)
                ids.append(int(row["id"]))
                payloads.append(
                    {
                        "name_zh": row["name_zh"],
                        "target_zh": row["target_zh"],
                        "equipment_zh": row["equipment_zh"],
                        "difficulty": row["difficulty"],
                        "content": combined_text,
                    }
                )

            # 2. 批量获取向量 (加速 10x)
            print(f"正在向量化批次 {i//batch_size + 1}...")
            embeddings_response = self.client.embeddings.create(
                input=texts_to_embed, model="text-embedding-3-small"
            )
            vectors = [data.embedding for data in embeddings_response.data]

            # 3. 构造 PointStruct 列表
            points = [
                PointStruct(id=ids[j], vector=vectors[j], payload=payloads[j])
                for j in range(len(ids))
            ]

            # 4. 上传到 Qdrant (此时 points 已在内存，上传极快)
            print(f"正在上传到 Qdrant...")
            try:
                self.qdrant.upsert(
                    collection_name=self.collection_name, points=points, wait=True
                )
                print(f"✅ 已完成 {min(i + batch_size, total)} / {total}")
            except Exception as e:
                print(f"❌ 上传失败: {e}")
                # 如果还超时，就在这里增加 retry 逻辑


if __name__ == "__main__":
    sync = QdrantRAGSync()
    sync.init_collection()
    sync.run_sync()
