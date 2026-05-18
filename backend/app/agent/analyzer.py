import json
from typing import List, Dict, Any, Tuple
from pydantic import BaseModel, Field
from app.agent.utils.logger import logger, LogColor


class AnalysisResult(BaseModel):
    is_complete: bool = Field(..., description="工具召回的数据是否已经足够完整、精准且安全地回答用户的问题")
    reason: str = Field(..., description="对数据完备性、语义准确性及物理安全防线进行理性客观的简要诊断分析")
    feedback: str = Field(..., description="如果未完成或数据发生严重语义/安全错配，请给出具体的、能够指导 Planner 修正方向的反思指令；若完全合格则为空字符串")


_ACTION_KEYWORDS = {"练", "推荐", "动作", "计划", "怎么练", "课表"}
_SAFETY_KEYWORDS = {"痛", "伤", "保护", "难", "易", "换一个", "软绵绵"}


class PlanAnalyzer:
    def __init__(self, client):
        self.client = client
        self.model = "gpt-4o-mini"

    def _get_type(self, r: Dict) -> str:
        return r.get("tool_name") or r.get("type", "")

    def _scan_tools(self, tool_results: List[Dict]) -> Dict[str, bool]:
        flags = {"sql": False, "rag": False, "graph": False, "sql_data": False}
        for r in tool_results:
            t = self._get_type(r)
            if t == "sql":
                flags["sql"] = True
                if isinstance(r.get("data"), list) and r["data"]:
                    flags["sql_data"] = True
            elif t == "rag":
                flags["rag"] = True
            elif t == "graph":
                flags["graph"] = True
        return flags

    def _format_rag(self, raw: Any) -> str:
        if not isinstance(raw, list):
            return str(raw)[:600]
        parts = []
        for item in raw:
            if getattr(item, "data_type", "exercise") == "knowledge":
                parts.append(f"文献来源:[{getattr(item, 'source_book', '未知')}]-核心内容:{getattr(item, 'content', '')[:150]}")
            else:
                parts.append(f"RAG动作名:[{getattr(item, 'name_zh', '未知')}]-要领:{getattr(item, 'description_zh', '')[:100]}")
        return " || ".join(parts)[:600]

    def _build_log_item(self, r: Dict, fallback_query: str) -> Dict:
        t = self._get_type(r)
        raw = r.get("data")
        entry = {
            "task_id": r.get("task_id", f"task_{t}"),
            "type": t,
            "focused_query": r.get("focused_query", fallback_query),
            "reason": r.get("reason", ""),
        }
        if t == "sql" and raw:
            names = []
            for obj in (raw if isinstance(raw, list) else []):
                if hasattr(obj, "name_zh"):
                    names.append(str(obj.name_zh))
                elif isinstance(obj, dict):
                    names.append(str(obj.get("name_zh", "未知")))
            entry["extracted_names"] = names
        elif t == "rag" and raw:
            entry["content_snippet"] = self._format_rag(raw)
        elif t == "graph" and raw:
            entry["graph_inference_data"] = str(raw)[:400]
        else:
            entry["content_snippet"] = str(raw or r.get("error", ""))[:150]
        return entry

    def _build_instructions(self, flags: Dict, has_safety_concern: bool) -> str:
        parts = []

        if flags["rag"]:
            parts.append(
                "- 【RAG审查】：对每个RAG任务，仅将其content_snippet与该任务自身的focused_query对比，禁止与SQL结果交叉审讯。"
                "例：SQL查出”卧推”，但某RAG任务的focused_query是”深蹲呼吸”且内容匹配深蹲，属于【合规】。"
                "发现脱靶时，标记 is_complete=false 并在 feedback 中注明 task_id。"
            )
        else:
            parts.append("- 【RAG 噪声豁免】：本轮未调用 RAG 工具，请【绝对禁止】对任何有关 RAG、知识错配、步骤缺失的问题进行审查或抛出反思。")

        if has_safety_concern:
            # flags["graph"] is guaranteed True here — the False case is caught before reaching this method
            parts.append(
                "- 【Graph 拓扑完备检查】：用户存在明显的伤病或动作切换诉求，且系统已触发 graph_tool。"
                "请仔细审查 `graph_inference_data` 字段中是否成功返回了'不安全动作拦截'、'降阶动作'、'平替动作'或'协同肌肉'。"
                "如果图数据库返回的数据完全为空或报错，导致安全防线未建立，请标记 is_complete = false，并给出微调图检索参数的指令。"
            )
        elif flags["graph"]:
            parts.append(
                "- 【Graph 宽泛强化审查】：用户没有显式主诉痛病，但触发了图工具进行肌肉协同编排或关节拉伸强化。"
                "请审查图返回的数据大体上是否与用户强壮和训练目的匹配。"
            )
        else:
            parts.append("- 【Graph 豁免】：用户无伤病诉求，且未调用 Graph，跳过图逻辑质检。")

        return "\n".join(parts)

    def _fallback_feedback(self, flags: Dict) -> str:
        if flags["graph"]:
            return (
                "【Analyzer内核灾难恢复反馈】：质检内核离线且图生理逻辑数据异常。为了绝对防范运动伤害，"
                "请 Planner 在下一轮迭代中，【最高优先级】重新检查并微调 graph_params 的 joint_name 或 scenario 字段，"
                "确保降阶、退让、平替或关节强化逻辑在代码层能够顺利执行！"
            )
        if flags["rag"]:
            return (
                "【Analyzer内核灾难恢复反馈】：质检内核离线且 RAG 知识百科召回为空。"
                "请 Planner 在下一轮迭代中，【最高优先级】精简并重构 rag_tool 的 focused_query 与 query_text 参数，"
                "剔除所有主观语气长句子，仅保留高度浓缩的'核心动作名+发力感'或'肌肉群+呼吸方式'关键词，以校正向量查找方向！"
            )
        return (
            "【Analyzer内核灾难恢复反馈】：质检内核离线且 SQL 基础动作资产查空。"
            "为了建立数据支柱，请 Planner 在下一轮迭代中，【最高优先级】完全解除所有关于器械、难度等主观脑补过滤条件，"
            "强行放大 sql_params.limit 至 15，执行最大范围的基准动作库唤醒，确保响应有据可查！"
        )

    async def evaluate(
        self, user_input: str, tool_results: List[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        logger.info(f"{LogColor.ANALYZER}[Analyzer] 🕵️‍♂️ 启动[SQL+RAG+Graph]全链路数据完备性与物理安全质检...{LogColor.RESET}")

        if not tool_results:
            return False, "【空数据拦截】：底层没有执行任何工具。请 Planner 至少启动一个核心工具进行数据检索。"

        flags = self._scan_tools(tool_results)
        is_action_query = any(kw in user_input for kw in _ACTION_KEYWORDS)
        has_safety_concern = any(kw in user_input for kw in _SAFETY_KEYWORDS)

        if is_action_query:
            for r in tool_results:
                if self._get_type(r) == "sql" and not r.get("data"):
                    task_id = r.get("task_id", "task_sql_base")
                    sql_params = r.get("params") or r.get("sql_params", {})
                    focused_query = r.get("focused_query", user_input)
                    logger.warning(f"{LogColor.ANALYZER}[Analyzer] ❌ 任务 [{task_id}] 查空！触发自愈回滚。{LogColor.RESET}")
                    return (
                        False,
                        f"【SQL拦截反馈】：大 Planner 请注意！你拆分出的任务节点 [{task_id}]（目标切片: '{focused_query}'）"
                        f"未能从动作库中检索到任何对应资产。原因极可能是你为该任务配置的微观筛选属性 {json.dumps(sql_params, ensure_ascii=False)} 过严或产生了冲突。"
                        f"请在下一轮循环中，为该 [{task_id}] 【绝对放宽、精简或完全移除】过滤字段，改用纯模糊搜索！"
                    )

        if has_safety_concern and not flags["graph"]:
            logger.warning(f"{LogColor.ANALYZER}[Analyzer] 🛡️ 安全拦截：用户主诉伤病/动作切换意图，但 Planner 漏调了 graph_tool！强制拦截。{LogColor.RESET}")
            return (
                False,
                "【安全防御拦截反馈】：用户在输入中明确表达了关节疼痛、伤病保护或动作难度调整的主观意图，但你【严重漏调了 graph_tool】！"
                "这在执教系统中会导致运动伤害风险。请在下一轮【必须】加入对 graph_tool 任务节点的调用，"
                "并配置其对应的子 reason、focused_query 进行生理拓扑安全换算！",
            )

        try:
            logs = [self._build_log_item(r, user_input) for r in tool_results]
            instructions = self._build_instructions(flags, has_safety_concern)

            prompt = (
                f'你是一名极其严谨、铁面无私、完全基于客观事实的 AI 健身教练系统【首席合规与安全审查专家】。\n'
                f'用户的真实输入是: "{user_input}"\n'
                f'当前多模态并发工具链收拢到的全量数据资产快照如下:\n'
                f'{json.dumps(logs, ensure_ascii=False)}\n\n'
                f'请你根据当下的【工具活性矩阵】，履行你的最高审查契约：\n\n'
                f'{instructions}\n\n'
                f'【知足常乐原则】：若数据已大体合格、且无上述死锁冲突，请果断判定为已完成（is_complete = true）。\n\n'
                f'【步长扩容与数量审查准则】：\n'
                f'1. 分析用户的输入，看用户是否指定了需要的动作数量（例如"推荐 4 个动作"、"来 5 个计划"）。\n'
                f'2. 对比数据快照，如果发现 SQL 查出的动作数量或者经过 Graph 拦截后残存的安全动作数量【明显不足】以满足用户要求的数量，判定为未完成（is_complete = false）。'
            )

            response = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format=AnalysisResult,
            )
            analysis: AnalysisResult = response.choices[0].message.parsed

            logger.info(f"{LogColor.ANALYZER}[Analyzer] 诊断结论: 是否完备={analysis.is_complete} | 原因: {analysis.reason}{LogColor.RESET}")
            if not analysis.is_complete:
                logger.info(f"{LogColor.ANALYZER}[Analyzer] 💡 产出反思指令: {analysis.feedback}{LogColor.RESET}")
            return analysis.is_complete, analysis.feedback

        except Exception as e:
            logger.error(f"[Analyzer] 🚨 质检内核崩溃: {e}，启动自适应隔离...")
            if flags["sql_data"] or (flags["rag"] and not flags["sql"]):
                logger.warning(f"{LogColor.ANALYZER}[Analyzer] 🛡️ [Fail-Safe] 核心资产已召回，允许带伤放行。{LogColor.RESET}")
                return True, ""
            logger.warning(f"{LogColor.ANALYZER}[Analyzer] 🛡️ [Fail-Safe] 强制回压反思指令。{LogColor.RESET}")
            return False, self._fallback_feedback(flags)
