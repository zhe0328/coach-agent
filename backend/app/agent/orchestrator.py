import asyncio
import json
from typing import Any

import httpx
import mysql.connector
from chromadb.errors import ChromaError
from neo4j.exceptions import DriverError, Neo4jError, ServiceUnavailable
from openai import APIConnectionError, APIStatusError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .analyzer import PlanAnalyzer
from .graph.coach_graph import build_coach_graph
from .graph.state import CoachAgentState
from .memory.memory_consolidator import MemoryConsolidator
from .memory.memory_manager import WorkingMemoryManager
from .memory.memory_policy import should_consolidate
from .prompts.skill_guide import get_skill_by_node
from .roles.macroPlanner import MacroPlannerAgent
from .roles.smallPlanner import SmallPlannerAgent
from .roles.synthesizer import CoachSynthesizer
from .utils.logger import LogColor, logger
from ..models.fitness import ChatRecord, ChatSession, TrainingLog, AgentPlansLog
from ..models.schema import (
    CoachResponse,
    FullPlan,
    MacroPlanSchema,
    RAGSearchSchema,
    SQLSearchSchema,
    ToolCallIntent,
    ToolTask,
)
from ..queue.enqueue import (
    AfterTurnPayload,
    enqueue_after_turn,
    enqueue_agent_plans_log,
    enqueue_consolidation,
)
from ..tools.graph_tool import GraphTool
from ..tools.rag_tool import RAGTool
from ..tools.sql_tool import SQLTool


class CoachOrchestrator:
    def __init__(self, client):
        self.macroPlanner = MacroPlannerAgent(client)
        self.smallPlanner = SmallPlannerAgent(client)
        self.synthesizer = CoachSynthesizer(client, get_skill_by_node("synthesizer"))
        self.analyzer = PlanAnalyzer(client)
        self.sql_tool = SQLTool()
        self.rag_tool = RAGTool()
        self.graph_tool = GraphTool()
        self.client = client
        self.memory_manager = WorkingMemoryManager(
            max_history_turns=4,
            sql_tool=self.sql_tool,
            summarize_client=client,
        )
        self.memory_consolidator = MemoryConsolidator(
            self.graph_tool, self.sql_tool, client
        )
        self._graph = build_coach_graph(self)
        self._prep_graph = build_coach_graph(
            self, interrupt_before=["synthesizer"]
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(
            (
                mysql.connector.errors.OperationalError,
                mysql.connector.errors.InterfaceError,
                DriverError,
                ServiceUnavailable,
                ChromaError,
                httpx.TimeoutException,
                httpx.NetworkError,
            )
        ),
        reraise=False,
    )
    async def _execute_with_retry(self, task: ToolTask):
        """内部高解耦高吞吐重试原子核"""
        if task.tool == "sql_tool" and task.sql_params:
            return {
                "id": task.task_id,
                "type": "sql",
                "data": await self.sql_tool.search_exercise_base(task.sql_params),
            }

        if task.tool == "rag_tool" and task.rag_params:
            return {
                "id": task.task_id,
                "type": "rag",
                "data": await self.rag_tool.search_knowledge(task.rag_params),
            }

        if task.tool == "graph_tool" and task.graph_params:
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
            return {
                "id": task.task_id,
                "type": task.tool,
                "data": [],
                "error": str(type(e).__name__),
            }

    async def run_plan(self, plan: FullPlan):
        """
        大厂级亮点：基于有状态拓扑排序的【动态并发任务调度引擎】
        - 既保留了无依赖工具之间的 100% 并行优势
        - 又解决了局部工具之间必须串行、传递上下文的依赖难题
        """
        logger.info(
            f"{LogColor.TOOL}[Scheduler] 🪐 启动拓扑动态调度引擎...{LogColor.RESET}"
        )

        completed_data: dict[str, Any] = {}
        final_results: list[dict[str, Any]] = []

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
        await asyncio.gather(
            *[
                execute_task_with_dependencies(t, task_events)
                for t in plan.tasks
            ]
        )

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
        仅保留前 limit 条拦截记录，且每条最多保留 2 个安全平替动作。
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
                row_copy["safe_replacements"] = replacements[:2]
            trimmed.append(row_copy)

        return trimmed

    def _build_fallback_plans(self, user_input: str) -> tuple[MacroPlanSchema, FullPlan]:
        routing_reason = "远端 Planner 离线，启动本地硬编码全自重安全基础处方调度。"
        selected_tools = [
            ToolCallIntent(
                task_id="fallback_task_sql",
                tool_name="sql_tool",
                reason="离线容灾：筛选自重安全动作",
                focused_query=user_input,
                limit=10,
            ),
            ToolCallIntent(
                task_id="fallback_task_rag",
                tool_name="rag_tool",
                rag_intent="mixed",
                reason="离线容灾：本地 ChromaDB 语义检索",
                focused_query=user_input,
            ),
        ]
        macro_plan = MacroPlanSchema(
            routing_mode="standard",
            selected_tools=selected_tools,
            routing_reason=routing_reason,
        )
        full_plan = FullPlan(
            logic_chain=routing_reason,
            tasks=[
                ToolTask(
                    task_id="fallback_task_sql",
                    tool="sql_tool",
                    sql_params=SQLSearchSchema(equipment_zh="自重", limit=10),
                    depends_on=[],
                ),
                ToolTask(
                    task_id="fallback_task_rag",
                    tool="rag_tool",
                    rag_params=RAGSearchSchema(
                        query_text=user_input, top_k=2, intent="mixed"
                    ),
                    depends_on=[],
                ),
            ],
        )
        return macro_plan, full_plan

    def _build_executed_tasks_snapshot(
        self,
        macro_plan: MacroPlanSchema,
        full_plan: FullPlan,
        tool_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        raw_data_map = {r.get("id"): r for r in tool_results if r.get("id")}
        snapshot: list[dict[str, Any]] = []

        for intent in macro_plan.selected_tools:
            t_id = intent.task_id
            matched = raw_data_map.get(t_id, {})
            live_data = matched.get("data", [])

            if intent.tool_name == "sql_tool" and isinstance(live_data, list):
                live_data = live_data[: intent.limit]

            elif (
                intent.tool_name == "graph_tool"
                and self._get_graph_scenario(full_plan, t_id) == "injury_avoidance"
                and isinstance(live_data, list)
            ):
                live_data = self._trim_injury_avoidance_graph_data(
                    live_data, intent.limit
                )

            snapshot.append(
                {
                    "task_id": t_id,
                    "tool_name": intent.tool_name,
                    "reason": intent.reason,
                    "focused_query": intent.focused_query,
                    "data": live_data,
                }
            )

        return snapshot

    def _build_agent_plans_log(self, state: CoachAgentState) -> AgentPlansLog | None:
        macro_plan = state.get("macro_plan")
        full_plan = state.get("full_plan")
        if not macro_plan or not full_plan:
            return None

        memory = state["memory"]
        return AgentPlansLog(
            id=None,
            session_id=state["session_id"],
            user_query=state["user_input"],
            loop_retry_count=memory.current_loop_retry_count,
            macro_blueprint=macro_plan.selected_tools,
            native_full_plan=full_plan,
            executed_results=json.dumps(
                state.get("executed_tasks_snapshot", []),
                ensure_ascii=False,
                default=str,
            ),
            analyzer_final_reason=state.get("analyzer_feedback"),
        )

    def _schedule_agent_plan_log(self, state: CoachAgentState) -> None:
        agent_plans_log = self._build_agent_plans_log(state)
        if agent_plans_log is None:
            return
        memory = state["memory"]
        turn_id = memory.turn_count + 1
        enqueue_agent_plans_log(agent_plans_log, turn_id=turn_id)

    # ── LangGraph nodes ─────────────────────────────────────────────

    async def _node_load_context(self, state: CoachAgentState) -> dict:
        user_id = state["user_id"]
        session_id = state["session_id"]

        await self.sql_tool.create_or_ignore_session(
            ChatSession(session_id=session_id, user_id=user_id)
        )

        memory = await self.memory_manager.get_session_memory(session_id)
        memory.reset_loop_state()

        semantic_profile = await self.graph_tool.fetch_user_semantic_memory(user_id)
        if semantic_profile:
            logger.info(
                f"[Orchestrator] 🧬 语义记忆: injuries={semantic_profile[0].get('injuries')} "
                f"equipment={semantic_profile[0].get('equipment_list')}"
            )

        return {
            "memory": memory,
            "history_messages": self.memory_manager.compile_to_llm_messages(memory),
            "semantic_profile": semantic_profile or [],
            "loop_count": 0,
            "max_loops": 3,
            "planner_offline": False,
            "skip_analyzer": False,
            "is_complete": False,
            "tool_results": [],
            "executed_tasks_snapshot": [],
        }

    async def _node_macro_planner(self, state: CoachAgentState) -> dict:
        loop_count = state.get("loop_count", 0)
        logger.info(f"\n--- 🔄 [ReAct 第 {loop_count + 1} 轮] macro_planner ---")

        try:
            macro_plan = await self.macroPlanner.plan(
                state["user_input"],
                state["history_messages"],
                state["semantic_profile"],
                state["memory"],
            )
            return {
                "macro_plan": macro_plan,
                "planner_offline": False,
                "skip_analyzer": False,
                "routing_mode": macro_plan.routing_mode,
            }
        except (APIConnectionError, APIStatusError) as err:
            logger.error(
                f"{LogColor.PLAN}[Planner] 🚨 LLM 离线: {type(err).__name__} → fallback{LogColor.RESET}"
            )
            macro_plan, full_plan = self._build_fallback_plans(state["user_input"])
            return {
                "macro_plan": macro_plan,
                "full_plan": full_plan,
                "planner_offline": True,
                "skip_analyzer": True,
                "routing_mode": "fallback",
            }

    async def _node_small_planner(self, state: CoachAgentState) -> dict:
        macro_plan = state["macro_plan"]
        full_plan = await self.smallPlanner.assemble_full_plan(macro_plan)
        logger.info(
            f'{LogColor.PLAN}[Planner] FullPlan: {len(full_plan.tasks)} tasks — '
            f'"{full_plan.logic_chain}"{LogColor.RESET}'
        )
        return {"full_plan": full_plan}

    async def _node_tool_execute(self, state: CoachAgentState) -> dict:
        full_plan = state["full_plan"]
        macro_plan = state["macro_plan"]

        if not full_plan or not macro_plan:
            return {"tool_results": [], "executed_tasks_snapshot": []}

        tool_results = await self.run_plan(full_plan)
        executed_tasks_snapshot = self._build_executed_tasks_snapshot(
            macro_plan, full_plan, tool_results
        )
        return {
            "tool_results": tool_results,
            "executed_tasks_snapshot": executed_tasks_snapshot,
        }

    async def _node_analyzer(self, state: CoachAgentState) -> dict:
        is_complete, feedback = await self.analyzer.evaluate(
            state["user_input"], state.get("tool_results", [])
        )

        memory = state["memory"]
        loop_count = state.get("loop_count", 0)
        updates: dict[str, Any] = {
            "is_complete": is_complete,
            "analyzer_feedback": feedback,
        }

        if not is_complete:
            memory.latest_analyzer_feedback = feedback
            memory.current_loop_retry_count += 1
            await self.memory_manager.save_session_memory(
                state["session_id"], memory
            )
            updates["memory"] = memory
            updates["loop_count"] = loop_count + 1
            logger.warning(
                "[Orchestrator] 🚨 质检未通过，反馈已写入 Redis，重试 macro_planner"
            )
            self._schedule_agent_plan_log({**state, **updates})

        return updates

    async def _node_synthesizer(self, state: CoachAgentState) -> dict:
        macro_plan = state.get("macro_plan")
        if macro_plan is None:
            macro_plan = MacroPlanSchema(
                routing_mode="chat_only",
                selected_tools=[],
                routing_reason="无宏观计划，兜底闲聊",
            )

        logger.info(
            f"\n{LogColor.SYNTH}[Synthesizer] ✍️ 生成教练响应...{LogColor.RESET}"
        )

        try:
            coach_response = await self.synthesizer.generate_response(
                user_input=state["user_input"],
                macro_plan=macro_plan,
                executed_tasks=state.get("executed_tasks_snapshot") or [],
            )
        except Exception as e:
            logger.error(f"[Synthesizer] 合成失败: {e}")
            coach_response = (
                "🏋️‍♂️【本地离线智能教练提示】：当前网络较弱，系统已自动切换至本地无网纯自重防御模式。"
                "为您本地安全离线匹配到如下计划，请参考练习："
            )

        return {"coach_response": coach_response}

    async def _node_persist(self, state: CoachAgentState) -> dict:
        session_id = state["session_id"]
        user_id = state["user_id"]
        user_input = state["user_input"]
        memory = state["memory"]
        coach_response = state.get("coach_response")

        if isinstance(coach_response, CoachResponse):
            full_reply_text = coach_response.model_dump_json()
            memory.add_message(role="user", content=user_input)
            memory.add_message(role="assistant", content=full_reply_text)
            memory.turn_count += 1
            memory.reset_loop_state()
            pruned = await self.memory_manager.save_session_memory(
                session_id, memory, summarize=False
            )

            semantic_profile = state.get("semantic_profile")
            sniff = await self.memory_consolidator.sniff_delta(
                user_id=user_id,
                user_query=user_input,
                semantic_profile=semantic_profile,
            )
            run_consolidation = should_consolidate(memory, sniff=sniff)

            user_record = ChatRecord(
                session_id=session_id, role="user", content=user_input
            )
            coach_record = ChatRecord(
                session_id=session_id,
                role="assistant",
                content=full_reply_text,
            )
            training_log = TrainingLog(
                user_id=user_id,
                session_id=session_id,
                coach_reply_summary=coach_response.summary,
                generated_plan_json=coach_response.exercises or [],
                is_completed=0,
            )

            agent_plans_log = self._build_agent_plans_log(state)
            turn_range = f"turn_{memory.turn_count}" if pruned else None
            enqueue_after_turn(
                AfterTurnPayload(
                    session_id=session_id,
                    turn_id=memory.turn_count,
                    user_id=user_id,
                    user_record=user_record,
                    coach_record=coach_record,
                    training_log=training_log,
                    run_consolidation=run_consolidation,
                    user_query=user_input,
                    semantic_profile=semantic_profile,
                    sniff=sniff,
                    agent_plans_log=agent_plans_log,
                    pruned_messages=pruned or None,
                    turn_range=turn_range,
                )
            )

        return {"memory": memory}

    async def close_session(
        self,
        user_id: int,
        session_id: str,
    ) -> dict[str, Any]:
        """Finalize a session: optional warm summary already in Redis; force profile consolidation."""
        memory = await self.memory_manager.get_session_memory(session_id)
        memory.pending_consolidation = True

        last_user_query = ""
        for msg in reversed(memory.chat_history):
            if msg.role == "user":
                last_user_query = msg.content
                break

        semantic_profile = await self.graph_tool.fetch_user_semantic_memory(user_id)
        sniff = None
        if last_user_query:
            sniff = await self.memory_consolidator.sniff_delta(
                user_id=user_id,
                user_query=last_user_query,
                semantic_profile=semantic_profile,
            )

        await self.memory_manager.save_session_memory(session_id, memory, summarize=False)

        consolidation_scheduled = False
        if should_consolidate(memory, force=True, sniff=sniff):
            enqueue_consolidation(
                user_id=user_id,
                session_id=session_id,
                user_query=last_user_query or "session close",
                semantic_profile=semantic_profile,
                sniff=sniff,
            )
            consolidation_scheduled = True

        memory.pending_consolidation = False
        await self.memory_manager.save_session_memory(session_id, memory, summarize=False)

        return {
            "session_id": session_id,
            "turn_count": memory.turn_count,
            "session_summary_chars": len(memory.session_summary or ""),
            "consolidation_scheduled": consolidation_scheduled,
        }

    async def execute_stream(
        self,
        user_id: int,
        session_id: str,
        user_input: str,
    ):
        """Run planner/tools/analyzer, stream synthesizer tokens, then persist."""

        initial_state: CoachAgentState = {
            "user_id": user_id,
            "session_id": session_id,
            "user_input": user_input,
            "max_loops": 3,
        }

        prep_state = await self._prep_graph.ainvoke(initial_state)
        macro_plan = prep_state.get("macro_plan")
        if macro_plan is None:
            macro_plan = MacroPlanSchema(
                routing_mode="chat_only",
                selected_tools=[],
                routing_reason="无宏观计划，兜底闲聊",
            )

        executed_tasks = prep_state.get("executed_tasks_snapshot") or []
        guidance_parts: list[str] = []

        async for chunk in self.synthesizer.stream_guidance(
            user_input=user_input,
            macro_plan=macro_plan,
            executed_tasks=executed_tasks,
        ):
            guidance_parts.append(chunk)
            yield {"type": "chunk", "content": chunk}

        coach_response = self.synthesizer.build_response_from_guidance(
            guidance_text="".join(guidance_parts),
            macro_plan=macro_plan,
            executed_tasks=executed_tasks,
        )
        await self._node_persist({**prep_state, "coach_response": coach_response})
        yield {"type": "done", "data": coach_response.model_dump()}

    async def execute(
        self,
        user_id: int,
        session_id: str,
        user_input: str,
    ):
        logger.info(
            f"\n==================== 🤖 NEW COACH AGENT REQUEST ===================="
        )
        logger.info(f"用户输入: '{user_input}'")

        initial_state: CoachAgentState = {
            "user_id": user_id,
            "session_id": session_id,
            "user_input": user_input,
            "max_loops": 3,
        }

        final_state = await self._graph.ainvoke(initial_state)
        coach_response = final_state.get("coach_response")

        logger.info(
            f"{LogColor.SYNTH}[Synthesizer] ✨ 完成。{LogColor.RESET}\n"
            f"===================================================================\n"
        )
        print("coach response:", coach_response);
        return coach_response
