# scripts/bake_unified_ragas_official.py
import os
import json
import random
import asyncio
from typing import List, Any

# 💡 引入 LangChain 与 Ragas 官方包装外壳，确保 compatible 
from langchain_openai import ChatOpenAI
from langchain_community.embeddings import DashScopeEmbeddings
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.testset import TestsetGenerator
from ragas.testset.persona import Persona
from ragas.testset.synthesizers.single_hop.specific import SingleHopSpecificQuerySynthesizer
from ragas.testset.synthesizers.multi_hop.specific import MultiHopSpecificQuerySynthesizer
from ragas.testset.synthesizers.multi_hop.abstract import MultiHopAbstractQuerySynthesizer
from ragas.testset.transforms import default_transforms
from langchain_core.documents import Document

# 引入你项目里唯一的、支持线程池和异步的三大库管理单例
from app.tools.sql_tool import SQLTool   # 👈 你的同步线程池版管理器
from app.tools.graph_tool import GraphTool     # 👈 你的完全体 Neo4j 异步大一统工具
from app.tools.rag_tool import RAGTool       # 👈 你的 Chroma 向量库单例
from app.config import settings
from app.agent.utils.logger import logger

# ====================================================================
# 🛡️ 【猴子补丁】：100% 物理修复新版 Ragas 官方 LangchainLLMWrapper 缺失异步方法漏洞
# ====================================================================
random.seed(42)

personas = [
    Persona(
        name="Adaptive Fitness Client",
        role_description=(
            "你是一个正在寻求专业 AI 健身教练指导的真实大众用户。你的特点是：\n"
            "1. 【体能分级多变】：你可能是完全没有常识的运动小白(beginner)，也可能是懂一些器械的进阶会员(intermediate),或者说训练很多年的高阶会员（advanced）。\n"
            "2. 【带有真实身体伤病与不适】：你经常会口语化地主诉自己的关节拉伤或疼痛（如：深蹲完膝盖疼、脖子酸僵、手腕一撑地就疼得钻心），或者明确有椎间盘突出等旧伤史。\n"
            "3. 【诉求全面而长尾】：你不仅需要教练为你定点推荐符合器械边界的动作，还需要教练执行动作难度的降阶与替代编排，甚至还会追问训练后的营养补给（如窗口期补糖和蛋白质）和运动生理机制。\n"
            "请完全使用【中文口语、甚至带有烦恼和疑惑的语气】进行发问。"
        )
    )
]

async def bake_unified_ragas_official():
    print("🚀 [Ragas Official] 启动【分层按比例语义锚定抽样】全库抽干流水线...")
    
    # ====================================================================
    # 🎯 核心优化：【分层隔离舱抽样模型】，防止小样本实体（如伤病）被大样本（器械）稀释
    # ====================================================================
    
    # ── 1. 📥 MySQL 动作库抽样 (总量三十几个，我们高散度随机抽 15 个动作) ──
    sql_tool = SQLTool()
    rag_tool = RAGTool()
    graph_tool = GraphTool()
    all_mysql_rows = await sql_tool.get_all_exercises() # 读出你线程池里的生动作
    sampled_mysql = random.sample(all_mysql_rows, 50) if all_mysql_rows else []

    # ── 2. 📥 Neo4j 伤病防线抽样 (关节只有 7 个，为了防信息丢失，执行 100% 全量保留！) ──
    # 因为伤病是最高宪法红线的来源，样本量极小，绝对不能参与等比例缩减，必须全量强灌作为语义锚点！
    all_injury_edges_rows = await graph_tool.get_all_injury_edges() 
    all_progression_rows = await graph_tool.get_all_progression_regressions()

    sampled_graph_injuries = random.sample(all_injury_edges_rows, 60)
    sampled_graph_progression = random.sample(all_progression_rows, 60)
    
    # ── 3. 📥 Chroma 书籍文献抽样 (长文本 Chunk 往往有几百个，高散度随机抽 20 个) ──
    chroma_results = rag_tool.book_collection.get()
    
    all_chroma_docs = chroma_results.get("documents", [])
    all_chroma_metas = chroma_results.get("metadatas", [])

    all_book_documents: List[Document] = []

    langchain_documents: List[Document] = []
    
    # 物理打包对齐，清洗掉无效短 Chunk
    for doc, meta in zip(all_chroma_docs, all_chroma_metas):
        if doc and len(doc.strip()) > 50:
            all_book_documents.append(Document(page_content=doc, metadata=meta or {"source": "fitness_books"}))

    print("book document len: ", len(all_book_documents))
    langchain_documents.extend(random.sample(all_book_documents, min(len(all_book_documents), 60)))
            

    print(f"🎲 [Sampling 看板] 动作库随机抽样: {len(sampled_mysql)} 条 | 伤病防线全量保留: {len(sampled_graph_injuries)} 条 | 专业书籍随机抽样: 60 条")

    # 转换清洗后的 MySQL 动作
    for row in sampled_mysql:
        semantic_text = f"【健身动作百科名录】\n- 动作名称：{row.name_zh}。训练部位：{row.body_part_zh}。目标肌肉：{row.target_zh}。器材：{row.equipment_zh}。难度: {row.difficulty} 类别：{row.category_zh}"
        langchain_documents.append(Document(page_content=semantic_text, metadata={"source": "mysql_exercise_library"}))

    for row in sampled_graph_injuries:
        semantic_text = (
            f"【下肢运动生理学安全警戒红线】\n"
            f"{row['exercise_name']}对关节{row['joint_name']}有一定损伤\n"
            f"【硬核执教守则】：任何主诉 [{row['joint_name']}] 不适的新手，你必须在排课中强制剔除上述动作，保障绝对安全！"
        )
        langchain_documents.append(Document(page_content=semantic_text, metadata={"source": "neo4j_lower_loads"}))

    # 💡 转化新捞出的 Neo4j 臀/腿动作进退阶变阶矩阵
    for row in sampled_graph_progression:
        semantic_text = (
            f"【下肢臀腿体能科学动作变阶进退阶连续体】\n"
            f"- 当前目标肌肉: {row['muscle_name']}\n"
            f"- 高阶动作实体: '{row['higher_action']}' (难度: {row['high_level']})\n"
            f"- 低阶动作实体: '{row['lower_action']}' (难度: {row['low_level']})\n"
            f"【硬核执教守则】：若用户反馈高难度动作 '{row['higher_action']}' 太难，你必须根据『退阶于（{row['relation_type']}）』指纹，安全【降阶退阶】平替为 '{row['lower_action']}'。"
        )
        langchain_documents.append(Document(page_content=semantic_text, metadata={"source": "neo4j_lower_chain"}))

    logger.info(f"📊 [Ragas Official] 资产包拼装完毕。累计向官方引擎投喂高品质语义 Document [{len(langchain_documents)}] 个。")

    # ── 5. ⚙️ 绑定 aihubmix 代理与阿里云官方的千问 v4 向量双网线 ──
    generator_llm = LangchainLLMWrapper(ChatOpenAI(
        model="gpt-4o", openai_api_key=settings.OPENAI_API_KEY, openai_api_base=settings.OPENAI_BASE_URL, temperature=0.7
    ))
    critic_llm = LangchainLLMWrapper(ChatOpenAI(
        model="gpt-4o-mini", openai_api_key=settings.OPENAI_API_KEY, openai_api_base=settings.OPENAI_BASE_URL, temperature=0.0
    ))
    embeddings = LangchainEmbeddingsWrapper(DashScopeEmbeddings(
        model="text-embedding-v4", dashscope_api_key=settings.DASHSCOPE_API_KEY
    ))

    # 🧠 初始化 Ragas 官方 2.0+ 生成大脑
    generator = TestsetGenerator(
        llm=generator_llm,
        embedding_model=embeddings,
        persona_list=personas)
    generator.critic_llm = critic_llm

    logger.info(f"⚡ [Ragas Official] 正在拉起新版 2.0 知识图谱变换流水线，目标全自动生成 40 条考题试卷...")
    
    transforms = default_transforms(
        documents=langchain_documents, 
        llm=generator_llm, 
        embedding_model=embeddings
    )
    
    # 2. 依次将这些中间推演器的 Prompt 汉化
    for transform in transforms:
        if hasattr(transform, "adapt_prompts"):
            prompts = await transform.adapt_prompts("chinese", llm=generator_llm)
            transform.set_prompts(**prompts)

    generator.knowledge_graph_transforms = transforms

    print("🔧 正在对 Ragas 合成器题型进行中文适配...")
    single_hop = SingleHopSpecificQuerySynthesizer(llm=generator_llm)
    multi_hop_spec = MultiHopSpecificQuerySynthesizer(llm=generator_llm)
    multi_hop_abst = MultiHopAbstractQuerySynthesizer(llm=generator_llm)

    distribution = [
        (single_hop, 0.5),      
        (multi_hop_spec, 0.25),  
        (multi_hop_abst, 0.25)   
    ]

    for query, _ in distribution:
        prompts = await query.adapt_prompts("chinese", llm=generator_llm)
        query.set_prompts(**prompts)

    try:
        # 自发在内存中交叉缝合出 [50% Simple + 25% Reasoning + 25% Multi-Context] 黄金考卷！
        testset = generator.generate_with_langchain_docs(
            documents=langchain_documents,
            testset_size=40,
            query_distribution=distribution,
        )

        df = testset.to_evaluation_dataset().to_pandas()
        
        os.makedirs("tests/dataset", exist_ok=True)
        output_path = "tests/dataset/fitness_ground_truth_multi.json"
        df.to_json(output_path, orient='records', lines=True, force_ascii=False)

        print(f"🎉 🎉 [Ragas Official] 跨多源合流的 Ragas 2.0+ 原生黄金试卷固化大成功！题量: {len(df)} 条。")

    except Exception as e:
        print(f"❌ [Ragas Official] 运行时遭遇底层断裂: {e}")


if __name__ == "__main__":
    asyncio.run(bake_unified_ragas_official())