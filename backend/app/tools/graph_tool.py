from app.database.async_db import run_in_thread
from app.database.neo4j_db import Neo4jManager
from app.models.schema import GraphReasoningSchema
from app.agent.utils.logger import logger, LogColor
from typing import List, Dict, Any
import asyncio


class GraphTool:
    def __init__(self):
        self.db = Neo4jManager()

    async def _run_session(self, fn):
        def _sync():
            with self.db.get_session() as session:
                return fn(session)

        return await run_in_thread(_sync)

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
        return []

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
        def _query(session):
            result = session.run(cypher, joint_name=joint_name, candidate_ids=p_ids)
            return [record.data() for record in result]

        return await self._run_session(_query)

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
        def _query(session):
            result = session.run(cypher, ex_name=exercise_name)
            return [record.data() for record in result]

        return await self._run_session(_query)

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
        def _query(session):
            result = session.run(cypher, ex_name=exercise_name)
            return [record.data() for record in result]

        return await self._run_session(_query)

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
        def _query(session):
            result = session.run(cypher, ex_name=exercise_name)
            return [record.data() for record in result]

        return await self._run_session(_query)

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
        def _query(session):
            result = session.run(cypher, joint_name=joint_name)
            return [record.data() for record in result]

        return await self._run_session(_query)

    async def init_user_semantic_memory(self, user_id: int, name: str, level: str, injuries: list, equipments: list):
        """
        【完全体：高可用防死锁异步版】
        通过将伤病、器械物理切分为两条独立的 Cypher 语句，彻底粉碎 UNWIND 空数组蒸发漏洞与死锁风险！
        """
        logger.info(f"{LogColor.TOOL}[GraphTool] ✒️ 正在执行防死锁用户语义记忆刻录, User: {name}{LogColor.RESET}")

        # 🚀 核心优化 A：将 user_id 转换为字符串，对齐 Neo4j 拓扑索引
        str_user_id = str(user_id)

        # 🚀 核心优化 B：拆分为独立语句 1 ── 专攻基础画像与伤病红线
        # 使用 DETACH DELETE 显式安全斩断
        cypher_injuries = """
            MERGE (u:User {user_id: $user_id})
            SET u.name = $name, u.level = $level
            
            WITH u
            OPTIONAL MATCH (u)-[r1:HAS_INJURY]->()
            DELETE r1
            
            WITH u
            // 🛡️ 终极护栏：只有当数组不为空时，才执行解包和建立红线，完美破解蒸发漏洞！
            WHERE size($injuries) > 0
            UNWIND $injuries AS injury_joint
            MATCH (j:Joint {name: injury_joint})
            MERGE (u)-[:HAS_INJURY {created_at: timestamp()}]->(j)
        """

        # 🚀 核心优化 C：拆分为独立语句 2 ── 专攻常用器械物理边界
        cypher_equipments = """
            MATCH (u:User {user_id: $user_id})
            
            WITH u
            OPTIONAL MATCH (u)-[r2:HAS_EQUIPMENT]->()
            DELETE r2
            
            WITH u
            // 🛡️ 终极护栏：只有当器械不为空时，才执行绑定
            WHERE size($equipments) > 0
            UNWIND $equipments AS equip_name
            MATCH (e:Equipment {name: equip_name})
            MERGE (u)-[:HAS_EQUIPMENT]->(e)
        """

        try:
            def _write(session):
                session.run(
                    cypher_injuries,
                    user_id=str_user_id,
                    name=name,
                    level=level,
                    injuries=injuries,
                )
                session.run(
                    cypher_equipments,
                    user_id=str_user_id,
                    equipments=equipments,
                )

            await self._run_session(_write)
            logger.info(f"✅ [Semantic Memory] 成功为用户 [{name}] 固化了【防蒸发、防死锁】的长效语义记忆。")
            
        except Exception as e:
            logger.error(f"[GraphTool] 异步图数据库写库遭遇严重崩溃: {e}")
            raise e
        print(f"✅ [Semantic Memory] 成功为用户 [{name}] 固化了长效解剖学避灾与器械边界钢印。")

    async def fetch_user_semantic_memory(self, user_id: int) -> List[Dict[str, Any]]:
        """
        从 Neo4j 瞬间捞取该用户的长效语义记忆画像（包含伤病限制与器械边界）
        """
        cypher = """
            MATCH (u:User {user_id: $user_id})
            OPTIONAL MATCH (u)-[r1:HAS_INJURY]->(j:Joint)
            OPTIONAL MATCH (u)-[r2:HAS_EQUIPMENT]->(e:Equipment)
            RETURN u.level as level, 
                collect(distinct j.name) as injuries, 
                collect(distinct e.name) as equipment_list
            """
            
        def _query(session):
            result = session.run(cypher, user_id=str(user_id))
            return [record.data() for record in result]

        return await self._run_session(_query)

    async def append_injury_list_to_profile(self, user_id: int, injury_list: List[str]) -> bool:
        """
        [多维矩阵解包版]：在对话结束后，向用户的语义记忆动态追加【多个不适关节】红线
        """
        if not injury_list:
            return True
            
        cypher_injury = """
            MATCH (u:User {user_id: $user_id})
            // 1. 利用 UNWIND 将传入的伤病列表（如 ['手腕', '膝关节']）剁碎炸裂成多行平行处理流
            UNWIND $injury_list AS single_joint
            // 2. 匹配官方解剖学节点
            MATCH (j:Joint {name: single_joint})
            // 3. 完美的幂等合并：若这条不适线没拉过，拉起它并标记临时痛感 temporary_pain
            MERGE (u)-[r:HAS_INJURY]->(j)
            ON CREATE SET r.severity = "temporary_pain", r.updated_at = timestamp()
            ON MATCH SET r.updated_at = timestamp()
        """
        try:
            await self._run_session(
                lambda session: session.run(
                    cypher_injury, user_id=str(user_id), injury_list=injury_list
                )
            )
            logger.info(f"{LogColor.TOOL}[GraphTool] 🛡️ 伤病防线拓扑扩展成功！已并发并入 {injury_list} 拦截线。{LogColor.RESET}")
            return True
        except Exception as e:
            logger.error(f"[GraphTool] 后台并发追加伤病红线遭遇异常: {e}")
            return False

    async def remove_injuries_from_profile(
        self, user_id: int, injury_list: List[str]
    ) -> bool:
        """从用户语义画像中移除已恢复/不再受限的关节红线。"""
        if not injury_list:
            return True

        cypher = """
            MATCH (u:User {user_id: $user_id})-[r:HAS_INJURY]->(j:Joint)
            WHERE j.name IN $injury_list
            DELETE r
        """
        try:
            await self._run_session(
                lambda session: session.run(
                    cypher, user_id=str(user_id), injury_list=injury_list
                )
            )
            logger.info(
                f"{LogColor.TOOL}[GraphTool] 🩹 已移除伤病限制: {injury_list}{LogColor.RESET}"
            )
            return True
        except Exception as e:
            logger.error(f"[GraphTool] 移除伤病红线失败: {e}")
            return False

    async def remove_equipment_from_profile(
        self, user_id: int, equip_list: List[str]
    ) -> bool:
        """从用户语义画像中移除不再拥有的器材边界。"""
        if not equip_list:
            return True

        cypher = """
            MATCH (u:User {user_id: $user_id})-[r:HAS_EQUIPMENT]->(e:Equipment)
            WHERE e.name IN $equip_list
            DELETE r
        """
        try:
            await self._run_session(
                lambda session: session.run(
                    cypher, user_id=str(user_id), equip_list=equip_list
                )
            )
            logger.info(
                f"{LogColor.TOOL}[GraphTool] 📦 已移除器材: {equip_list}{LogColor.RESET}"
            )
            return True
        except Exception as e:
            logger.error(f"[GraphTool] 移除器材连线失败: {e}")
            return False

    async def append_equipment_list_to_profile(self, user_id: int, equip_list: List[str]) -> bool:
        """
        [多维矩阵解包版]：在对话结束后，向用户的语义记忆动态追加【多个新解锁器材】边界
        """
        if not equip_list:
            return True
            
        cypher_equip = """
            MATCH (u:User {user_id: $user_id})
            // 1. 将新买的器材列表解包
            UNWIND $equip_list AS single_equip
            // 2. 跨异构数据库语义对齐：匹配官方器械节点（若大模型脑补了不存在的词，此处自动匹配失败，安全不报错）
            MATCH (e:Equipment {name: single_equip})
            // 3. 建立手牌连线
            MERGE (u)-[:HAS_EQUIPMENT]->(e)
        """
        try:
            await self._run_session(
                lambda session: session.run(
                    cypher_equip, user_id=str(user_id), equip_list=equip_list
                )
            )
            logger.info(f"{LogColor.TOOL}[GraphTool] 🛠️ 器械资产拓扑扩展成功！已并发解禁 {equip_list} 筛选池。{LogColor.RESET}")
            return True
        except Exception as e:
            logger.error(f"[GraphTool] 后台并发追加器材连线遭遇异常: {e}")
            return False

    async def get_all_injury_edges(self):
        cypher_query = """
                MATCH (ex:Exercise)-[l:LOADS]->(j:Joint)
                WHERE j.name IN ["髋关节", "膝关节", "踝关节"]
                RETURN ex.name AS exercise_name, j.name AS joint_name
            """
        def _query(session):
            result = session.run(cypher_query)
            return [record.data() for record in result]

        return await self._run_session(_query)

    async def get_all_progression_regressions(self):
        cypher_query = """
            MATCH (base:Exercise)-[:PROGRESSION_OF]->(advanced:Exercise),
            (base)-[:TARGETS]->(m:Muscle)
            WHERE m.name IN ["股四头肌", "臀大肌", "腘绳肌", "外展肌群", "小腿肌群", "内收肌群"]
            RETURN base.name AS lower_action, 
                   advanced.name AS higher_action, 
                   base.difficulty AS low_level, 
                   advanced.difficulty AS high_level,
                   "PROGRESSION_OF" AS relation_type,
                   m.name AS muscle_name
            """
        def _query(session):
            result = session.run(cypher_query)
            return [record.data() for record in result]

        return await self._run_session(_query)

async def test():
    graph_tool = GraphTool()
    # params = GraphReasoningSchema(
    #     exercise_name="上斜飞鸟",
    #     muscle_name="下腹部",
    #     joint_name="踝关节",
    #     candidate_ids=["0030", "0032", "0042"],
    #     scenario="strengthen_joint",
    # )
    # result = await graph_tool.reason(params)
    # print(result)

    await graph_tool.init_user_semantic_memory(
        user_id=1, name="李小明", level="intermediate", injuries=["肩关节"], equipments=["哑铃", "弹力带", "泡沫轴", "自重"])


if __name__ == "__main__":
    asyncio.run(test())
