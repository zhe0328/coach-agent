import os
import pandas as pd
from qdrant_client import QdrantClient
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_recall,
    context_precision,
)
from config import settings


class RAGEvaluator:
    def __init__(self):
        # 1. 基础配置
        self.qdrant = QdrantClient(
            url=settings.QDRANT_BASE_URL, api_key=settings.QDRANT_API_KEY
        )
        self.collection_name = "exercises"

        # 2. 评估用的裁判模型
        self.evaluator_llm = ChatOpenAI(
            model="gpt-4o",
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )

        # 3. 你的 RAG 生成模型 (用于生成回答)
        self.rag_llm = ChatOpenAI(
            model="gpt-4.1-mini",
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )

    def _get_embedding(self, text):
        """为 Qdrant 检索生成向量"""
        return self.embeddings.embed_query(text)

    def get_rag_response(self, query_text):
        """
        模拟你的 RAG 完整流程：检索 + 生成
        """
        # A. 检索
        vector = self._get_embedding(query_text)
        hits = self.qdrant.query_points(
            collection_name=self.collection_name,
            query=vector,
            limit=5,
            with_payload=True,
        ).points

        retrieved_contexts = [hit.payload.get("content", "") for hit in hits]
        context_str = "\n\n".join(retrieved_contexts)

        # B. 生成答案 (Prompt 可以根据你的业务调整)
        prompt = f"请根据以下练习指令回答问题：\n{context_str}\n\n问题：{query_text}"
        response = self.rag_llm.invoke(prompt)

        return response.content, retrieved_contexts

    def run_evaluation(self, csv_path, output_path="evaluation_report_new.csv"):
        """
        主评估函数
        """
        # 1. 加载数据
        print(f"正在加载 Ground Truth: {csv_path}")
        df_gt = pd.read_csv(csv_path)

        # 如果 CSV 列名不同，请在此处重命名
        # 期望列: 'Question', 'Answer'

        results_data = []

        print("正在运行 RAG 系统获取预测结果...")
        for _, row in df_gt.iterrows():
            question = row["Question"]
            ground_truth = row["Answer"]

            # 获取系统输出
            answer, contexts = self.get_rag_response(question)

            results_data.append(
                {
                    "question": question,
                    "answer": answer,
                    "contexts": contexts,
                    "ground_truth": ground_truth,
                }
            )

        # 2. 转换为 Ragas 数据集
        dataset = Dataset.from_list(results_data)

        # 3. 调用 Ragas 评估
        print("正在启动 Ragas 评估 (裁判打分中)...")
        # 强制关闭异步以避免之前的 SSLError
        os.environ["IS_ASYNC"] = "False"

        score = evaluate(
            dataset=dataset,
            metrics=[faithfulness, answer_relevancy, context_recall, context_precision],
            llm=self.evaluator_llm,
            embeddings=self.embeddings,
        )

        # 4. 保存与输出
        df_report = score.to_pandas()
        df_report.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"✅ 评估完成！报告已保存至: {output_path}")
        print("\n各项指标平均得分:")
        print(score)

        return score


# --- 使用示例 ---
if __name__ == "__main__":
    evaluator = RAGEvaluator()
    # 确保你已经有了 ground_truth.csv
    evaluator.run_evaluation("/Users/eva/Documents/git/coach-agent/backend/app/ground_truth.csv")

    