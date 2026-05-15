import asyncio
from .roles.planner import PlannerAgent
from .roles.synthesizer import CoachSynthesizer
from .analyzer import PlanAnalyzer
from .router import WorkflowRouter
from .prompts.skill_guide import get_skill_by_node
from .utils.logger import logger, LogColor
from ..tools.sql_tool import SQLTool
from ..tools.rag_tool import RAGTool
from ..tools.graph_tool import GraphTool
from ..models.schema import ToolTask, FullPlan


class CoachOrchestrator:
    def __init__(self, client):
        self.planner = PlannerAgent(client, get_skill_by_node("planner"))
        self.synthesizer = CoachSynthesizer(client, get_skill_by_node("synthesizer"))
        self.analyzer = PlanAnalyzer(client)
        self.router = WorkflowRouter()
        self.sql_tool = SQLTool()
        self.rag_tool = RAGTool()
        self.graph_tool = GraphTool()
        self.client = client

    async def dispatch_tool(self, task: ToolTask):
        """
        工具分发路由：根据不同的 Schema 动态调用
        """
        try:
            if task.tool == "sql_tool" and task.sql_params:
                print("sql_tool is called")
                return {
                    "type": "sql",
                    "data": await self.sql_tool.search_exercise_base(task.sql_params),
                }

            elif task.tool == "rag_tool" and task.rag_params:
                return {
                    "type": "rag",
                    "data": await self.rag_tool.search_knowledge(task.rag_params),
                }

            elif task.tool == "graph_tool" and task.graph_params:
                return {
                    "type": "graph",
                    "data": await self.graph_tool.reason(task.graph_params),
                }
        except Exception as e:
            # JD 1 要求：错误容灾机制
            print(f"Tool {task.tool} failed: {e}")
            return {"type": task.tool, "error": str(e)}

    async def run_plan(self, plan: FullPlan):
        """
        大厂级亮点：基于有状态拓扑排序的【动态并发任务调度引擎】
        - 既保留了无依赖工具之间的 100% 并行优势
        - 又解决了局部工具之间必须串行、传递上下文的依赖难题
        """
        logger.info(
            f"{LogColor.TOOL}[Scheduler] 🪐 启动拓扑动态调度引擎...{LogColor.RESET}"
        )

        # 1. 建立共享状态机与任务状态映射
        # tasks_pool = {t.task_id: t for t in plan.tasks}
        completed_data = {}  # 存储已完成任务的原始返回数据，用于上下文动态注入

        # 存储最终返回的大包结构
        final_results = []

        # 内部核心包装协程：负责等待依赖、动态注入强类型参数、执行、最后唤醒下游
        async def execute_task_with_dependencies(
            task: ToolTask, task_events: dict[str, asyncio.Event]
        ):
            # A. 等待所有前置依赖任务的 asyncio.Event 被 set() 唤醒
            if task.depends_on:
                logger.info(
                    f"{LogColor.TOOL}[Scheduler]   -> 任务 【{task.task_id}】 挂起，等待前置依赖: {task.depends_on}...{LogColor.RESET}"
                )
                await asyncio.gather(
                    *[task_events[dep_id].wait() for dep_id in task.depends_on]
                )

                # ==================== 【🔥 替换后的核心黑科技：强类型热注入】 ====================
                # 兼容大模型对 SQL 任务命名的变体（如 task_sql_base, task_sql_1），只要包含 sql 关键字就触发
                related_sql_ids = [
                    dep for dep in task.depends_on if "sql" in dep.lower()
                ]
                if task.tool == "graph_tool" and related_sql_ids:
                    # 1. 捞出最先完成的那个前置 SQL 任务沉淀在共享池里的数据
                    first_sql_id = related_sql_ids[0]
                    sql_res = completed_data.get(first_sql_id, [])

                    if isinstance(sql_res, list) and len(sql_res) > 0:
                        # 2. 健壮提取：不管 MySQL 查出来的是 Pydantic 对象还是字典，统一转化为纯字符串 ID 列表
                        c_ids = []
                        for item in sql_res:
                            if hasattr(item, "id"):  # 兼容 Pydantic 对象
                                c_ids.append(str(item.id))
                            elif (
                                isinstance(item, dict) and "id" in item
                            ):  # 兼容原始字典键
                                c_ids.append(str(item["id"]))

                        # 3. 强类型合规点语法赋值，彻底杜绝 TypeError
                        if task.graph_params and hasattr(
                            task.graph_params, "candidate_ids"
                        ):
                            task.graph_params.candidate_ids = (
                                c_ids  # 👈 修正为点语法赋值
                            )
                            logger.info(
                                f"{LogColor.TOOL}[Scheduler] 🎯 强类型依赖就绪！"
                                f"成功将 SQL 的 {len(c_ids)} 个候选 ID 热注入至 "
                                f"【{task.task_id}.graph_params.candidate_ids】{LogColor.RESET}"
                            )
                # ==============================================================================

            # C. 参数就绪，立即投入真正的执行路由
            logger.info(
                f"{LogColor.TOOL}[Scheduler] 🚀 调度启动执行: 【{task.task_id} ({task.tool})】{LogColor.RESET}"
            )
            res = await self.dispatch_tool(task)

            # D. 将数据沉淀到共享池中，供其他潜在的下游依赖任务读取
            if res and "data" in res:
                completed_data[task.task_id] = res["data"]
            final_results.append(res)

            # E. 执行完毕，立刻 set() 自己的事件，宣告自己完成，秒级唤醒所有下游任务
            task_events[task.task_id].set()

        # 3. 为所有任务初始化独一无二的同步事件信号（Event）
        task_events = {t.task_id: asyncio.Event() for t in plan.tasks}

        # 4. 全量轰炸：一并抛入 asyncio 运行时环境中，由底层事件循环自动进行拓扑分流
        worker_coroutines = [
            execute_task_with_dependencies(t, task_events) for t in plan.tasks
        ]
        await asyncio.gather(*worker_coroutines)

        logger.info(
            f"{LogColor.TOOL}[Scheduler] ✅ 全拓扑流式任务集触发闭环，并发调度圆满结束。{LogColor.RESET}"
        )
        return final_results

    async def execute(self, user_input: str):
        current_step = 0
        max_loops = 3  # 设置安全最大尝试次数（大厂通常设为 2-3 次，平衡效果与延迟）
        feedback = ""  # 初始反思为空
        tool_results = []
        last_logic_chain = ""

        while current_step < max_loops:
            logger.info(f"\n--- 🔄 [ReAct 迭代第 {current_step + 1} 轮开始] ---")
            # 1. 拿到精细化的执行蓝图
            logger.info(
                f"{LogColor.PLAN}[Planner] 🧠 正在构建任务蓝图... (是否有反思反馈: {bool(feedback)}){LogColor.RESET}"
            )
            full_plan = await self.planner.plan(user_input, feedback)
            last_logic_chain = full_plan.logic_chain
            logger.info(
                f'{LogColor.PLAN}[Planner] 思维链 (Logic Chain): "{last_logic_chain}"{LogColor.RESET}'
            )

            # 2. 并发调度当前周期的工具集
            step_results = await self.run_plan(full_plan)
            # 聚合多轮工具调用沉淀下的所有核心数据资产
            tool_results.extend(step_results)

            # 3. 质检引擎评估数据丰满度
            is_complete, feedback = await self.analyzer.evaluate(
                user_input, tool_results
            )

            # 4. 路由决策：是该修正重试，还是见好就收去走向最终合成？
            route_decision = self.router.should_stop(
                is_complete, current_step, max_loops
            )

            if route_decision == "synthesize":
                break

            current_step += 1

        # 5. 最终合成 (Synthesis) - 将通过反思洗白出来的完美数据喂给生成层
        logger.info(
            f"\n{LogColor.SYNTH}[Synthesizer] ✍️ 开始凝聚多源资产，正在生成最终的拟人化教练响应...{LogColor.RESET}"
        )
        final_answer = await self.synthesizer.generate_response(
            user_input, tool_results, last_logic_chain
        )
        logger.info(
            f"{LogColor.SYNTH}[Synthesizer] ✨ 最终响应合成完毕，成功推送至前端展示！{LogColor.RESET}"
        )
        return final_answer

    async def _generate_hyde(self, prompt: str):
        # 快速生成一个伪向量
        res = self.client.embeddings.create(
            input=prompt, model="text-embedding-3-small"
        )
        return res.data[0].embedding
