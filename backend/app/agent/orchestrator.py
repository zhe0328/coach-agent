import asyncio
from .roles.macroPlanner import MacroPlannerAgent
from .roles.smallPlanner import SmallPlannerAgent
from .roles.synthesizer import CoachSynthesizer
from .analyzer import PlanAnalyzer
from .router import WorkflowRouter
from .memory.memory_manager import WorkingMemoryManager
from .memory.memory_consolidator import MemoryConsolidator
from .prompts.skill_guide import get_skill_by_node
from .utils.logger import logger, LogColor
from ..tools.sql_tool import SQLTool
from ..tools.rag_tool import RAGTool
from ..tools.graph_tool import GraphTool
from ..models.schema import CoachResponse, ToolTask, FullPlan, SQLSearchSchema, RAGSearchSchema
from ..models.fitness import AgentPlansLog, ChatRecord, ChatSession, TrainingLog
import mysql.connector
import httpx
from neo4j.exceptions import DriverError, Neo4jError, ServiceUnavailable
from chromadb.errors import ChromaError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from openai import APIConnectionError, APIStatusError
from typing import Any
import json


class CoachOrchestrator:
    def __init__(self, client):
        self.macroPlanner = MacroPlannerAgent(client)
        self.smallPlanner = SmallPlannerAgent(client)
        self.synthesizer = CoachSynthesizer(client, get_skill_by_node("synthesizer"))
        self.analyzer = PlanAnalyzer(client)
        self.router = WorkflowRouter()
        self.sql_tool = SQLTool()
        self.rag_tool = RAGTool()
        self.graph_tool = GraphTool()
        self.client = client
        self.memory_manager = WorkingMemoryManager(
            max_history_turns=4, sql_tool=self.sql_tool
        )
        self.memory_consolidator = MemoryConsolidator(self.graph_tool, client)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        # 只有遇到网络连接异常、API 超时、或者数据库断连时才触发真正重试，业务逻辑错（如参数不对）不触发重试
        retry=retry_if_exception_type(
            (  # 1. MySQL 核心网络与连接抖动异常 (排除语法错误)
                mysql.connector.errors.OperationalError,
                mysql.connector.errors.InterfaceError,
                # 2. Neo4j 核心驱动崩溃、套接字失联、网络不可达异常
                DriverError,
                ServiceUnavailable,  # 导入自 neo4j.exceptions
                # 3. ChromaDB 底层 SQLite 本地文件锁死或 I/O 线程冲突
                ChromaError,
                # 4. 网络瞬时丢包或 HTTP 502/504 超时
                httpx.TimeoutException,
                httpx.NetworkError,
            )
        ),
        reraise=False,  # 重试 3 次依然失败后，不崩掉整个进程，而是向上跑进 except 容灾块
    )
    async def _execute_with_retry(self, task: ToolTask):
        """内部高解耦高吞吐重试原子核"""
        if task.tool == "sql_tool" and task.sql_params:
            return {
                "id": task.task_id,
                "type": "sql",
                "data": await self.sql_tool.search_exercise_base(task.sql_params),
            }

        elif task.tool == "rag_tool" and task.rag_params:
            return {
                "id": task.task_id,
                "type": "rag",
                "data": await self.rag_tool.search_knowledge(task.rag_params),
            }

        elif task.tool == "graph_tool" and task.graph_params:
            return {
                "id": task.task_id,
                "type": "graph",
                "data": await self.graph_tool.reason(task.graph_params),
            }
        return None

    async def dispatch_tool(self, task: ToolTask):
        """
        工具分发路由：根据不同的 Schema 动态调用
        """
        try:
            logger.info(
                f"{LogColor.TOOL}[ToolDispatcher] 发起高稳定性工具调度: 【{task.task_id} ({task.tool})】...{LogColor.RESET}"
            )

            # 1. 投流进入多维级联重试黑科技管道
            result = await self._execute_with_retry(task)

            if result is None:
                raise ValueError(f"未识别的工具类型或参数缺失: {task.tool}")
            return result
        except (mysql.connector.Error, Neo4jError, Exception) as e:
            # 💡【柔性熔断熔断舱（Graceful Degradation Airbag）】
            # 当经历 3 次重试仍旧因为网络故障崩溃，或者由于大模型参数幻觉引发硬报错（如 SQL 语法写错时）
            # 外部的 except 块会瞬间将其捕获。
            logger.error(
                f"{LogColor.TOOL}[ToolDispatcher] ❌ 严重预警：工具 【{task.task_id}】 经历 3 次指数重试后依旧崩溃！"
                f"参考异常: {e}。系统启动柔性退化防御，向状态机透传空资产...{LogColor.RESET}"
            )
            # 返回标准的空契约格式，防止下游 Pydantic 解析报错
            return {"type": task.tool, "data": [], "error": str(type(e).__name__)}

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

    def _get_graph_scenario(self, plan: FullPlan, task_id: str) -> str | None:
        for task in plan.tasks:
            if task.task_id == task_id and task.graph_params:
                return task.graph_params.scenario
        return None

    def _trim_injury_avoidance_graph_data(self, data: list[Any], limit: int) -> list[Any]:
        """
        injury_avoidance 会为每个高风险动作返回完整平替列表，极易撑爆 Synthesizer 上下文。
        仅保留前 limit 条拦截记录，且每条最多保留 1 个安全平替动作。
        """
        if not isinstance(data, list):
            return data

        trimmed: list[Any] = []
        for row in data[:limit]:
            if not isinstance(row, dict):
                trimmed.append(row)
                continue

            row_copy = dict(row)
            replacements = row_copy.get("safe_replacements")
            if isinstance(replacements, list):
                row_copy["safe_replacements"] = replacements[:1]
            trimmed.append(row_copy)

        return trimmed

    async def execute(self, user_id: int, session_id: str, user_input: str, background_tasks: Any = None):
        """
        全栈完全体：具备大脑级网络熔断自愈能力（Planner Fail-Safe）的终极编排引擎
        """
        logger.info(
            f"\n==================== 🤖 NEW COACH AGENT REQUEST ===================="
        )
        logger.info(f"用户输入 (User Input): '{user_input}'")

        chatSession = ChatSession(
            session_id=session_id, 
            user_id=user_id
        )
        await self.sql_tool.create_or_ignore_session(chatSession)

        current_step = 0
        max_loops = 3
        last_logic_chain = ""
        tool_results = []
        memory = await self.memory_manager.get_session_memory(session_id)
        print("current memory: ", memory)

        semantic_profile: list = await self.graph_tool.fetch_user_semantic_memory(user_id)
        if len(semantic_profile) != 0:
            logger.info(f"[Orchestrator] 🧬 长效语义记忆同步成功。当前关节限制: {semantic_profile[0]['injuries']} | 常用器械: {semantic_profile[0]['equipment_list']}")


        # Step 2: 将历史对话转化为标准的消息流背景，供后续大 Planner 理解上下文（比如理解“换一个”代词）
        history_messages = self.memory_manager.compile_to_llm_messages(memory)

        # 确保每一轮外网发问进入时，状态机计数清零
        memory.reset_loop_state()

        while memory.current_loop_retry_count < max_loops:
            logger.info(f"\n--- 🔄 [ReAct 迭代第 {current_step + 1} 轮开始] ---")

            try:
                # 正常路径：尝试连接远端 OpenAI 进行精细化意图规划
                logger.info(
                    f"{LogColor.PLAN}[Planner] 🧠 正在构建任务蓝图...){LogColor.RESET}"
                )

                macro_plan = await self.macroPlanner.plan(user_input, history_messages, semantic_profile, memory)

                if macro_plan.routing_mode == "chat_only" or not macro_plan.selected_tools:
                    print("macro_plan: ", macro_plan)
                    logger.info(
                        f"{LogColor.TOOL}[Orchestrator] 🍃 智能路由命中：【纯闲聊/社交寒暄】。开启零工具直驱通道...{LogColor.RESET}"
                    )

                    # 零数据直接送入 Synthesizer，并透传用户的原始提问
                    coach_response = await self.synthesizer.generate_response(
                        macro_plan=macro_plan,
                        executed_tasks=[],  # 👈 空资产无伤透传
                        user_input=user_input,
                    )

                    # 同样将这轮温馨的寒暄对话沉淀落盘进 Redis，维持多轮聊天连续性
                    full_reply_text = coach_response.model_dump_json()
                    memory.add_message(role="user", content=user_input)
                    memory.add_message(role="assistant", content=full_reply_text)
                    memory.reset_loop_state()
                    await self.memory_manager.save_session_memory(session_id, memory)

                    logger.info(f"[Orchestrator] ✅ 纯闲聊直驱交互圆满闭环，工作记忆已持久化。")
                    return coach_response

                full_plan = await self.smallPlanner.assemble_full_plan(macro_plan)

                last_logic_chain = full_plan.logic_chain
                logger.info(
                    f'{LogColor.PLAN}[Planner] 思维链 (Logic Chain): "{last_logic_chain}"{LogColor.RESET}'
                )
                logger.info(
                    f'{LogColor.PLAN}[Planner] 任务 (Full Plan): "{full_plan}"{LogColor.RESET}'
                )

            except (APIConnectionError, APIStatusError) as planner_err:
                logger.error(
                    f"{LogColor.PLAN}[Planner] 🚨 严重灾难预警：远端大模型机房失联！"
                    f"异常快照: {type(planner_err).__name__} -> {planner_err}。全栈启动『脊髓反射静态蓝图』容灾！{LogColor.RESET}"
                )

                last_logic_chain = (
                    "远端 Planner 离线，启动本地硬编码全自重安全基础处方调度。"
                )

                full_plan = FullPlan(
                    logic_chain=last_logic_chain,
                    tasks=[
                        # 任务一：SQL 基础粗筛任务（绝对放宽门槛，只搜最安全的自重动作）
                        ToolTask(
                            task_id="fallback_task_sql",
                            tool="sql_tool",
                            sql_params=SQLSearchSchema(equipment_zh="自重", limit=10),
                            depends_on=[],  # 无依赖，直接冲锋
                        ),
                        # 任务二：RAG 百科语义盲搜（直接拿着用户提问去搜本地 ChromaDB 缓存，本地计算 0 网络依赖！）
                        ToolTask(
                            task_id="fallback_task_rag",
                            tool="rag_tool",
                            rag_params=RAGSearchSchema(query_text=user_input, top_k=2),
                            depends_on=[],
                        ),
                    ],
                )
                # 既然大模型已经断网，强行终止后续的 ReAct 环路，本次请求以该静态蓝图直接一轮执行到底
                current_step = max_loops

            # 3. 并发调度当前周期的工具集（无论是大模型生成的，还是我们刚在 except 里面伪造出来的）
            step_results = await self.run_plan(full_plan)
            tool_results = step_results  # 状态多轮隔离清洗

            raw_data_map = {r.get("id"): r for r in tool_results}
            executed_tasks_snapshot = []

            for intent in macro_plan.selected_tools:
                t_id = intent.task_id

                # 从执行器的账单里，定点捞出这个任务跑出来的核心资产（data）和生参数（params）
                matched_raw_result = raw_data_map.get(t_id, {})
                live_data = matched_raw_result.get("data", [])

                if intent.tool_name == "sql_tool" and isinstance(live_data, list):
                    target_k = intent.limit
                    live_data = live_data[:target_k]

                elif (
                    intent.tool_name == "graph_tool"
                    and self._get_graph_scenario(full_plan, t_id) == "injury_avoidance"
                    and isinstance(live_data, list)
                ):
                    live_data = self._trim_injury_avoidance_graph_data(
                        live_data, intent.limit
                    )

                snapshot_node = {
                    "task_id": t_id,
                    "tool_name": intent.tool_name,  # 来自大蓝图
                    "reason": intent.reason,  # 来自大蓝图
                    "focused_query": intent.focused_query,  # 来自大蓝图
                    "data": live_data,  # 来自底层执行结算
                }
                executed_tasks_snapshot.append(snapshot_node)


            # 4. 如果是正常模型路径，继续启动质检引擎审查
            if type(planner_err if "planner_err" in locals() else None) not in [
                APIConnectionError,
                APIStatusError,
            ]:
                is_complete, feedback = await self.analyzer.evaluate(
                    user_input, tool_results
                )

                # agentPlansLog = AgentPlansLog(
                #     session_id=session_id,
                #     user_query=user_input,
                #     loop_retry_count=memory.current_loop_retry_count,
                #     macro_blueprint=macro_plan.selected_tools,
                #     native_full_plan=full_plan,
                #     executed_results=json.dumps(executed_tasks_snapshot, ensure_ascii=False),
                #     analyzer_final_reason=feedback
                # )
                if not is_complete:
                    # if background_tasks:
                    #     background_tasks.add_task(
                    #         self.sql_tool.log_agent_plan_decision,
                    #         agentPlansLog=agentPlansLog
                    #     )
                    memory.latest_analyzer_feedback = feedback
                    memory.current_loop_retry_count += 1
                    await self.memory_manager.save_session_memory(session_id, memory)
                    logger.warning(
                        f"[Orchestrator] 🚨 质检被打回！反思已写回 Redis，正在触发自愈重规划..."
                    )

                route_decision = self.router.should_stop(
                    is_complete, current_step, max_loops
                )
                if route_decision == "synthesize":
                    break
            else:
                # 脑死亡模式下不通过 Analyzer（因为 Analyzer 也需要连网大模型），直接跳出
                break

            current_step += 1

        # 5. 最终合成 (Synthesis)
        logger.info(
            f"\n{LogColor.SYNTH}[Synthesizer] ✍️ 凝聚资产，正在生成最终的教练响应...{LogColor.RESET}"
        )
        try:
            final_answer: CoachResponse = await self.synthesizer.generate_response(
                user_input, macro_plan, executed_tasks_snapshot
            )
            full_reply_text = final_answer.model_dump_json()
            memory.add_message(role="user", content=user_input)
            memory.add_message(role="assistant", content=full_reply_text)

            memory.reset_loop_state()
            await self.memory_manager.save_session_memory(session_id, memory)

            userRecord = ChatRecord(
                session_id=session_id,
                role="user",
                content=user_input,
            )
            coachRecord = ChatRecord(
                session_id=session_id,
                role="assistant",
                content=final_answer.detailed_guidance,
            )
            trainingLog = TrainingLog(
                user_id=user_id,
                session_id=session_id,
                coach_reply_summary=final_answer.summary,
                generated_plan_json=final_answer.exercises,
                is_completed=0
            )

            if background_tasks:
                background_tasks.add_task(
                    self.sql_tool.log_chat_transaction,
                    userChatRecord = userRecord,
                    coachChatRecord = coachRecord
                )
                background_tasks.add_task(
                    self.sql_tool.save_training_log,
                    trainingLog = trainingLog
                )

                # background_tasks.add_task(
                #     self.sql_tool.log_agent_plan_decision,
                #     agentPlansLog=agentPlansLog
                # )

                background_tasks.add_task(
                    self.memory_consolidator.consolidate_session_to_graph,
                    user_id=user_id,
                    user_query=user_input
                )
        except Exception as e:
            logger.error("[Synthesizer] 合成大模型断线，触发最终话术软着陆:", e)
            # 终极无网肉眼降级话术
            final_answer = "🏋️‍♂️【本地离线智能教练提示】：当前网络较弱，系统已自动切换至本地无网纯自重防御模式。为您本地安全离线匹配到如下计划，请参考练习："

        logger.info(
            f"{LogColor.SYNTH}[Synthesizer] ✨ 最终响应合成完毕，成功推送至前端展示！{LogColor.RESET}"
        )
        logger.info(
            f"===================================================================\n"
        )
        print("final_answer: ", final_answer)
        return final_answer

    async def _generate_hyde(self, prompt: str):
        # 快速生成一个伪向量
        res = self.client.embeddings.create(
            input=prompt, model="text-embedding-3-small"
        )
        return res.data[0].embedding
