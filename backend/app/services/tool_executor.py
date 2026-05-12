# app/services/tool_executor.py

class ToolExecutor:
    def __init__(self):
        self.sql_tool = SQLTool()
        self.rag_tool = RAGTool()
        self.graph_tool = GraphTool()

    async def execute(self, tool_call):
        """
        根据 Agent 解析出的 tool_name 执行对应的工具
        """
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if name == "query_sql":
            return await self.sql_tool.search(args)
        elif name == "query_rag":
            return await self.rag_tool.search(args)
        elif name == "query_graph":
            return await self.graph_tool.reason(args)
        else:
            raise ValueError(f"Unknown tool: {name}")
