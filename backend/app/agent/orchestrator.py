import asyncio
from .roles.planner import PlannerAgent
from .roles.synthesizer import CoachSynthesizer
from .prompts.skill_guide import get_skill_by_node
from ..tools.sql_tool import SQLTool
from ..tools.rag_tool import RAGTool
from ..tools.graph_tool import GraphTool
from ..models.schema import ToolTask, FullPlan


class CoachOrchestrator:
    def __init__(self, client):
        self.planner = PlannerAgent(client, get_skill_by_node("planner"))
        self.synthesizer = CoachSynthesizer(client, get_skill_by_node("synthesizer"))
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
        并行执行计划中的所有任务
        JD 1 要求：提升并发能力与响应延迟优化
        """
        tasks = []
        for task in plan.tasks:
            # 将每个任务包装成一个协程
            tasks.append(self.dispatch_tool(task))

        # 并发运行所有工具请求
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 结果聚合与过滤 (去除异常)
        valid_results = [r for r in results if not isinstance(r, Exception)]
        return valid_results

    async def execute(self, user_input: str):
        # 1. 拿到精细化的执行蓝图
        full_plan = await self.planner.plan(user_input)

        tool_results = await self.run_plan(full_plan)

        # 4. 最终合成 (Synthesis)
        final_answer = await self.synthesizer.generate_response(
            user_input, tool_results, full_plan.logic_chain
        )
        return final_answer

    async def _generate_hyde(self, prompt: str):
        # 快速生成一个伪向量
        res = self.client.embeddings.create(
            input=prompt, model="text-embedding-3-small"
        )
        return res.data[0].embedding
