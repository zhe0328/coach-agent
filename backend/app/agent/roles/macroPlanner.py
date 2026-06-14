from app.models.memory import WorkingMemory
from ...models.schema import MacroPlanSchema
from ..context.context_builder import PlannerContextBundle, compile_macro_messages
from ..intent.intent_state import IntentState
from ..utils.logger import LogColor, logger

MACRO_SYSTEM_PROMPT = """你是一个专业的健身训练调度员（Macro Planner）。你的唯一任务是审视用户的需求，从三个专业工具中选择最合适的组合，并定义它们的依赖拓扑关系。

            【微观单槽（Single Slot）多实例拆分铁律 —— 违反则下游全盘崩溃】：
            你的下游微观工具（SQL_tool、graph_tool）在参数设计上是【单内聚的】，它们每次【只支持且只允许】接收单个器械或单个关节名称！

            【复合多任务实例拆分铁律】：
            如果用户的输入包含多个不同的动作需求、多处伤病或多重理论疑问，你必须将它们拆解为【多个独立的工具实例】，每个实例赋予唯一的 `task_id`。
            - 例如：输入: "我想用哑铃练胸，还要用弹力带练背，但我肩膀痛。另外卧推和划船怎么排课？"
                -> 动作: 拆解并选装 4 个工具任务节点：
                1. {{ "task_id": "task_sql_chest", "tool_name": "sql_tool", "reason": "筛选哑铃练胸的抗阻动作" }}
                2. {{ "task_id": "task_sql_back", "tool_name": "sql_tool", "reason": "筛选弹力带练背的抗阻动作" }}
                3. {{ "task_id": "task_graph_shoulder", "tool_name": "graph_tool", "reason": "针对肩关节伤病执行运动风险规避与定点动作裁剪", "depends_on": ["task_sql_chest", "task_sql_back"] }}
                4. {{ "task_id": "task_rag_logic", "tool_name": "rag_tool", "rag_intent": "knowledge", "reason": "检索卧推和划船抗阻训练组合与排课的生理学干扰机制" }}
            
            【核心工具分发准则】
            1. SQL_tool (结构化筛选)：只要用户提到了目标肌肉、器材名称、难度等级、动作类别或身体部位时触发。
            2. graph_tool (生理逻辑推理)：涉及动作切换(太难/太易)、伤病规避(痛/受伤/关节不适/关节强化)、或寻找协同动作时触发。
            3. rag_tool (双库检索)：
            - 用户问具体动作“怎么做”、精细发力感 -> 设置 rag_intent="exercise"
            - 用户问动作先后顺序、组合、行不行、生理机制、疲劳原因、训练计划、饮食/营养方案、运动生理学 -> 设置 rag_intent="knowledge"
            - 用户描述模糊、需要综合理论与实操背景 -> 设置 rag_intent="mixed"
            - 【强制】每个 rag_tool 任务必须填写 rag_intent；下游 small planner 会直接沿用，不会二次判 intent。

            【任务依赖生成指南 (Topological Dependency Rules)】
            - 默认情况下，所有任务都是【并行的】，它们不互相依赖，`depends_on` 应保持为空数组 `[]`。
            - 【关键串行场景】：当且仅当发生“伤病规避”或“动作切换”需要调用 graph_tool，且同时需要针对用户匹配动作调用 sql_tool 时。
            - 在此场景下：
            1. 为 sql_tool 任务赋予固定的标识：`task_id: "task_sql_base"`
            2. 为 graph_tool 任务赋予标识：`task_id: "task_graph_injury"`
            3. 【强行约束】：必须将 graph_tool 的 `depends_on` 字段声明为 `["task_sql_base"]`。

            【组合策略】
            - 用户搜动作 + 问做法：SQL_tool + rag_tool。
            - 用户有伤病 + 搜动作：graph_tool + SQL_tool。
            - 用户觉得动作难 + 问原理：graph_tool + rag_tool。

            【严格约束】
            - 此时你只需决定触发哪个工具，不需要提取具体的动作细节参数。
            - 如果你分析出用户的提问没有提到任何与运动有关的信息，请绝对不要选装任何工具。将 routing_mode 锁死为 'chat_only'，并保持 selected_tools 为空数组 []。
            - 若 IntentState 显示 routing_hint=chat_only_candidate 且 fitness_score=0，【必须】输出 chat_only，不得选装工具。
            """


def _log_compiled_macro_prompt(
    messages: list[dict[str, str]],
    *,
    planner_context: PlannerContextBundle | None = None,
    source: str,
) -> None:
    """Log the exact messages[] sent to the macro planner LLM."""
    header = (
        f"{LogColor.PLAN}[MacroPlanner] Compiled prompt "
        f"({len(messages)} messages, {source}){LogColor.RESET}"
    )
    logger.info(header)

    if planner_context is not None:
        logger.info(
            f"{LogColor.PLAN}[MacroPlanner] Context segments: "
            f"{planner_context.explain()}{LogColor.RESET}"
        )
        logger.info(
            f"{LogColor.PLAN}[MacroPlanner] Token budget: "
            f"{planner_context.used_tokens}/{planner_context.budget_max_tokens}"
            f"{LogColor.RESET}"
        )

    for idx, message in enumerate(messages):
        role = message.get("role", "?")
        content = message.get("content") or ""
        if role == "system":
            preview = content[:160].replace("\n", "\\n")
            logger.info(
                f"{LogColor.PLAN}[MacroPlanner] msg[{idx}] role=system "
                f"len={len(content)} preview={preview!r}…{LogColor.RESET}"
            )
            continue

        logger.info(
            f"{LogColor.PLAN}[MacroPlanner] msg[{idx}] role={role} "
            f"len={len(content)}{LogColor.RESET}\n{content}"
        )


class MacroPlannerAgent:
    def __init__(self, client):
        self.client = client

    async def plan(
        self,
        user_input: str,
        history_context: list,
        semantic_profile: list[dict[str, any]],
        memory: WorkingMemory,
        intent_state: IntentState | None = None,
        planner_context: PlannerContextBundle | None = None,
    ) -> MacroPlanSchema:
        if planner_context is not None:
            messages = compile_macro_messages(planner_context, MACRO_SYSTEM_PROMPT)
            _log_compiled_macro_prompt(
                messages,
                planner_context=planner_context,
                source="context_builder",
            )
        else:
            from ..intent.intent_state import format_intent_block
            from ..memory.state_patch import format_state_patch_block

            semantic_constraints = ""
            if len(semantic_profile) != 0:
                profile = semantic_profile[0]
                semantic_constraints = (
                    f"【来自图数据库（Neo4j）的当前用户长效硬性指标与物理红线】:\n"
                    f"- 用户当前体能级别硬钢印: {profile.get('level', 'beginner')}\n"
                    f"- 用户当前【主诉受损/严禁过度负载】的身体关节: "
                    f"{', '.join(profile.get('injuries', [])) if profile.get('injuries') else '全身健康无受损'}\n"
                    f"- 用户家里目前【仅拥有且仅能调遣】的常备训练器械库: "
                    f"{', '.join(profile.get('equipment_list', [])) if profile.get('equipment_list') else '自重'}\n\n"
                )

            messages = [{"role": "system", "content": MACRO_SYSTEM_PROMPT}]
            if history_context:
                messages.extend(history_context)

            summary_block = ""
            if memory.session_summary.strip():
                summary_block = (
                    f"【本对话较早轮次摘要（warm memory）】:\n"
                    f"{memory.session_summary.strip()}\n\n"
                )

            user_content = (
                f"{semantic_constraints}"
                f"{format_state_patch_block(memory.state_patch)}"
                f"{format_intent_block(intent_state) if intent_state else ''}"
                f"{summary_block}"
                f"【当前用户的最新发问】：\n\"{user_input}\"\n"
            )

            if memory.latest_analyzer_feedback:
                user_content += (
                    f"【自愈复盘报告 —— 你在上一轮由于调度不当被质检官打回了！】\n"
                    f"- 质检官的反思修正指令: \"{memory.latest_analyzer_feedback}\"\n"
                )

            messages.append({"role": "user", "content": user_content})
            _log_compiled_macro_prompt(messages, source="legacy_fallback")

        response = self.client.beta.chat.completions.parse(
            model="gpt-4o",
            messages=messages,
            response_format=MacroPlanSchema,
        )
        return response.choices[0].message.parsed
