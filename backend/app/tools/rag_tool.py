import re
from openai import OpenAI
from app.config import settings
from app.database.qdrant_db import QdrantManager
from app.models.schema import RAGSearchSchema, ExerciseDetail
from flashrank import Ranker, RerankRequest
from qdrant_client import models
import asyncio


class RAGTool:
    def __init__(self):
        self.ai_client = OpenAI(
            api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL
        )
        self.qdrant_client = QdrantManager.get_client()
        self.collection_name = "exercises_v2"
        self.ranker = Ranker()

    def _get_embedding(self, text: str):
        response = self.ai_client.embeddings.create(
            input=[text.replace("\n", " ")], model="text-embedding-3-small"
        )
        return response.data[0].embedding

    def _parse_content(self, content: str):
        """
        解析 payload 中的 content 字符串
        提取描述 (description_zh) 和 步骤列表 (instructions_zh)
        """
        # 使用正则匹配“描述：”和“步骤：”之间的内容
        desc_match = re.search(r"效果和描述：(.*?)。执行步骤：", content)
        description = desc_match.group(1).strip() if desc_match else ""

        # 匹配“步骤：”之后的所有内容
        instr_match = re.search(r"执行步骤：(.*)", content)
        instr_raw = instr_match.group(1).strip() if instr_match else ""

        # 将步骤字符串拆分为列表 (根据序号 1. 2. 3. 拆分)
        # 结果示例: ["仰卧在垫上...", "双手置于脑后..."]
        instructions = re.split(r"\s*\d+\.\s*", instr_raw)
        instructions = [i.strip() for i in instructions if i.strip()]

        return description, instructions

    async def search_knowledge(self, params: RAGSearchSchema):
        query_vector = self._get_embedding(params.query_text)

        # 搜索 Qdrant
        search_results = self.qdrant_client.query_points(
            collection_name="exercises_v2",
            prefetch=[
                # 增加 header 的检索深度，因为它是核心
                models.Prefetch(query=query_vector, using="header", limit=15),
                # detail 仅作辅助参考
                models.Prefetch(query=query_vector, using="detail", limit=3),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),  # 融合两路结果
            limit=10,
            with_payload=True,
        ).points

        # 2. 构造重排请求
        passages = []
        for hit in search_results:
            passages.append(
                {"id": hit.id, "text": hit.payload.get("content"), "meta": hit.payload}
            )

        rerankrequest = RerankRequest(query=params.query_text, passages=passages)

        # 3. 执行重排
        rerank_results = self.ranker.rerank(rerankrequest)

        final_results = []
        for res in rerank_results[: params.top_k]:
            p = res["meta"]
            description, instructions = self._parse_content(res["text"])

            # 封装为统一的 ExerciseDetail 模型
            exercise_obj = ExerciseDetail(
                id=str(res["id"]),
                name_zh=p.get("name_zh"),
                target_zh=p.get("target_zh"),
                equipment_zh=p.get("equipment_zh"),
                difficulty=p.get("difficulty"),
                description_zh=description,
                instructions_zh=instructions,
                rag_content=res["text"],  # 保留原始全文供 Agent 参考
            )
            final_results.append(exercise_obj)

        # final_results = []
        # for res in search_results:
        #     p = res.payload
        #     # description, instructions = self._parse_content(res["text"])
        #     raw_instructions = p.get("instructions_zh", [])
        #     # 封装为统一的 ExerciseDetail 模型
        #     exercise_obj = ExerciseDetail(
        #         id=str(res.id),
        #         name_zh=p.get("name_zh"),
        #         target_zh=p.get("target_zh"),
        #         equipment_zh=p.get("equipment_zh"),
        #         difficulty=p.get("difficulty"),
        #         description_zh=p.get("description_zh"),
        #         instructions_zh=raw_instructions,
        #         rag_content=p.get("content"),  # 保留原始全文供 Agent 参考
        #     )
        #     final_results.append(exercise_obj)

        return final_results


async def test():
    rag_tool = RAGTool()
    params = RAGSearchSchema(query_text="前锯肌 训练 动作原理 发力方式", top_k=3)
    result = await rag_tool.search_knowledge(params)
    print(result)


if __name__ == "__main__":
    asyncio.run(test())
