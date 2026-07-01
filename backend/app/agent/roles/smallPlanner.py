from app.agent.utils.logger import logger, LogColor
from app.agent.roles.sql_param_sanitizer import SqlParamCatalog, sanitize_sql_search_params
from ...models.schema import (
    SQLSearchSchema,
    RAGSearchSchema,
    RAGQueryExtractSchema,
    GraphReasoningSchema,
    FullPlan,
    ToolTask,
    ToolCallIntent,
    MacroPlanSchema,
)
from typing import Any, List, Literal, Optional
import asyncio


class SmallPlannerAgent:
    """
    小 Planner (微观参数提取专家)
    职责：只在宏观调度决定启动某工具后，进行绝对严谨的字段抠字眼提取，拒绝冗余和脑补。
    """

    def __init__(self, client):
        self.client = client
        self.model = "gpt-4o-mini"  # 选用极速且便宜的模型

    async def _extract_sql_params(
        self,
        focused_query: str,
        reason: str,
        *,
        sql_param_catalog: SqlParamCatalog | None = None,
    ) -> SQLSearchSchema:
        """SQL 专项：极端严苛的‘非必要不填充’数据提取"""
        system_prompt = """
            你是一个冷酷、严谨的结构化数据提取器。

            【关键准则：非必要不填充】
            - 只有当用户显式提到了某个属性时，才填充对应的参数。
            - 严禁脑补用户没说的信息。如果用户没提部位，该字段必须保持 null（None）。
            - name_zh / body_part_zh / target_zh 三者语义不同，【禁止混填】。

            【字段语义（必须严格区分）】
            - name_zh: 【仅】具体动作名（如「反向卷腹」「波比跳」「罗马尼亚硬拉」）。
              禁止填：胸/背/腿/核心/胸肌/腹直肌/哑铃 等区域词、肌肉词、器材词。
            - body_part_zh: 【仅】从枚举中选一个大分区：背部/胸部/肩部/大腿/腰腹/上臂/前臂/小腿/颈部/心脏。
              用户说「练胸/练背/练核心/练腿」→ 只填 body_part_zh，不要填 target_zh。
            - target_zh: 【仅】更细的目标肌（如「腹直肌」「胸大肌」「背阔肌」），且用户明确点名该肌肉时才填。
              若已填 body_part_zh，通常应 leave target_zh 为空，避免 SQL AND 过窄查不到结果。

            【互斥规则】
            - 区域意图（练胸、练背、练核心）→ 只填 body_part_zh，target_zh=null，name_zh=null。
            - 具体动作名 → 只填 name_zh（可附带 equipment/difficulty），不要填 body_part/target。
            - 禁止 name_zh 与 body_part_zh / target_zh 填同一个词。

            【其他字段】
            - equipment_zh / difficulty / category_zh: 用户明确提到才填。

            【执行范例】
            - "初学者弹力带练大腿" -> {{equipment_zh: "弹力带", body_part_zh: "大腿", difficulty: "beginner"}}
            - "advanced 练核心" -> {{body_part_zh: "腰腹", difficulty: "advanced"}}
            - "前锯肌有氧" -> {{target_zh: "前锯肌", category_zh: "有氧运动"}}
            - "反向卷腹怎么做" -> {{name_zh: "反向卷腹"}}
            - 错误示范: name_zh="胸肌" ❌  应改为 body_part_zh="胸部"
        """

        user_prompt = f"""
            【上游宏观规划官的决策依据】：
            {reason}
            
            【针对本工具裁剪后的纯净提问切片】：
            "{focused_query}"
            
            请结合上游规划官的决策依据（它告诉你了为什么要查SQL），将用户的原始输入精炼为高价值的检索词，并判定意图：
        """
        try:
            logger.info(
                f"{LogColor.TOOL}[SmallPlanner][sql_tool] 提取输入 "
                f"focused_query={focused_query!r} reason={reason!r}{LogColor.RESET}"
            )
            response = self.client.beta.chat.completions.parse(
                model=self.model,  # 涉及复杂规划，建议用强模型
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=SQLSearchSchema,
                temperature=0.0,
            )
            parsed = response.choices[0].message.parsed
            sanitized = sanitize_sql_search_params(
                parsed,
                focused_query=focused_query,
                catalog=sql_param_catalog,
            )
            if sanitized.model_dump(exclude_none=True) != parsed.model_dump(
                exclude_none=True
            ):
                logger.info(
                    f"{LogColor.TOOL}[SmallPlanner][sql_tool] 参数校正 "
                    f"{parsed.model_dump(exclude_none=True)} -> "
                    f"{sanitized.model_dump(exclude_none=True)}{LogColor.RESET}"
                )
            logger.info(
                f"{LogColor.TOOL}[SmallPlanner][sql_tool] 提取结果 "
                f"{sanitized.model_dump(exclude_none=True)}{LogColor.RESET}"
            )
            return sanitized
        except Exception as e:
            logger.error(f"[Extractor] SQL参数提取失败: {e}")
            return SQLSearchSchema()  # 容灾：返回全 null 对象

    async def _extract_graph_params(
        self, focused_query: str, reason: str
    ) -> GraphReasoningSchema:
        """Graph 专项：专注于生理安全防线与动作进退阶映射"""
        system_prompt = """
            你是一个运动医学与生物力学图谱参数提取器。
            你的任务是识别用户提问中的关节加强、关节疼痛、伤病风险，或者动作进阶/退让（太难/太易/想换一个）的意图。

            【执行范例】
            - 输入: "深蹲腰痛怎么办" -> 输出: {{scenario: "injury_avoidance", joint_name: "脊柱"}}
            - 输入: "俯卧撑太难了" -> 输出: 调用 graph_tool {{scenario: "regression", exercise_name: "俯卧撑"}}
        """

        user_prompt = f"""
            【上游宏观规划官的决策依据】：
            {reason}
            
            【针对本工具裁剪后的纯净提问切片】：
            "{focused_query}"
            
            请结合上游规划官的决策依据（它告诉你了为什么要查graph），将用户的原始输入精炼为高价值的检索词，并判定意图：
        """
        try:
            logger.info(
                f"{LogColor.TOOL}[SmallPlanner][graph_tool] 提取输入 "
                f"focused_query={focused_query!r} reason={reason!r}{LogColor.RESET}"
            )
            response = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=GraphReasoningSchema,
                temperature=0.0,
            )
            parsed = response.choices[0].message.parsed
            logger.info(
                f"{LogColor.TOOL}[SmallPlanner][graph_tool] 提取结果 "
                f"{parsed.model_dump(exclude_none=True)}{LogColor.RESET}"
            )
            return parsed
        except Exception as e:
            logger.error(f"[Extractor] Graph参数提取失败: {e}")
            raise e

    async def _extract_rag_query_text(
        self, focused_query: str, reason: str
    ) -> RAGQueryExtractSchema:
        """Extract RAG query keywords only; intent is owned by macro planner."""
        system_prompt = """
            你是一个专业的运动科学RAG提取器。
            你的唯一职责是将口语化的提问精炼为纯粹的体育科学/动作关键词。
            不要判断 exercise/knowledge/mixed — 上游 macro planner 已决定检索意图。

            【执行范例】
            - 输入: "波比跳的执行步骤" -> 输出: {{ "query_text": "波比跳 步骤" }}
            - 输入: "先做高翻还是先做深蹲？感觉练完软绵绵的" -> 输出: {{ "query_text": "高翻 深蹲 动作顺序 中枢神经疲劳" }}
        """
        user_prompt = f"""
            【上游宏观规划官的决策依据】：
            {reason}

            【针对本工具裁剪后的纯净提问切片】：
            "{focused_query}"

            请精炼为高价值检索词：
        """
        response = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=RAGQueryExtractSchema,
            temperature=0.0,
        )
        return response.choices[0].message.parsed

    async def _extract_rag_params(
        self,
        focused_query: str,
        reason: str,
        rag_intent: Optional[Literal["exercise", "knowledge", "mixed"]] = None,
    ) -> RAGSearchSchema:
        """RAG 专项：macro rag_intent 为真源；仅缺失时才由 LLM 判定 intent。"""
        if rag_intent is not None:
            try:
                logger.info(
                    f"{LogColor.TOOL}[SmallPlanner][rag_tool] 使用 macro rag_intent="
                    f"{rag_intent!r} focused_query={focused_query!r}{LogColor.RESET}"
                )
                extracted = await self._extract_rag_query_text(focused_query, reason)
                parsed = RAGSearchSchema(
                    query_text=extracted.query_text,
                    top_k=extracted.top_k,
                    intent=rag_intent,
                )
                logger.info(
                    f"{LogColor.TOOL}[SmallPlanner][rag_tool] 提取结果 "
                    f"{parsed.model_dump(exclude_none=True)}{LogColor.RESET}"
                )
                return parsed
            except Exception as e:
                logger.error(
                    f"[Extractor] RAG query 提取失败，回退至完整提取: {e}"
                )

        system_prompt = """
            你是一个专业的运动科学RAG提取器。
            你的唯一职责是将口语化的提问精炼为纯粹的体育科学/动作关键词，并准确判断提问是偏向动作实操（exercise）还是生理机制逻辑（knowledge），还是两者都有（mixed）。

            【执行范例】
            - 输入: "波比跳的执行步骤" -> 输出: {{query_text: "波比跳 步骤", "intent": "exercise"}}
            - 输入: "先做高翻还是先做深蹲？感觉练完软绵绵的" -> 输出: {{ "query_text": "高翻 深蹲 动作顺序 中枢神经疲劳", "intent": "knowledge"}}
        """

        user_prompt = f"""
            【上游宏观规划官的决策依据】：
            {reason}
            
            【针对本工具裁剪后的纯净提问切片】：
            "{focused_query}"
            
            请结合上游规划官的决策依据（它告诉你了为什么要查RAG），将用户的原始输入精炼为高价值的检索词，并判定意图：
        """
        try:
            logger.info(
                f"{LogColor.TOOL}[SmallPlanner][rag_tool] 提取输入 "
                f"focused_query={focused_query!r} reason={reason!r}{LogColor.RESET}"
            )
            response = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=RAGSearchSchema,
                temperature=0.0,
            )
            parsed = response.choices[0].message.parsed
            logger.info(
                f"{LogColor.TOOL}[SmallPlanner][rag_tool] 提取结果 "
                f"{parsed.model_dump(exclude_none=True)}{LogColor.RESET}"
            )
            return parsed
        except Exception as e:
            logger.error(f"[Extractor] RAG参数提取失败: {e}")
            raise e

    async def assemble_full_plan(
        self,
        macro_plan: MacroPlanSchema,
        *,
        sql_param_catalog: SqlParamCatalog | None = None,
    ) -> FullPlan:
        """
        核心装配大脑：将宏观意图与微观参数完美焊接，还原并吐出原生的 FullPlan 强类型契约
        """
        logger.info(
            f"{LogColor.TOOL}[SmallPlanner] 🛠️ 启动微观参数合成器，开始装配全量拓扑计划...{LogColor.RESET}"
        )

        # 【高级并发池】：按 selected_tools 下标提取，避免重复 task_id 覆盖参数
        all_activated_task_ids = {intent.task_id for intent in macro_plan.selected_tools}

        extract_coros: list[Any | None] = [None] * len(macro_plan.selected_tools)
        for idx, intent in enumerate(macro_plan.selected_tools):
            t_id = intent.task_id
            t_reason = intent.reason
            t_focused_query = intent.focused_query

            logger.info(
                f"{LogColor.TOOL}[SmallPlanner] 📋 宏观任务 [{t_id}] tool={intent.tool_name} "
                f"depends_on={intent.depends_on} focused_query={t_focused_query!r} "
                f"reason={t_reason!r}{LogColor.RESET}"
            )

            if intent.tool_name == "sql_tool":
                extract_coros[idx] = self._extract_sql_params(
                    t_focused_query,
                    t_reason,
                    sql_param_catalog=sql_param_catalog,
                )
            elif intent.tool_name == "graph_tool":
                extract_coros[idx] = self._extract_graph_params(
                    t_focused_query, t_reason
                )
            elif intent.tool_name == "rag_tool":
                extract_coros[idx] = self._extract_rag_params(
                    t_focused_query, t_reason, intent.rag_intent
                )

        extracted_data: dict[int, Any] = {}
        extract_indices = [i for i, coro in enumerate(extract_coros) if coro is not None]
        if extract_indices:
            completed_param_objects = await asyncio.gather(
                *[extract_coros[i] for i in extract_indices]
            )
            extracted_data = dict(zip(extract_indices, completed_param_objects))

        final_tasks: List[ToolTask] = []

        # 4. 遍历宏观蓝图，将选装工具完美拼装为原生的标准 ToolTask 列表
        for idx, intent in enumerate(macro_plan.selected_tools):
            t_id = intent.task_id

            valid_dependencies = []
            if intent.depends_on:
                for dep_id in intent.depends_on:
                    # 检查大指挥官声明的依赖任务，在本轮是否【真的存在】于执行队列里
                    if dep_id in all_activated_task_ids:
                        valid_dependencies.append(dep_id)
                    else:
                        # 🛡️ 发现悬空孤儿依赖！果断在进程内将其物理抹除，将其降级、解锁为【独立并行/单发任务】！
                        logger.warning(
                            f"{LogColor.TOOL}[SmallPlanner] ⚠️ 发现拓扑悬空死锁！任务 [{t_id}] 声明依赖了 [{dep_id}]，"
                            f"但该前置任务在本轮未被启动。系统已自动执行【拓扑剪枝】，强行恢复该任务独立运行！{LogColor.RESET}"
                        )

            # 初始化一个干净的标准 ToolTask
            task_node = ToolTask(
                task_id=intent.task_id,
                tool=intent.tool_name,
                reason=intent.reason,
                depends_on=valid_dependencies
            )

            # 根据工具类型，将小 Planner 刚刚并发榨取出来的干净参数，定点“焊入”对应字段
            if idx in extracted_data:
                param_obj = extracted_data[idx]
                if intent.tool_name == "sql_tool":
                    task_node.sql_params = param_obj

                elif intent.tool_name == "graph_tool":
                    task_node.graph_params = param_obj

                elif intent.tool_name == "rag_tool":
                    task_node.rag_params = param_obj

            task_params = (
                task_node.sql_params
                or task_node.graph_params
                or task_node.rag_params
            )
            logger.info(
                f"{LogColor.TOOL}[SmallPlanner] 📦 装配完成 [{task_node.task_id}] "
                f"tool={task_node.tool} depends_on={task_node.depends_on} "
                f"params={task_params.model_dump(exclude_none=True) if task_params else None}"
                f"{LogColor.RESET}"
            )

            final_tasks.append(task_node)

        # 5. 合体打包，完美回归原生 FullPlan 契约模型
        full_plan_output = FullPlan(
            tasks=final_tasks, logic_chain=f"[解耦拼装链] {macro_plan.routing_reason}"
        )

        logger.info(
            f"{LogColor.TOOL}[SmallPlanner] ✅ 拼装闭环大通车！成功组装出含有 {len(final_tasks)} 个任务的 FullPlan 实体。{LogColor.RESET}"
        )
        return full_plan_output
