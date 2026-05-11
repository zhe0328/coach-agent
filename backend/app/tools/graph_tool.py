from app.database.neo4j_db import Neo4jManager
from app.models.schema import GraphReasoningSchema
import asyncio


class GraphTool:
    def __init__(self):
        self.db = Neo4jManager

    async def reason(self, params: GraphReasoningSchema):
        """
        基于 Neo4j 拓扑关系进行生理学逻辑推理
        """
        if params.scenario == "injury_avoidance":
            return await self._avoid_injury(params.joint_name)
        elif params.scenario == "regression":
            return await self._get_regression(params.exercise_id)
        elif params.scenario == "progression":
            return await self._get_progression(params.exercise_id)
        elif params.scenario == "synergy":
            return await self._get_synergistic_movements(params.exercise_id)
        elif params.scenario == "strengthen_joint":
            return await self._strengthen_joint(params.joint_name)

    async def _avoid_injury(self, joint_name: str):
        """场景 1: 避灾逻辑 —— 找到所有加载该关节的动作 ID"""
        cypher = """
        MATCH (e:Exercise)-[:LOADS]->(j:Joint {name: $joint_name})
        RETURN e.id as unsafe_exercise_id, e.name as name
        """
        with self.db.get_session() as session:
            result = session.run(cypher, joint_name=joint_name)
            return [record.data() for record in result]

    async def _get_regression(self, exercise_id: str):
        """场景 2: 退让逻辑 —— 动作太难了，找更简单的替代品"""
        cypher = """
        MATCH (e:Exercise {id: $ex_id})-[:REGRESSION_OF]->(easier:Exercise)
        RETURN easier.id as id, easier.name as name_zh
        """
        with self.db.get_session() as session:
            result = session.run(cypher, ex_id=exercise_id)
            return [record.data() for record in result]

    async def _get_progression(self, exercise_id: str):
        """场景 3: 进阶逻辑 —— 动作太简单，挑战更难的"""
        cypher = """
        MATCH (e:Exercise {id: $ex_id})-[:PROGRESSION_OF]->(harder:Exercise)
        RETURN harder.id as id, harder.name as name_zh
        """
        with self.db.get_session() as session:
            result = session.run(cypher, ex_id=exercise_id)
            return [record.data() for record in result]

    async def _get_synergistic_movements(self, exercise_id: str):
        """场景 4: 协同逻辑 —— 练完这个，建议下一个练什么（利用协同肌）"""
        cypher = """
        MATCH (e:Exercise {id: $ex_id})-[:SYNERGIST]->(m:Muscle)
        MATCH (next:Exercise)-[:TARGETS {intensity: 'primary'}]->(m)
        RETURN next.id as id, next.name as name_zh, m.name as shared_muscle
        LIMIT 3
        """
        with self.db.get_session() as session:
            result = session.run(cypher, ex_id=exercise_id)
            return [record.data() for record in result]


    async def _strengthen_joint(self, joint_name: str):
        """
        场景 5: 强化关节逻辑 —— 寻找能激活关节周围稳定肌群但直接负荷较小的动作
        """
        cypher = """
        MATCH (j:Joint {name: $joint_name})<-[:LOADS]-(e:Exercise)
        MATCH (e)-[:TARGETS|SYNERGIST]->(m:Muscle)
        WHERE e.difficulty = 'beginner'
        // 使用 COLLECT 函数按动作 ID 聚合肌肉名称
        RETURN e.id as id, 
            e.name as name_zh, 
            collect(m.name) as protective_muscles
        LIMIT 5
        """
        with self.db.get_session() as session:
            result = session.run(cypher, joint_name=joint_name)
            return [record.data() for record in result]

async def test():
    graph_tool = GraphTool()
    params = GraphReasoningSchema(exercise_id="0038", muscle_name="下腹部", joint_name="髋关节", scenario="strengthen_joint")
    result = await graph_tool.reason(params)
    print(result)

if __name__ == "__main__":
    asyncio.run(test())