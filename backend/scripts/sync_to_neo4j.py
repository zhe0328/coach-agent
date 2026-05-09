import mysql.connector
from neo4j import GraphDatabase # 之前定义的配置类
from difflib import SequenceMatcher
from ..app.config import settings

def similarity(a, b):
    # 计算两个字符串的相似度评分 (0-1)
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

JOINT_MAPPING = {
    # 肩关节
    "三角肌": "肩关节", "三角肌后束": "肩关节", "背阔肌": "肩关节", "阔背肌": "肩关节",
    "胸肌": "肩关节", "上胸部": "肩关节", "胸部": "肩关节", "肩袖肌群": "肩关节",
    "前锯肌": "肩关节", "肩部": "肩关节",
    # 肘关节
    "肱二头肌": "肘关节", "肱三头肌": "肘关节", "肱肌": "肘关节", "前臂肌群": "肘关节",
    # 腕关节
    "手腕": "腕关节", "腕伸肌": "腕关节", "腕屈肌": "腕关节", "握力肌群": "腕关节", "手部": "腕关节",
    # 髋关节
    "臀大肌": "髋关节", "臀中肌": "髋关节", "臀中肌（后部纤维）": "髋关节", "臀小肌": "髋关节", "梨状肌": "髋关节",
    "内/外闭孔肌": "髋关节", "内闭孔肌": "髋关节",
    "髋屈肌": "髋关节", "外展肌群": "髋关节", "内收肌群": "髋关节", "大腿内侧": "髋关节",
    "上/下孖肌": "髋关节",
    # 膝关节
    "股四头肌": "膝关节", "腘绳肌": "膝关节",
    # 踝关节
    "小腿肌群": "踝关节", "比目鱼肌": "踝关节", "腓肠肌": "踝关节", "胫骨前肌": "踝关节",
    "胫骨后肌": "踝关节", "第三腓骨肌": "踝关节", "腓骨长肌": "踝关节", "腓骨短肌": "踝关节",
    "趾长伸肌": "踝关节", "拇长伸肌": "踝关节", "趾长屈肌": "踝关节", "拇长屈肌": "踝关节",
    "踝关节": "踝关节", "踝关节稳定肌": "踝关节", "脚部": "踝关节", "胫部": "踝关节",
    # 脊柱/核心
    "核心": "脊柱", "腹肌": "脊柱", "下腹部": "脊柱", "腹外斜肌": "脊柱", 
    "脊柱区域": "脊柱", "下背部": "脊柱", "上背部": "脊柱", "背部": "脊柱",
    # 颈部
    "颈长肌": "颈部", "头长肌": "颈部", "颈深屈肌": "颈部", "头夹肌": "颈部", 
    "颈夹肌": "颈部", "头半棘肌": "颈部", "胸锁乳突肌": "颈部", "斜角肌": "颈部", 
    "下枕肌群": "颈部", "肩胛提肌": "颈部",
    # 肩胛带
    "斜方肌": "肩胛带", "斜方肌上部": "肩胛带", "菱形肌": "肩胛带"
}

class Neo4jSync:
    def __init__(self):
        # MySQL 连接
        self.mysql_conn = mysql.connector.connect(
            host=settings.DB_HOST,
            user=settings.DB_USERNAME,
            password=settings.DB_PASSWORD,
            database=settings.DB_DATABASE,
        )
        # Neo4j 连接 (假设 .env 中已添加相关变量)
        self.neo4j_driver = GraphDatabase.driver(
            settings.NEO4J_BASE_URL,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
        )

    def close(self):
        self.mysql_conn.close()
        self.neo4j_driver.close()

# ... 前面代码保持不变 ...
    def run_sync(self):
        with self.neo4j_driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n") # 开发阶段清空

            cursor = self.mysql_conn.cursor(dictionary=True)
            
            # 1. 核心动作及主目标肌肉查询
            main_query = """
            SELECT e.id, e.name_zh, e.difficulty, 
                   t.name_zh as target_muscle, 
                   eq.name_zh as equipment, 
                   b.name_zh as body_part
            FROM exercises e
            JOIN targets t ON e.target_id = t.id
            JOIN equipments eq ON e.equipment_id = eq.id
            JOIN body_parts b ON e.body_part_id = b.id
            """
            cursor.execute(main_query)
            exercises = cursor.fetchall()

            # 2. 获取所有辅助肌肉关系数据
            # 一次性取回，避免在循环中频繁查库
            sec_muscle_query = """
            SELECT esm.exercise_id, t.name_zh as muscle_name
            FROM exercise_secondary_muscles esm
            JOIN targets t ON esm.target_id = t.id
            """
            cursor.execute(sec_muscle_query)
            sec_muscles = cursor.fetchall()
            
            # 将辅助肌肉按 exercise_id 分组
            sec_map = {}
            for item in sec_muscles:
                sec_map.setdefault(item['exercise_id'], []).append(item['muscle_name'])

            # 3. 执行同步
            for ex in exercises:
                # 获取该动作对应的辅助肌肉列表
                current_sec_muscles = sec_map.get(ex['id'], [])
                
                # 写入 Neo4j
                session.execute_write(
                    self._create_exercise_nodes, 
                    ex, 
                    current_sec_muscles
                )

            # 4. 构建进阶逻辑 (保持不变)
            self._build_progression_logic(session)

    @staticmethod
    def _create_exercise_nodes(tx, ex, sec_muscles):
        # Cypher：创建节点并建立 Primary 和 Synergist 关系
        query = """
        MERGE (e:Exercise {id: $id})
        SET e.name = $name, e.difficulty = $difficulty
        
        MERGE (m_main:Muscle {name: $target_muscle})
        MERGE (eq:Equipment {name: $equipment})
        
        // 核心关系 1: 主目标肌肉
        MERGE (e)-[:TARGETS {intensity: 'primary'}]->(m_main)
        MERGE (e)-[:REQUIRES]->(eq)

        // 核心关系 3: 协同肌关系 (使用 FOREACH 处理列表)
        WITH e
        UNWIND $sec_muscles AS sec_muscle_name
        MERGE (m_sec:Muscle {name: sec_muscle_name})
        MERGE (e)-[:SYNERGIST]->(m_sec)
        """
        tx.run(query, 
               id=ex['id'], 
               name=ex['name_zh'], 
               difficulty=ex['difficulty'], 
               target_muscle=ex['target_muscle'],
               equipment=ex['equipment'],
               sec_muscles=sec_muscles)

    def _build_progression_logic(self, session):
        """
        自动化逻辑：在相同目标肌肉下，将 beginner -> intermediate -> advanced 连成线
        """
        query = """
        MATCH (e1:Exercise)-[:TARGETS]->(m:Muscle)<-[:TARGETS]-(e2:Exercise)
        WHERE e1.difficulty = 'beginner' AND e2.difficulty = 'intermediate'
        MERGE (e1)-[:PROGRESSION_OF]->(e2)
        MERGE (e2)-[:REGRESSION_OF]->(e1)
        """
        session.run(query)

    def _build_progression_logic_advanced(self, session):
        """
        自动化逻辑：在相同目标肌肉下，将 beginner -> intermediate -> advanced 连成线
        """
        query = """
        MATCH (e1:Exercise)-[:TARGETS]->(m:Muscle)<-[:TARGETS]-(e2:Exercise)
        WHERE e1.difficulty = 'intermediate' AND e2.difficulty = 'advanced'
        MERGE (e1)-[:PROGRESSION_OF]->(e2)
        MERGE (e2)-[:REGRESSION_OF]->(e1)
        """
        session.run(query)

    def _add_joint(self, session):
        for muscle_name, joint_name in JOINT_MAPPING.items():
            query = """
            MATCH (e:Exercise)-[:TARGETS|SYNERGIST]->(m:Muscle {name: $muscle_name})
            MERGE (j:Joint {name: $joint_name})
            MERGE (e)-[:LOADS {stress: 'active'}]->(j)
            """
            session.run(query, muscle_name=muscle_name, joint_name=joint_name)

    def _refine_progression(self, session):
        print("正在删除旧的进阶/退让关系...")
        session.run("MATCH ()-[r:PROGRESSION_OF|REGRESSION_OF]->() DELETE r")

        # 2. 获取具有相同“肌肉+器材”但“难度不同”的动作对
        query = """
        MATCH (e1:Exercise)-[:TARGETS {intensity: 'primary'}]->(m:Muscle)<-[:TARGETS {intensity: 'primary'}]-(e2:Exercise)
        MATCH (e1)-[:REQUIRES]->(eq:Equipment)<-[:REQUIRES]-(e2:Exercise)
        WHERE 
            (e1.difficulty = 'beginner' AND e2.difficulty = 'intermediate') OR
            (e1.difficulty = 'intermediate' AND e2.difficulty = 'advanced')
        RETURN e1.id AS id1, e1.name AS name1, e2.id AS id2, e2.name AS name2
        """
        candidates = session.run(query)

        # 3. 在 Python 中进行相似度过滤
        relationships_to_create = []
        for rec in candidates:
            score = similarity(rec['name1'], rec['name2'])
            # 设置阈值：0.6 通常能涵盖 "Barbell Squat" vs "Barbell Front Squat" 
            # 或者包含关系
            if score > 0.6 or rec['name1'].lower() in rec['name2'].lower() or rec['name2'].lower() in rec['name1'].lower():
                relationships_to_create.append((rec['id1'], rec['id2']))

        # 4. 批量写回 Neo4j
        write_query = """
        UNWIND $pairs AS pair
        MATCH (a:Exercise {id: pair[0]}), (b:Exercise {id: pair[1]})
        MERGE (a)-[:PROGRESSION_OF]->(b)
        MERGE (b)-[:REGRESSION_OF]->(a)
        """
        session.run(write_query, pairs=relationships_to_create)
        print(f"成功建立了 {len(relationships_to_create)} 条精准进阶关系。")

if __name__ == "__main__":
    syncer = Neo4jSync()
    with syncer.neo4j_driver.session() as session:
        syncer._refine_progression(session)
    syncer.close()

    print(len(JOINT_MAPPING))
