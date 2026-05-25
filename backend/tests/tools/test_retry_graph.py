# test_retry_graph.py
import asyncio
from unittest.mock import patch
from neo4j.exceptions import ServiceUnavailable
from app.agent.orchestrator import CoachOrchestrator
from app.models.schema import ToolTask, GraphReasoningSchema

async def simulate_neo4j_crash():
    orchestrator = CoachOrchestrator(client=None)
    
    task = ToolTask(
        task_id="task_graph_test",
        tool="graph_tool",
        graph_params=GraphReasoningSchema(scenario="injury_avoidance", joint_name="膝关节"),
        reason="测试图数据库断连"
    )
    
    # 💡 【核心黑科技】：强行让 Neo4j 驱动执行 Cypher 时抛出服务不可达
    with patch('neo4j.Session.run', side_effect=ServiceUnavailable("Neo4j 远程服务器集群端口断开")):
        print("🚩 [测试启动] 已成功注入『Neo4j 突发不可达故障』...")
        
        result = await orchestrator.dispatch_tool(task)
        
        print("\n🎉 [测试结束] 最终收拢的熔断数据资产快照:")
        print(result)

if __name__ == "__main__":
    asyncio.run(simulate_neo4j_crash())
