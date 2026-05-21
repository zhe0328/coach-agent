from app.agent.utils.logger import logger, LogColor
from ...models.schema import (
    SQLSearchSchema,
    RAGSearchSchema,
    GraphReasoningSchema,
    FullPlan,
    ToolTask,
    ToolCallIntent,
    MacroPlanSchema,
)
from typing import List
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
        self, focused_query: str, reason: str
    ) -> SQLSearchSchema:
        """SQL 专项：极端严苛的‘非必要不填充’数据提取"""
        system_prompt = """
            你是一个冷酷、严谨的结构化数据提取器。

            【关键准则：非必要不填充】
            - 只有当用户显式提到了某个属性时，才填充对应的参数。
            - 严禁脑补用户没说的信息。如果用户没提部位，该字段必须保持 null（None）。
            - 严禁将用户提到的“部位”同时填入 name_zh 和 target_zh。

            【字段填充指南】
            - name_zh: 仅当用户提到具体的动作名称（如“交替触脚跟”、“空中蹬车”）时填写。不要把部位填在这里。
            - target_zh/body_part_zh: 只有用户明确说了“练哪里”才填。若填写了target_zh, 必须确保 body_part_zh 与其在人类解剖学上【绝对属于同一身体分区】
            - category_zh: 除非用户明确说“有氧”或“力量”，否则不填。

            【严格约束】
            - 必须使用中文填充参数。

            【执行范例】
            - 输入: "初学者弹力带练大腿" -> 输出: {{equipment_zh: "弹力带", body_part_zh: "大腿", difficulty: "beginner"}}
            - 输入: "锻炼前锯肌的有氧运动" -> 输出: {{targets_zh: "前锯肌", category_zh: "有氧运动"}}
        """

        user_prompt = f"""
            【上游宏观规划官的决策依据】：
            {reason}
            
            【针对本工具裁剪后的纯净提问切片】：
            "{focused_query}"
            
            请结合上游规划官的决策依据（它告诉你了为什么要查SQL），将用户的原始输入精炼为高价值的检索词，并判定意图：
        """
        try:
            print("focused query: ", focused_query)
            response = self.client.beta.chat.completions.parse(
                model=self.model,  # 涉及复杂规划，建议用强模型
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=SQLSearchSchema,
                temperature=0.0,
            )
            return response.choices[0].message.parsed
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
            print("focused query: ", focused_query)
            response = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=GraphReasoningSchema,
                temperature=0.0,
            )
            return response.choices[0].message.parsed
        except Exception as e:
            logger.error(f"[Extractor] Graph参数提取失败: {e}")
            raise e

    async def _extract_rag_params(
        self, focused_query: str, reason: str
    ) -> RAGSearchSchema:
        """RAG 专项：清洗高频体育实体，并执行意图路由三选一"""
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
            print("focused query: ", focused_query)
            response = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=RAGSearchSchema,
                temperature=0.0,
            )
            return response.choices[0].message.parsed
        except Exception as e:
            logger.error(f"[Extractor] RAG参数提取失败: {e}")
            raise e

    async def assemble_full_plan(
        self, macro_plan: MacroPlanSchema
    ) -> FullPlan:
        """
        核心装配大脑：将宏观意图与微观参数完美焊接，还原并吐出原生的 FullPlan 强类型契约
        """
        logger.info(
            f"{LogColor.TOOL}[SmallPlanner] 🛠️ 启动微观参数合成器，开始装配全量拓扑计划...{LogColor.RESET}"
        )

        # 【高级并发池】：专项专办，有针对性地开启异步小 Planner 提取任务
        all_activated_task_ids = {intent.task_id for intent in macro_plan.selected_tools}

        extract_tasks = {}
        for intent in macro_plan.selected_tools:
            t_id = intent.task_id
            t_reason = intent.reason
            t_focused_query = intent.focused_query
            
            if intent.tool_name == "sql_tool":
                extract_tasks[t_id] = self._extract_sql_params(
                    t_focused_query, t_reason
                )
            elif intent.tool_name == "graph_tool":
                extract_tasks[t_id] = self._extract_graph_params(
                    t_focused_query, t_reason
                )
            elif intent.tool_name == "rag_tool":
                extract_tasks[t_id] = self._extract_rag_params(
                    t_focused_query, t_reason
                )

        # 3. 秒级并发执行所有提取器（耗时仅由最慢的一个小任务决定）
        extracted_data = {}
        if extract_tasks:
            task_ids_keys = list(extract_tasks.keys())
            completed_param_objects = await asyncio.gather(*extract_tasks.values())
            extracted_data = dict(
                zip(
                    task_ids_keys,
                    completed_objects_or_instances := completed_param_objects,
                )
            )

        final_tasks: List[ToolTask] = []

        # 4. 遍历宏观蓝图，将选装工具完美拼装为原生的标准 ToolTask 列表
        for intent in macro_plan.selected_tools:
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
            if t_id in extracted_data:
                param_obj = extracted_data[t_id]
                if intent.tool_name == "sql_tool":
                    task_node.sql_params = param_obj

                elif intent.tool_name == "graph_tool":
                    task_node.graph_params = param_obj

                elif intent.tool_name == "rag_tool":
                    task_node.rag_params = param_obj

            final_tasks.append(task_node)

        # 5. 合体打包，完美回归原生 FullPlan 契约模型
        full_plan_output = FullPlan(
            tasks=final_tasks, logic_chain=f"[解耦拼装链] {macro_plan.routing_reason}"
        )

        logger.info(
            f"{LogColor.TOOL}[SmallPlanner] ✅ 拼装闭环大通车！成功组装出含有 {len(final_tasks)} 个任务的 FullPlan 实体。{LogColor.RESET}"
        )
        return full_plan_output
