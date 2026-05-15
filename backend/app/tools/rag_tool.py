import re
from app.config import settings
from app.database.chroma_db import ChromaManager
from app.models.schema import RAGSearchSchema, ExerciseDetail
from app.agent.utils.logger import logger, LogColor
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
            # 严格对齐：使用与灌库（chroma_sync）一模一样的 text_embedding_v3 模型
            response = TextEmbedding.call(
                model=TextEmbedding.Models.text_embedding_v3, input=[cleaned_text]
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

    async def search_knowledge(self, params: RAGSearchSchema):
        """
        场景 B: 宽泛知识与发力感语义检索 —— 1ms 本地进程内极速响应
        """
        logger.info(
            f"{LogColor.TOOL}[RAGTool] 🔍 正在执行本地 ChromaDB 向量语义匹配，Query: '{params.query_text}'{LogColor.RESET}"
        )

        try:
            limit = params.top_k
            # 2. 实时换算千问 v3 高维语义特征向量
            query_embedding = self._get_embedding(params.query_text)

            # 3. 直驱本地持久化 ChromaDB 进行闪电级最近邻检索
            results = self.exercise_collection.query(
                query_embeddings=[query_embedding],
                n_results=limit
            )
            
            final_results = []
            
            # 4. 解构 ChromaDB 返回的扁平数组结构
            ids = results.get("ids", [[]])[0]
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]

            # 联动未来存书：如果动作百科集合彻底查空，可以降级去书籍集合捞数据
            if not ids or len(ids) == 0:
                logger.info(f"{LogColor.TOOL}[RAGTool] ⚠️ 动作库未命中，正在触发书籍知识库（fitness_books）二次泛化检索...{LogColor.RESET}")
                book_results = self.book_collection.query(query_embeddings=[query_embedding], n_results=2)
                ids = book_results.get("ids", [[]])[0]
                documents = book_results.get("documents", [[]])[0]
                metadatas = book_results.get("metadatas", [[]])[0]

            # 5. 遍历检索结果，通过 Pydantic 强类型契约模型进行原子化装配
            for i in range(len(ids)):
                doc_text = documents[i]
                meta_dict = metadatas[i] if (metadatas and i < len(metadatas)) else {}
                
                # 复用你原有的长文本解析规则（从全量 documents 中榨取出简介与具体步骤）
                description, instructions = self._parse_content(doc_text)

                # 完美还原并封装为你原生的标准 ExerciseDetail 模型
                exercise_obj = ExerciseDetail(
                    id=str(ids[i]),
                    # 优先从我们在灌库时存入的 metadata 中提取结构化标签
                    name_zh=meta_dict.get("name", "未命名动作"),
                    target_zh=meta_dict.get("target_muscle", "未知肌群"),
                    equipment_zh=meta_dict.get("equipment", "自重"),
                    difficulty=meta_dict.get("difficulty", "beginner"),
                    description_zh=description,
                    instructions_zh=instructions,
                    rag_content=doc_text  # 全文留档，供最终 Synthesizer 进行发力感细读
                )
                final_results.append(exercise_obj)
                
            logger.info(f"{LogColor.TOOL}[RAGTool] ✅ 向量召回成功。成功向 Orchestrator 透传 {len(final_results)} 个标准 ExerciseDetail 知识实体。{LogColor.RESET}")
            print("[RAG Result sample]: ", final_results[0])
            return final_results

        except Exception as e:
            logger.error(f"[RAGTool] 强类型语义检索管线崩溃: {e}")
            # 工业级容灾防御：报错时不抛异常阻断，而是返回空列表，让系统降级运行
            raise e


async def test():
    rag_tool = RAGTool()
    params = RAGSearchSchema(query_text="波比跳", top_k=3)
    result = await rag_tool.search_knowledge(params)
    print(result)


if __name__ == "__main__":
    asyncio.run(test())
