from app.database.neo4j_db import Neo4jManager
from app.models.schema import GraphReasoningSchema
from typing import List, Dict, Any
import asyncio
import logging

logger = logging.getLogger("CoachAgent")


class GraphTool:
    def __init__(self):
        self.db = Neo4jManager

    async def reason(self, params: GraphReasoningSchema):
        """
        基于 Neo4j 拓扑关系进行生理学逻辑推理
        """
        if params.scenario == "injury_avoidance":
            return await self._avoid_injury(params.joint_name, params.candidate_ids)
        elif params.scenario == "regression":
            return await self._get_regression(params.exercise_name)
        elif params.scenario == "progression":
            return await self._get_progression(params.exercise_name)
        elif params.scenario == "synergy":
            return await self._get_synergistic_movements(params.exercise_name)
        elif params.scenario == "strengthen_joint":
            return await self._strengthen_joint(params.joint_name)

    async def _avoid_injury(
        self, joint_name: str, candidate_ids: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        场景 1: 避灾与自适应横移平替
        - 针对 SQL 并发出的 candidate_ids 进行定点拦截，斩断长上下文冗余。
        - 路径 A: 优先通过 REGRESSION_OF 寻找该动作更简单的退让动作。
        - 路径 B: 若动作已是初学者级别(退无可退)，自动横向匹配【相同主目标肌肉、同为 beginner、且不伤害该关节】的安全动作！
        """
        p_ids = candidate_ids if (candidate_ids and len(candidate_ids) > 0) else None

        cypher = """
        MATCH (e:Exercise)
        WHERE $candidate_ids IS NULL OR e.id IN $candidate_ids
        
        // 1. 精准拦截：在你的图结构中，动作节点存在直接给关节加压的 [LOADS] 关系
        MATCH (e)-[:LOADS]->(j:Joint {name: $joint_name})
        
        // 2. 【路径 A：纵向退让】顺着你的图关系：(困难 b)-[:REGRESSION_OF]->(简单 a)
        OPTIONAL MATCH (e)-[:REGRESSION_OF]->(easier:Exercise)
        WHERE NOT (easier)-[:LOADS]->(j)
        
        // 3. 【路径 B：横向平替】通过你的图结构寻找相同主目标肌肉节点
        OPTIONAL MATCH (e)-[:TARGETS {intensity: 'primary'}]->(m:Muscle)
        OPTIONAL MATCH (alt:Exercise)-[:TARGETS {intensity: 'primary'}]->(m)
        WHERE alt.difficulty = 'beginner' 
          AND alt.id <> e.id 
          AND NOT (alt)-[:LOADS]->(j)
        
        // 4. 双轨动态决策合流 (对齐你的实体属性 e.name)
        WITH e, 
             collect(distinct {id: easier.id, name_zh: easier.name}) AS reg_list,
             collect(distinct {id: alt.id, name_zh: alt.name}) AS alt_list
             
        WITH e, 
             CASE 
                WHEN size([x IN reg_list WHERE x.id IS NOT NULL]) > 0 
                THEN [x IN reg_list WHERE x.id IS NOT NULL]
                ELSE [x IN alt_list WHERE x.id IS NOT NULL]
             END AS final_replacements
             
        RETURN 
            e.id AS unsafe_exercise_id, 
            e.name AS unsafe_name,
            final_replacements AS safe_replacements
        """
        with self.db.get_session() as session:
            result = session.run(cypher, joint_name=joint_name, candidate_ids=p_ids)
            return [record.data() for record in result]

    async def _get_regression(self, exercise_name: str) -> List[Dict[str, Any]]:
        """
        场景 2: 退让逻辑 —— 动作太难了，找更简单的替代品
        - 解决冷启动：通过 CONTAINS 进行双向模糊子串匹配。
        - 解决断链死锁：如果当前动作已经是新手级（退无可退），横向寻找相同主肌肉的 beginner 自重平替。
        """
        cypher = """
            MATCH (current:Exercise)
            WHERE current.name CONTAINS $ex_name OR $ex_name CONTAINS current.name
            
            // 路径 A: 顺着你的物理建模：(当前)-[:REGRESSION_OF]->(更简单的)
            OPTIONAL MATCH (current)-[:REGRESSION_OF]->(easier:Exercise)
            
            // 路径 B: 横向寻找相同主目标肌肉的 beginner 替代
            OPTIONAL MATCH (current)-[:TARGETS {intensity: 'primary'}]->(m:Muscle)
            OPTIONAL MATCH (alt:Exercise)-[:TARGETS {intensity: 'primary'}]->(m)
            WHERE alt.difficulty = 'beginner' AND alt.id <> current.id
            
            WITH current,
                collect(distinct {id: easier.id, name_zh: easier.name, diff: easier.difficulty}) AS easier_list,
                collect(distinct {id: alt.id, name_zh: alt.name, diff: alt.difficulty}) AS alt_list
            
            WITH current,
                CASE 
                    WHEN size([x IN easier_list WHERE x.id IS NOT NULL]) > 0 
                    THEN [x IN easier_list WHERE x.id IS NOT NULL]
                    ELSE [x IN alt_list WHERE x.id IS NOT NULL]
                END AS final_candidates
                
            UNWIND final_candidates AS res
            // 关键修复点：增加 WITH 来承接变量，允许后续执行 WHERE 过滤
            WITH current, res
            WHERE res.id IS NOT NULL 
            AND (current.difficulty = 'advanced' OR res.diff = 'beginner' OR res.diff = current.difficulty)
            
            RETURN distinct res.id AS id, res.name_zh AS name_zh
            LIMIT 5
            """
        with self.db.get_session() as session:
            result = session.run(cypher, ex_name=exercise_name)
            return [record.data() for record in result]

    async def _get_progression(self, exercise_name: str) -> List[Dict[str, Any]]:
        """
        场景 3: 进阶逻辑 —— 动作太简单，挑战更难的
        - 顺着你的物理建模：(当前)-[:PROGRESSION_OF]->(更难的)
        - 进无可进时，横向抓取同肌群高级动作（advanced）进行刺激切换。
        """
        cypher = """
        MATCH (current:Exercise)
        WHERE current.name CONTAINS $ex_name OR $ex_name CONTAINS current.name
        
        // 路径 A: 顺着你的关系链：(当前)-[:PROGRESSION_OF]->(更难的)
        OPTIONAL MATCH (current)-[:PROGRESSION_OF]->(harder:Exercise)
        
        // 路径 B: 横向高阶平替
        OPTIONAL MATCH (current)-[:TARGETS {intensity: 'primary'}]->(m:Muscle)
        OPTIONAL MATCH (alt:Exercise)-[:TARGETS {intensity: 'primary'}]->(m)
        WHERE alt.difficulty = 'advanced' AND alt.id <> current.id
        
        WITH current,
             collect(distinct {id: harder.id, name_zh: harder.name, diff: harder.difficulty}) AS harder_list,
             collect(distinct {id: alt.id, name_zh: alt.name, diff: alt.difficulty}) AS alt_list
             
        WITH current,
             CASE 
                WHEN size([x IN harder_list WHERE x.id IS NOT NULL]) > 0 
                THEN [x IN harder_list WHERE x.id IS NOT NULL]
                ELSE [x IN alt_list WHERE x.id IS NOT NULL]
             END AS final_candidates
             
        UNWIND final_candidates AS res
        WITH current, res
        WHERE res.id IS NOT NULL 
          AND (current.difficulty = 'beginner' OR res.diff = 'advanced' OR res.diff = current.difficulty)
          
        RETURN distinct res.id AS id, res.name_zh AS name_zh
        LIMIT 5
        """
        with self.db.get_session() as session:
            result = session.run(cypher, ex_name=exercise_name)
            return [record.data() for record in result]

    async def _get_synergistic_movements(
        self, exercise_name: str
    ) -> List[Dict[str, Any]]:
        """
        场景 4: 协同运动编排
        - 机制：练完当前动作后，利用其副目标肌肉（SYNERGIST 关系），寻找以该肌肉为主训练目标（TARGETS primary）的其他安全动作。
        """
        cypher = """
        MATCH (current:Exercise)
        WHERE current.name CONTAINS $ex_name OR $ex_name CONTAINS current.name
        
        // 1. 顺着你定义的实体关系，找到副目标协同肌群 (SYNERGIST)
        MATCH (current)-[:SYNERGIST]->(m:Muscle)
        
        // 2. 跨节点匹配：寻找以该肌肉为主训练核心的其他候选动作
        MATCH (next:Exercise)-[:TARGETS {intensity: 'primary'}]->(m)
        
        // 3. 安全防线：排重，且协同动作绝对不能比当前主动作更难
        WHERE next.id <> current.id 
          AND (
            current.difficulty = 'advanced' 
            OR next.difficulty = current.difficulty 
            OR next.difficulty = 'beginner'
          )
        
        RETURN distinct
            next.id AS id, 
            next.name AS name_zh, 
            next.difficulty AS difficulty,
            m.name AS shared_muscle
        ORDER BY next.difficulty DESC
        LIMIT 5
        """
        with self.db.get_session() as session:
            result = session.run(cypher, ex_name=exercise_name)
            return [record.data() for record in result]

    async def _strengthen_joint(self, joint_name: str) -> List[Dict[str, Any]]:
        """
        场景 5: 康复强化关节
        - 核心逻辑调优：在你的同步逻辑中，肌肉通过 [:LOADS] 给关节施压。
        - 康复原则是：去激活能刺激到能覆盖该关节周围肌肉的动作，但【该动作绝对不能直接 LOADS 伤害关节】。
        """
        cypher = """
        MATCH (target_j:Joint {name: $joint_name})
        
        // 1. 反向顺着你的建立网络，找到哪些肌肉在跨越和保护这个关节
        MATCH (e_source:Exercise)-[:TARGETS|SYNERGIST]->(m:Muscle)
        MATCH (e_source)-[:LOADS]->(target_j)
        
        // 2. 重新收拢，寻找能锻炼到这些保护性肌肉，但【绝对不存在直接加压受损关节 LOADS 关系】的新手极其安全自重动作
        WITH distinct m, target_j
        MATCH (e:Exercise)-[:TARGETS|SYNERGIST]->(m)
        WHERE e.difficulty = 'beginner'
          AND NOT (e)-[:LOADS]->(target_j)
          
        RETURN 
            e.id AS id, 
            e.name AS name_zh, 
            collect(distinct m.name) AS protective_muscles
        LIMIT 5
        """
        with self.db.get_session() as session:
            result = session.run(cypher, joint_name=joint_name)
            return [record.data() for record in result]


async def test():
    graph_tool = GraphTool()
    params = GraphReasoningSchema(
        exercise_name="上斜飞鸟",
        muscle_name="下腹部",
        joint_name="踝关节",
        candidate_ids=["0030", "0032", "0042"],
        scenario="strengthen_joint",
    )
    result = await graph_tool.reason(params)
    print(result)


if __name__ == "__main__":
    asyncio.run(test())
