# app/database/chroma_book_sync.py
import os
import glob
import re
import json
import dashscope
from dashscope import TextEmbedding
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.config import settings
from app.database.chroma_db import ChromaManager
from app.agent.utils.logger import logger, LogColor

# 显式激活通义千问鉴权密钥
dashscope.api_key = settings.DASHSCOPE_API_KEY


class ChromaBookSync:
    def __init__(self):
        self.chroma_manager = ChromaManager()
        self.collection = self.chroma_manager.get_book_collection()

    def _get_qwen_embeddings(self, texts: list[str]) -> list[list[float]]:
        """调用通义千问 text-embedding-v4 向量接口"""
        try:
            response = TextEmbedding.call(
                model=TextEmbedding.Models.text_embedding_v4, input=texts
            )
            if response.status_code == 200:
                return [record["embedding"] for record in response.output["embeddings"]]
            else:
                raise Exception(f"通义千问 API 报错: {response.message}")
        except Exception as e:
            logger.error(f"[BookSync] 换算千问 Embedding 遭遇异常: {e}")
            raise e

    def split_by_single_hash(self, content: str) -> list[dict]:
        """
        第一级切分：利用唯一的一级标题 '#' 将整本书切分成宏观的板块/章节
        返回: [{"header": "章节名", "body": "这一章的全量长正文"}]
        """
        # 使用正则捕捉所有的 '# 标题名'
        # (?=\n#\s) 代表前瞻匹配，确保保留标题符号
        sections = re.split(r"\n(?=#\s)", "\n" + content)

        results = []
        for sec in sections:
            sec = sec.strip()
            if not sec:
                continue

            # 榨取出当前的标题名字
            match = re.match(r"^#\s*(.*)", sec)
            if match:
                header_title = match.group(1).split("\n")[0].strip()
                # 剔除第一行标题后的纯正文
                body_content = "\n".join(sec.split("\n")[1:]).strip()
            else:
                header_title = "未分类前言/背景"
                body_content = sec

            results.append({"header": header_title, "body": body_content})
        return results

    def run_sync_books(self):
        logger.info(
            f"{LogColor.TOOL}[BookSync] 🔄 正在清空旧的本地 Chroma 生理学图书知识库...{LogColor.RESET}"
        )
        try:
            existing = self.collection.get()
            if existing and existing["ids"]:
                self.collection.delete(ids=existing["ids"])
        except Exception as e:
            logger.warning(f"[BookSync] 旧图书集合清空失败: {e}")

        current_dir = os.path.dirname(os.path.abspath(__file__))
        source_dir = os.path.join(current_dir, "../data/book_source")
        md_files = glob.glob(os.path.join(source_dir, "*.md"))

        if not md_files:
            logger.error(
                f"[BookSync] ❌ 错误：未能在目录 {source_dir} 下找到任何 .md 书籍文件！"
            )
            return

        # 💡【微观二级切分器契约】：定义黄金滑动窗口
        # 对于中文运动生理学而言，500字足以为大模型提供一个结构相对完整的段落背景
        # chunk_overlap=100 极其重要，能强行确保长句机制不被拦腰斩断
        child_text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=100,
            separators=[
                "\n\n",
                "\n",
                "。",
                "！",
                "？",
                "；",
                " ",
                "",
            ],  # 优先根据句号断句，保持中文发力感句式自然完整
        )

        all_ids = []
        all_documents = []
        all_metadatas = []
        chunk_counter = 0

        logger.info(
            f"{LogColor.TOOL}[BookSync] 📖 启动自适应双指针滑动窗口算法，解析 {len(md_files)} 本专业语料...{LogColor.RESET}"
        )

        for file_path in md_files:
            file_name = os.path.basename(file_path)
            logger.info(f"[BookSync]   -> 正在读取: 【{file_name}】")

            with open(file_path, "r", encoding="utf-8") as f:
                md_content = f.read()

            # 第一步：根据唯一的一级标题划分宏观版块
            macro_sections = self.split_by_single_hash(md_content)

            for sec_data in macro_sections:
                header_title = sec_data["header"]
                body_text = sec_data["body"]

                if not body_text:
                    continue

                # 第二步：对每一个版块的超长正文进行微观滑动切片
                sub_chunks = child_text_splitter.split_text(body_text)

                for sub_text in sub_chunks:
                    chunk_counter += 1

                    # 💡【核心高级特性：语义焊接（Contextual Injection）】
                    # 由于你的 Markdown 没有 H2/H3，当滑动切片切到文章中部时，文本会彻底失去上下文。
                    # 我们强行把书名、以及这一章唯一的 `#` 标题焊接在每个 500 字段落的头部！
                    # 强行确保切片在降维后的高维空间里拥有 100% 绝对安全的场景辨识指纹！
                    dense_document = (
                        f"【图书来源】: {file_name} | 【所属章节主题】: {header_title}\n"
                        f"【核心生理学与执教知识点】:\n{sub_text.strip()}"
                    )

                    unique_id = f"book_chunk_{chunk_counter}"

                    all_ids.append(unique_id)
                    all_documents.append(dense_document)
                    all_metadatas.append(
                        {
                            "source_book": file_name,
                            "chapter_title": header_title,
                            "category": "physiology_and_logic",
                        }
                    )

        # 5. 锁死为 10 条的步长进行全量向量化落盘
        if all_ids:
            logger.info(
                f"{LogColor.TOOL}[BookSync] 🧠 正在批量换算 {len(all_documents)} 个高密度图书切片向量...{LogColor.RESET}"
            )
            batch_size = 10
            all_embeddings = []

            for i in range(0, len(all_documents), batch_size):
                batch_texts = all_documents[i : i + batch_size]
                batch_embs = self._get_qwen_embeddings(batch_texts)
                all_embeddings.extend(batch_embs)

            self.collection.add(
                ids=all_ids,
                documents=all_documents,
                embeddings=all_embeddings,
                metadatas=all_metadatas,
            )
            logger.info(
                f"{LogColor.TOOL}[BookSync] 🎉 全面大通车！{len(all_ids)} 个高质量中文生理学知识切片已完美闭环注入本地 ChromaDB！{LogColor.RESET}"
            )
        else:
            logger.warning("[BookSync] 未能提取到有效文本。")


if __name__ == "__main__":
    syncer = ChromaBookSync()
    syncer.run_sync_books()
