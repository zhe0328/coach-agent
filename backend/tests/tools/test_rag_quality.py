import os
import json
from re import S
import pytest
from ragas.metrics import ContextRecall, ContextPrecision
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.llms import LangchainLLMWrapper
from openai import AsyncOpenAI
from ragas.llms import llm_factory

from app.config import settings
from app.tools.rag_tool import RAGTool
from app.models.schema import KnowledgeChunk, RAGSearchSchema, ExerciseDetail

from typing import List, Union

def format_rag_output(rag_results: List[Union[ExerciseDetail, KnowledgeChunk]]) -> List[str]:
    """
    【数据解析器】：将结构化的复杂 Pydantic 实体资产，
    高效压榨、拼装成 Ragas 唯一认账的纯文本字符串列表（List[str]）
    """
    formatted_contexts = []
    
    for item in rag_results:
        # 获取类型判定标志（利用你的 data_type 字段）
        data_type = getattr(item, "data_type", None)
        
        if data_type == "exercise":
            # 💡 1. 抓取动作详情所需的所有中文特征字段
            # 注意：如果 ExerciseBase 里的字段在子类没有，可通过 getattr 安全获取
            name = getattr(item, "name_zh", "未知动作")
            body_part = getattr(item, "body_part_zh", "全身")
            target = getattr(item, "target_zh", "核心肌肉群")
            equipment = getattr(item, "equipment_zh", "徒手")
            description = getattr(item, "description_zh", "") or "暂无简介"
            
            # instructions_zh 是一个 List[str]，将其转换为带编号的文本步骤
            instructions = getattr(item, "instructions_zh", [])
            
            # 组装高密度语义实体段落
            text_block = (
                f"动作名称：{name}。训练部位：{body_part}。主目标肌群：{target}。"
                f"器材：{equipment}动作简介：{description}。执行步骤规范：{instructions}"
            )
            formatted_contexts.append(text_block)
            
        elif data_type == "knowledge":
            # 💡 2. 抓取生理学理论切片所需的三个核心字段
            source_book = getattr(item, "source_book", "专业文献")
            chapter_title = getattr(item, "chapter_title", "基础理论")
            content = getattr(item, "content", "")
            
            # 组装高密度理论教科书原文段落
            text_block = (f"【图书来源】: {source_book} | 【所属章节主题】: {chapter_title}\n"
                          f"【核心生理学与执教知识点】:\n{content}"
                        )
            formatted_contexts.append(text_block)
            
        else:
            # 🛡️ 兜底防御：如果是未知或者纯字典格式，转成普通字符串
            formatted_contexts.append(str(item))
            
    return formatted_contexts


@pytest.fixture(scope="module")
def evaluator_llm():
    """
    初始化充当裁判的大模型。
    使用 json_object 物理压制，防止 Ragas 指标在适配中文时因 Markdown 标签报错。
    """
    client = AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL
    )
    r_llm = llm_factory(
        model="gpt-4o", 
        client=client
    )
    
    return r_llm


@pytest.fixture(scope="module")
def fitness_ground_truth():
    """
    你的黄金测试数据集（可从本地 JSON 文件读取，这里用你生成的格式做演示）。
    测试 RAG Tool 单元时，我们只需要 user_input 和 reference_contexts。
    """
    file_path = "tests/dataset/fitness_ground_truth.json"
    
    if not os.path.exists(file_path):
        pytest.fail(f"❌ 未找到测试集文件，请确保路径正确: {file_path}")
        
    with open(file_path, mode="r", encoding="utf-8") as f:
        raw_data = json.load(f)
        
    cleaned_data = []
    for idx, item in enumerate(raw_data):
        user_input = item.get("user_input")
        
        ref_contexts = item.get("reference_contexts")

        intent = item.get("intent")

        reference = item.get("reference")
        
        # 边界自愈：如果拿出来的是单条字符串，强转为 Ragas 要求的 List[str]
        if isinstance(ref_contexts, str):
            ref_contexts = [ref_contexts]
            
        if not user_input or not ref_contexts:
            print(f"⚠️  警告: 样本 #{idx+1} 缺少 user_input 或 reference_contexts 核心字段，已跳过。")
            continue
            
        cleaned_data.append({
            "user_input": user_input,
            "reference_contexts": ref_contexts,
            "intent": intent,
            "reference": reference
        })
        
    print(f"📂 [数据加载成功] 已从本地成功注入 {len(cleaned_data)} 条黄金检索单元测试用例。")
    return cleaned_data



# ==========================================
# 🧪 2. 核心 Pytest 异步单元测试用例
# ==========================================

@pytest.mark.asyncio
async def test_rag_tool_retrieval_performance(fitness_ground_truth, evaluator_llm):
    """
    对 RAG Tool 纯检索召回能力的端到端单元测试
    """
    # 初始化你的真实 RAG 工具（请替换为你的真实代码）
    rag_tool = RAGTool() 
    
    # 初始化 Ragas 0.4.3 检索维度指标并适配中文
    metric_recall = ContextRecall(llm=evaluator_llm)
    metric_precision = ContextPrecision(llm=evaluator_llm)
    
    metrics = [metric_recall, metric_precision]
    
    # 🏃 物理触发你的 RAG Tool 进行批量检索
    samples = []
    for data in fitness_ground_truth:
        q = data["user_input"]
        intent = data["intent"]
        print("intent: ", intent)

        query = RAGSearchSchema(
            query_text = q,
            intent = intent
        )
        actual_contexts = await rag_tool.search_knowledge(query)
        formated_contexts = format_rag_output(actual_contexts)
        
        sample = SingleTurnSample(
            user_input=q,
            retrieved_contexts=formated_contexts,
            reference_contexts=data["reference_contexts"],
            reference=data["reference"]
        )
        samples.append(sample)

    eval_dataset = EvaluationDataset(samples=samples)
    
    # 🏁 触发 Ragas 裁判打分（保持不变）
    results = evaluate(
        dataset=eval_dataset,
        metrics=metrics,
        raise_exceptions=True
    )
    
    # ==========================================
    # 👁️ 【核心重构】：查看并打印每一个数据的明细评分
    # ==========================================
    # 1. 转换为 pandas DataFrame
    df_details = results.to_pandas()
    
    print("\n" + "="*50)
    print("📋 [RAG Tool 每条数据检索得分明细]：")
    print("="*50)
    
    # 2. 遍历每一行数据，打印独立得分
    for idx, row in df_details.iterrows():
        question = row.get("user_input")
        # 0.4.3 细分指标在 df 中的列名通常与指标类名的小写蛇形命名一致
        recall = row.get("context_recall", 0.0)
        precision = row.get("context_precision", 0.0)
        
        print(f"👉 样本 #{idx + 1}")
        print(f"   [问题]: {question}")
        print(f"   [召回率 Context Recall]: {recall:.2f}")
        print(f"   [精准度 Context Precision]: {precision:.2f}")
        print("-" * 50)
        
        # 💡 【可选的行级硬性门禁】：如果你希望任何一条数据不达标就立刻熔断报错：
        # assert recall >= 0.60, f"❌ 动作 '{question}' 检索严重漏检，得分仅 {recall:.2f}"

    # ==========================================
    # 🎯 3. 全局平均分断言（保持作为总门禁）
    # ==========================================
    score_recall = df_details["context_recall"].mean()
    score_precision = df_details["context_precision"].mean()

    print("avg score_recall", score_recall)
    print("avg score_precision", score_precision)

    # print(f"\n📈 [全局平均报告] -> 平均 Recall: {score_recall:.2f}, 平均 Precision: {score_precision:.2f}\n")

    df_details.to_csv("tests/rag_debug.csv", index=False)
    
    assert score_recall >= 0.80, f"❌ 整体平均召回率未达标 ({score_recall:.2f})！"
    assert score_precision >= 0.70, f"❌ 整体平均精准度未达标 ({score_precision:.2f})！"

