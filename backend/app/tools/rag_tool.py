import re
from app.config import settings
from app.database.async_db import run_in_thread
from app.database.chroma_db import ChromaManager
from app.models.schema import RAGSearchSchema, ExerciseDetail, KnowledgeChunk
from app.agent.utils.logger import logger, LogColor
from typing import Union, List
import asyncio


class RAGTool:
    def __init__(self):
        self.chroma_manager = ChromaManager()
        self.chroma_client = self.chroma_manager.get_client()
        self.exercise_collection = self.chroma_manager.get_exercise_collection()
        self.book_collection = self.chroma_manager.get_book_collection()

    def _get_embedding(self, text: str) -> list[float]:
        """
        核心修复点：将实时提问向量化模型由 OpenAI 同步切置为通义千问
        - 消除 \n 换行噪音，确保长文本语义完整度
        """
        import dashscope
        from dashscope import TextEmbedding

        # 确保鉴权密钥已被正确绑定
        dashscope.api_key = settings.DASHSCOPE_API_KEY

        # 清理由于 Markdown 或大模型输入带来的异常换行噪音
        cleaned_text = text.replace("\n", " ").strip()

        if not cleaned_text:
            raise ValueError("[RAGTool] 实时向量化文本为空，无法换算特征向量。")

        try:
            # 严格对齐：使用与灌库（chroma_sync）一模一样的 text_embedding_v4 模型
            response = TextEmbedding.call(
                model=TextEmbedding.Models.text_embedding_v4, input=[cleaned_text]
            )

            if response.status_code == 200:
                # 榨取千问返回的单条特征向量 [0.12, -0.45, ...]
                return response.output["embeddings"][0]["embedding"]
            else:
                raise Exception(f"通义千问 Embedding 实时计算失败: {response.message}")

        except Exception as e:
            logger.error(f"[RAGTool] 唤醒通义千问实时 Embedding 遭遇严重异常: {e}")
            raise e

    def _parse_content(self, content: str):
        """
        解析 payload 中的 content 字符串
        提取描述 (description_zh) 和 步骤列表 (instructions_zh)
        """
        # 使用正则匹配“描述：”和“步骤：”之间的内容
        desc_match = re.search(r"动作简介：(.*?)。执行步骤规范：", content)
        description = desc_match.group(1).strip() if desc_match else ""

        # 匹配“步骤：”之后的所有内容
        instr_match = re.search(r"执行步骤规范：(.*)", content)
        instr_raw = instr_match.group(1).strip() if instr_match else ""

        # 将步骤字符串拆分为列表 (根据序号 1. 2. 3. 拆分)
        # 结果示例: ["仰卧在垫上...", "双手置于脑后..."]
        instructions = re.split(r"\s*\d+\.\s*", instr_raw)
        instructions = [i.strip() for i in instructions if i.strip()]

        return description, instructions

    async def search_knowledge(self, params: RAGSearchSchema) -> List[Union[ExerciseDetail, KnowledgeChunk]]:
        """
        场景 B: 宽泛知识与发力感语义检索 —— 【方案2】基于大模型智能意图路由的双库解耦解构管线
        """
        logger.info(
            f"{LogColor.TOOL}[RAGTool] 🔍 启动智能路由多库检索，Query: '{params.query_text}', Intent: '{params.intent}' {LogColor.RESET}"
        )

        try:
            limit = params.top_k
            
            # 2. 第二步：根据意图，动态分配各个 Collection 的检索配额 (Top-K)
            if params.intent == "exercise":
                exe_limit = limit
                book_limit = 0  # 纯动作查询，不浪费算力查书库
            elif params.intent == "knowledge":
                book_limit = limit
                exe_limit = 0   # 纯理论机制查询，不查动作百科
            else:  # mixed 混合意图
                book_limit = max(2, limit - 1)  # 均衡分配
                exe_limit = max(1, limit - book_limit)

            # 3. 实时换算查询文本的千问 1024 维特征向量（线程池，避免阻塞事件循环）
            query_embedding = await run_in_thread(
                self._get_embedding, params.query_text
            )
            
            final_results = []
            seen_contents = set()  # 去重锁

            # === 轨迹 A: 动作库精准装配 ===
            if exe_limit > 0:
                exe_results = await run_in_thread(
                    self.exercise_collection.query,
                    query_embeddings=[query_embedding],
                    n_results=exe_limit,
                )
                exe_ids = exe_results.get("ids", [[]])[0]
                exe_docs = exe_results.get("documents", [[]])[0]
                exe_metas = exe_results.get("metadatas", [[]])[0]

                for i in range(len(exe_ids)):
                    doc_text = exe_docs[i]
                    if doc_text in seen_contents: continue
                    seen_contents.add(doc_text)
                    
                    meta_dict = exe_metas[i] if (exe_metas and i < len(exe_metas)) else {}
                    description, instructions = self._parse_content(doc_text)

                    final_results.append(ExerciseDetail(
                        id=str(exe_ids[i]),
                        name_zh=meta_dict.get("name", "未命名动作"),
                        body_part_zh=meta_dict.get("body_part", "未知肌群"),
                        target_zh=meta_dict.get("target_muscle", "未知肌群"),
                        equipment_zh=meta_dict.get("equipment", "自重"),
                        difficulty=meta_dict.get("difficulty", "beginner"),
                        description_zh=description,
                        instructions_zh=instructions,
                        rag_content=doc_text
                    ))

            # === 轨迹 B: 书籍理论库装配 ===
            if book_limit > 0:
                book_results = await run_in_thread(
                    self.book_collection.query,
                    query_embeddings=[query_embedding],
                    n_results=book_limit,
                )
                book_ids = book_results.get("ids", [[]])[0]
                book_docs = book_results.get("documents", [[]])[0]
                book_metas = book_results.get("metadatas", [[]])[0]
                book_distances = book_results.get("distances", [[]])[0]

                for i in range(len(book_ids)):
                    doc_text = book_docs[i]
                    if doc_text in seen_contents: continue
                    seen_contents.add(doc_text)
                    
                    meta_dict = book_metas[i] if (book_metas and i < len(book_metas)) else {}
                    dist = book_distances[i] if (book_distances and i < len(book_distances)) else 0.5
                    
                    raw_mechanisms = meta_dict.get("mechanisms", "none")
                    principles = [p for p in raw_mechanisms.split(",") if p != "none"]

                    knowledge_obj = KnowledgeChunk(
                        id=str(book_ids[i]),
                        source_book=meta_dict.get("source_book", "未知体能教材.md"),
                        chapter_title=meta_dict.get("chapter_title", "核心理论"),
                        category=meta_dict.get("category", "physiology_and_logic"),
                        core_principles=principles,
                        content=doc_text,
                        cosine_similarity=round(1.0 - dist, 4)
                    )
                    
                    # 混合模式下，理论知识往往是限制性条件，优先置顶
                    if params.intent == "mixed":
                        final_results.insert(0, knowledge_obj)
                    else:
                        final_results.append(knowledge_obj)

            # 4. 安全拦截与最终截断
            final_results = final_results[:limit]
            logger.info(f"{LogColor.TOOL}[RAGTool] ✅ 大模型路由双库融合装配通车。输出实体数: {len(final_results)}{LogColor.RESET}")
            return final_results

        except Exception as e:
            logger.error(f"[RAGTool] 大模型智能路由检索管线发生崩溃: {e}")
            raise e

async def test():
    rag_tool = RAGTool()
    params = RAGSearchSchema(query_text="退阶动作的动作原理 髋关节保护", top_k=3, intent="knowledge")
    result = await rag_tool.search_knowledge(params)
    print(result)


if __name__ == "__main__":
    asyncio.run(test())
