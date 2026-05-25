import os
import json
from deepeval.synthesizer import Synthesizer
from deepeval.synthesizer.config import StylingConfig
from deepeval.dataset.golden import Golden
from app.config import settings
from openai import OpenAI
import time
import random

random.seed(42)

# 1. 配置您的大模型环境
os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
os.environ["OPENAI_BASE_URL"] = settings.OPENAI_BASE_URL
os.environ["OPENAI_MODEL_NAME"] = "gpt-4o"

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL")
)

def forge_memory_context(user_input, expected_output):
    """根据问题和答案，反向伪造一段身体损伤或病史记忆"""
    prompt = f"""
    你是一个健身教练系统测试数据伪造专家。
    根据以下当前提问和理想回答，反向伪造一段该用户的【历史伤病或身体限制档案】（限40字以内）。
    
    用户当前提问："{user_input}"
    教练理想回答："{expected_output}"
    
    请直接输出伪造的中文记忆文本，不要包含任何标点符号包裹、Markdown或解释性文字。
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        return response.choices[0].message.parsed
    except Exception:
        return "用户曾在历史档案中登记过相关关节损伤风险。"

with open("tests/dataset/fitness_ground_truth_multi.json", "r", encoding="utf-8") as f:
    ragas_data = json.load(f)

# 3. 必须把 Ragas 的问题和 contexts 一起打包进 Golden 对象
seed_goldens = []
for item in ragas_data:
    seed_goldens.append(
        Golden(
            input=item["user_input"],
            # 这里的 contexts 就是你测试 RAG 时，从运动生理学书籍或动作说明里切片出来的纯文本列表
            context=item.get("reference_contexts", []) 
        )
    )

# 2. 用严谨的中文定义针对“多工具教练”的生成规则
# 我们在规则中显式要求大模型生成：用户提问、理想回答、预期调用的工具组合、所需的记忆上下文
coach_agent_styling = StylingConfig(
    task=(
        "生成用于评估虚拟智能健身教练（Coach Agent）的测试数据集。"
        "该 Agent 拥有三个工具：graph工具（解剖/损伤退阶关系）、SQL动作库（包含1300个动作）、生理学RAG工具（书籍理论）。"
        "同时，Agent 具备工作记忆和语义记忆，能记住用户的历史伤病。"
    ),
    scenario=(
        "用户向教练咨询运动方案、动作替换或伤病康复指导。"
        "场景必须涵盖以下六种类型：\n"
        "1. 纯动作检索与编排（仅需 SQL）\n"
        "2. 纯动作的具体执行步骤检索（仅需RAG，collection_name是exercise）"
        "3. 纯生理学百科检索（仅需 RAG，collection_name是book）\n"
        "4. 伤病逻辑推理（需要先查 SQL 找动作，再通过graph查询该动作是不是会加重关节负荷）\n"
        "5. 记忆联动（用户在历史对话中提过伤病，当前轮次需要结合历史记忆进行安全拦截）"
        "6. 前五项的联动发问"
    ),
    input_format=(
        "口语化的中文用户提问。如果是记忆联动场景，提问应隐晦（如：'今天练腿，给我排个动作'，而伤病信息写在历史记忆中）。"
    ),
    expected_output_format=(
        "一个 JSON 字符串，包含以下精确字段（不要包含任何 markdown 块或 ```json 标记）：\n"
        "{\n"
        "  \"user_input\": \"用户的中文提问\",\n"
        "  \"expected_output\": \"完美的教练中文标准回答，需包含动作名和生理学依据\",\n"
        "  \"expected_tools\": [\"graph工具\", \"SQL动作库工具\", \"生理学RAG工具\"] (根据场景选择放入工具名称),\n"
        "  \"memory_context\": \"此案例所依赖的历史记忆（如：用户上周提及右肩袖轻度拉伤），若无则留空\"\n"
        "}"
    )
)

# 3. 初始化合成器
synthesizer = Synthesizer(styling_config=coach_agent_styling)


# 4. 从零开始合成针对多工具逻辑的测试集
BATCH_SIZE = 5
all_synthetic_goldens = []

print(f"🚀 开始分批次演化数据，每批 {BATCH_SIZE} 条，总计 {len(seed_goldens)} 条种子数据...")

for i in range(0, len(seed_goldens), BATCH_SIZE):
    batch = seed_goldens[i:i + BATCH_SIZE]
    print(f"正在处理第 {i//BATCH_SIZE + 1} 批数据（范围: {i} 到 {i + len(batch)}）...")
    
    # 尝试执行，如果网络断开则捕获异常，确保程序不崩溃
    try:
        synthetic_goldens_batch = synthesizer.generate_goldens_from_goldens(
            goldens=batch,
            include_expected_output=True
        )
        all_synthetic_goldens.extend(synthetic_goldens_batch)
        print(f"✅ 第 {i//BATCH_SIZE + 1} 批演化成功！")
    except Exception as e:
        # 针对 RemoteProtocolError 或超时进行捕获
        print(f"❌ 第 {i//BATCH_SIZE + 1} 批发生网络断连或超时: {e}")
        print("⏳ 触发安全等待机制，休眠 5 秒后尝试跳过该批次，继续处理下一批...")
        time.sleep(5)
        continue # 跳过故障批次，确保后续数据能继续生成
        
    # 每批成功后强制歇 1-2 秒，防止高频触发 AIhubmix 转发商的每分钟频率限制（RPM）
    time.sleep(1.5)

# ========================================================
# 5. 后处理：将生成的定制 JSON 结构转化为标准化测试文件
# ========================================================

final_dataset = []

MEMORY_PROBABILITY = 0.35 

for g in all_synthetic_goldens:
    parsed_data = json.loads(g.expected_output)
    
    # 2. 从字典中精准提取你需要的各个中文字段
    user_input = parsed_data.get("user_input", g.input) # 如果没解析到，用外层的 input 保底
    expected_output = parsed_data.get("expected_output", "")
    expected_tools = parsed_data.get("expected_tools", [])

    final_dataset.append({
        "user_input": user_input,
        "expected_output": expected_output,
        "referenced_context": g.context,
        "expected_tools": expected_tools,
        "memory_context": ""
    })
# 6. 写入本地存储
output_path = "tests/dataset/coach_agent_advanced_goldens.json"
os.makedirs(os.path.dirname(output_path), exist_ok=True)

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(final_dataset, f, ensure_ascii=False, indent=2)

print(f"🎉 专属中文 Agent 数据集生成成功！已保存至: {output_path}")
