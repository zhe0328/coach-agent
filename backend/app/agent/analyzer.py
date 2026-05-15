# agent/analyzer.py
from .utils.logger import logger, LogColor
import json
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Tuple


class AnalysisResult(BaseModel):
    is_complete: bool = Field(
        ..., description="工具召回的数据是否已经足够完整、精准且安全地回答用户的问题"
    )
    reason: str = Field(..., description="对数据完备性、语义准确性及物理安全防线进行理性客观的简要诊断分析")
    feedback: str = Field(
        ...,
        description="如果未完成或数据发生严重语义/安全错配，请给出具体的、能够指导 Planner 修正方向的反思指令；若完全合格则为空字符串",
    )


class PlanAnalyzer:
    def __init__(self, client):
        self.client = client

    async def evaluate(
        self, user_input: str, tool_results: List[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        """
        全功能完全体质检引擎：具备三剑客（SQL+RAG+Graph）全活性感知与安全重排审查
        """
        logger.info(f"{LogColor.ANALYZER}[Analyzer] 🕵️‍♂️ 启动[SQL+RAG+Graph]全链路数据完备性与物理安全质检...{LogColor.RESET}")
        
        if not tool_results:
            return False, "【空数据拦截】：底层没有执行任何工具。请 Planner 至少启动一个核心工具进行数据检索。"

        # 1. 极速工程硬核检查与工具活性矩阵切分（Fast-Path）
        has_sql_tool_called = any(r.get("type") == "sql" for r in tool_results)
        has_rag_tool_called = any(r.get("type") == "rag" for r in tool_results)
        has_graph_tool_called = any(r.get("type") == "graph" for r in tool_results)
        
        has_sql_data = any(
            r.get("type") == "sql"
            and isinstance(r.get("data"), list)
            and len(r["data"]) > 0
            for r in tool_results
        )

        # 2. SQL 强行查空拦截规则
        if any(kw in user_input for kw in ["练", "推荐", "动作", "计划"]):
            if has_sql_tool_called and not has_sql_data:
                logger.warning(f"{LogColor.ANALYZER}[Analyzer] ❌ 规则拦截：基础动作资产全部查空！触发自愈回滚。{LogColor.RESET}")
                return (
                    False,
                    "【SQL拦截反馈】：未能从动作库中检索到任何基础动作资产。原因极可能是你的 SQL 筛选属性映射过严或产生了过滤冲突。请在下一轮【绝对放宽、精简或移除】过滤字段，改用纯模糊搜索！",
                )

        # 3. 智能化内容分析：分流摘要提取（Slow-Path）
        simplified_logs = []
        sql_extracted_names = []

        for r in tool_results:
            log_item = {"type": r.get("type")}
            raw_data = r.get("data")
            
            if r.get("type") == "sql" and raw_data:
                names = []
                if isinstance(raw_data, list):
                    for item in raw_data:
                        if hasattr(item, "name_zh"): names.append(str(item.name_zh))
                        elif isinstance(item, dict): names.append(str(item.get("name_zh", "未知")))
                log_item["extracted_names"] = names
                sql_extracted_names.extend(names)
                
            elif r.get("type") == "rag" and raw_data:
                if isinstance(raw_data, list):
                    rag_text = " || ".join([
                        f"RAG动作名:[{getattr(item, 'name_zh', '未知')}]-片段:{getattr(item, 'rag_content', str(item))[:150]}" 
                        for item in raw_data
                    ])
                else:
                    rag_text = str(raw_data)
                log_item["content_snippet"] = rag_text[:600] # 保持 600 字丰满上下文
                
            elif r.get("type") == "graph" and raw_data:
                # 💡【Graph 核心增强】：完美兼容你的避灾、平替、协同、关节强化四路图数据解构
                log_item["graph_inference_data"] = str(raw_data)[:400]
                
            else:
                log_item["content_snippet"] = str(raw_data or r.get("error", ""))[:150]
                
            simplified_logs.append(log_item)

        # 4. 💡【三维活性条件图剪枝】：动态拼接给质检员大模型的“审讯合规说明书”
        dynamic_instructions = []

        # 维度 A：RAG 交叉审讯
        if has_rag_tool_called and has_sql_data:
            dynamic_instructions.append(f"""- 【RAG 语义对齐检查】：当前同时触发了 SQL 与 RAG。请审查 SQL 正确想查的动作名集 {sql_extracted_names} 与 RAG 的『RAG动作名』或主题是否产生了严重的答非所问、张冠李戴的错配。若错配（如要深蹲却查出俯卧撑），必须判定 is_complete = false，并在 feedback 中写明：'【RAG语义错配反馈】：检测到 RAG 检索发生严重语义飘移。请 Planner 在下一轮大幅修正并精简 rag_tool 的 query_text 参数，去除语气词，只保留纯碎的“动作名+发力感技巧”关键词，以校正查找方向。'""")
        else:
            dynamic_instructions.append("- 【RAG 噪声豁免】：本轮未调用 RAG 工具，请【绝对禁止】对任何有关 RAG、知识错配、步骤缺失的问题进行审查或抛出反思。")

        # 维度 B：Graph 安全防线审查（大厂核心加分点）
        if any(kw in user_input for kw in ["痛", "伤", "保护", "难", "易", "换一个"]):
            if not has_graph_tool_called:
                # 漏调图数据库防线，属于严重失职，直接打回
                logger.warning(f"{LogColor.ANALYZER}[Analyzer] 🛡️ 安全拦截：用户主诉伤病/动作切换意图，但 Planner 漏调了 graph_tool！强制拦截。{LogColor.RESET}")
                return False, "【安全防御拦截反馈】：用户在输入中明确表达了关节疼痛、伤病保护或动作难度调整（太难/太易/换动作）的主观意图，但你【严重漏调了 graph_tool】！这在执教系统中会导致运动伤害风险。请在下一轮【必须】加入对 graph_tool 的调用，并正确配置其参数（如 joint_name 或 exercise_name、scenario）进行生理拓扑关系换算！"
            else:
                dynamic_instructions.append("- 【Graph 拓扑完备检查】：用户存在明显的伤病或动作切换诉求，且系统已触发 graph_tool。请仔细审查 `graph_inference_data` 字段中是否成功返回了‘不安全动作拦截’、‘降阶动作’、‘平替动作’或‘协同肌肉’。如果图数据库返回的数据完全为空或报错，导致安全防线未建立，请标记 is_complete = false，并给出微调图检索参数的指令。")
        else:
            if has_graph_tool_called:
                dynamic_instructions.append("- 【Graph 宽泛强化审查】：用户没有显式主诉痛病，但触发了图工具进行肌肉协同编排或关节拉伸强化。请审查图返回的数据大体上是否与用户强壮和训练目的匹配。")
            else:
                dynamic_instructions.append("- 【Graph 豁免】：用户无伤病诉求，且未调用 Graph，跳过图逻辑质检。")

        # 组合终极 Prompt
        formatted_instructions = "\n".join(dynamic_instructions)
        analyzer_prompt = f"""你是一名极其严谨、铁面无私、完全基于客观事实的 AI 健身教练系统【首席合规与安全审查专家】。
            用户的真实输入是: "{user_input}"
            当前多模态并发工具链收拢到的全量数据资产快照如下:
            {json.dumps(simplified_logs, ensure_ascii=False)}

            请你根据当下的【工具活性矩阵】，履行你的最高审查契约：
            
            {formatted_instructions}

            【知足常乐原则】：若数据已大体合格、且无上述死锁冲突，请果断判定为已完成（is_complete = true）。

            【步长扩容与数量审查准则】：
            1. 分析用户的输入，看用户是否指定了需要的动作数量（例如“推荐 4 个动作”、“来 5 个计划”）。
            2. 对比数据快照，如果发现 SQL 查出的动作数量或者经过 Graph 拦截后残存的安全动作数量【明显不足】以满足用户要求的数量，判定为未完成（is_complete = false）。
            3. 【强行要求】：你必须在 feedback 中写明：'【SQL步长不足反馈】：由于伤病拦截或筛选过严，当前残存的动作数量无法满足用户要求的个数。请 Planner 在下一轮迭代中，【必须将 sql_params 中的 limit 参数强行放大至 15 或 20】，以召回更多长尾候选动作供图数据库挑选平替！'

            你必须严格输出 JSON 结构，不要包含任何额外的 Markdown 解释。
            """

        try:
            response = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini", 
                messages=[{"role": "user", "content": analyzer_prompt}],
                response_format=AnalysisResult,
            )
            analysis: AnalysisResult = response.choices[0].message.parsed

            logger.info(f"{LogColor.ANALYZER}[Analyzer] 诊断结论: 是否完备={analysis.is_complete} | 原因: {analysis.reason}{LogColor.RESET}")
            if not analysis.is_complete:
                logger.info(f"{LogColor.ANALYZER}[Analyzer] 💡 产出反思指令: {analysis.feedback}{LogColor.RESET}")
            return analysis.is_complete, analysis.feedback
            
        except Exception as e:
            # ==================== 【🔥 大厂级亮点：自适应工具感知 Fallback 机制】 ====================
            logger.error(f"[Analyzer] 🚨 严重警报：质检大模型内核突发崩溃/断连！原因: {e}。启动自适应隔离...")
            
            # 1. 动态获取本轮真正执行过的工具活性状态，作为自适应分流的最强线索
            has_sql_tool_called = any(r.get("type") == "sql" for r in tool_results)
            has_rag_tool_called = any(r.get("type") == "rag" for r in tool_results)
            has_graph_tool_called = any(r.get("type") == "graph" for r in tool_results)

            # 2. 如果基础 SQL 动作资产完备，或者独立的 RAG/Graph 已经拿到了背景干货，直接通过
            if has_sql_data or (has_rag_tool_called and not has_sql_tool_called):
                logger.warning(f"{LogColor.ANALYZER}[Analyzer] 🛡️ [Fail-Safe] 检测到核心资产已召回，允许带伤放行走向合成层。{LogColor.RESET}")
                return True, ""
                
            # 3. 如果底层全面查空且内核崩溃（双空现象），启动精确分流反思自愈
            fallback_feedback = ""
            
            if has_graph_tool_called:
                # 场景 A：图工具崩了或查空时的保守指令
                fallback_feedback = (
                    "【Analyzer内核灾难恢复反馈】：质检内核离线且图生理逻辑数据异常。为了绝对防范运动伤害，"
                    "请 Planner 在下一轮迭代中，【最高优先级】重新检查并微调 graph_params 的 joint_name 或 scenario 字段，"
                    "确保降阶、退让、平替或关节强化逻辑在代码层能够顺利执行！"
                )
            elif has_rag_tool_called:
                # 场景 B：纯知识库百科检索查空时的保守指令
                fallback_feedback = (
                    "【Analyzer内核灾难恢复反馈】：质检内核离线且 RAG 知识百科召回为空。"
                    "请 Planner 在下一轮迭代中，【最高优先级】精简并重构 rag_tool 的 query_text 参数，"
                    "剔除所有主观语气长句子，仅保留高度浓缩的‘核心动作名+发力感’或‘肌肉群+呼吸方式’关键词，以校正向量查找方向！"
                )
            else:
                # 场景 C：传统的 SQL 条件筛选查空时的保守指令
                fallback_feedback = (
                    "【Analyzer内核灾难恢复反馈】：质检内核离线且 SQL 基础动作资产查空。"
                    "为了建立数据支柱，请 Planner 在下一轮迭代中，【最高优先级】完全解除所有关于器械、难度等主观脑补过滤条件，"
                    "强行放大 sql_params.limit 至 15，执行最大范围的基准动作库唤醒，确保响应有据可查！"
                )

            logger.warning(f"{LogColor.ANALYZER}[Analyzer] 🛡️ [Fail-Safe] 触发自适应条件裁剪！拒绝放行，强行将【{task.tool if 'task' in locals() else 'Current'}】反思指令灌回状态机！{LogColor.RESET}")
            return False, fallback_feedback

