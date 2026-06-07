import json
import asyncio
from app.database.mysql_db import MySQLManager
from app.models.schema import (
    ExerciseBase,
    ExerciseDetail,
    SQLSearchSchema,
    UserProfileRequest,
    UserSignupRequest,
)
from app.models.fitness import ChatSession, ChatRecord, AgentPlansLog, TrainingLog
from app.agent.utils.logger import logger, LogColor
from typing import Optional
import bcrypt
import mysql.connector


class SQLTool:
    def __init__(self):
        self.db_manager = MySQLManager()

    async def search_exercise_base(self, params: SQLSearchSchema) -> list[ExerciseBase]:

        base_sql = """
        SELECT
            e.id, e.name_zh, e.difficulty,
            b.name_zh AS body_part_zh,
            eq.name_zh AS equipment_zh,
            t.name_zh AS target_zh,
            c.name_zh AS category_zh
        FROM exercises e
        JOIN body_parts b ON e.body_part_id = b.id
        JOIN equipments eq ON e.equipment_id = eq.id
        JOIN targets t ON e.target_id = t.id
        JOIN categories c ON e.category_id = c.id
        """

        condition_map = {
            "t.name_zh": params.target_zh,
            "eq.name_zh": params.equipment_zh,
            "c.name_zh": params.category_zh,
            "b.name_zh": params.body_part_zh,
            "e.difficulty": params.difficulty,
            "e.name_zh": params.name_zh,
        }

        where_clauses = []
        query_params = []

        for column, value in condition_map.items():
            if value:
                where_clauses.append(f"{column} LIKE %s")
                query_params.append(f"%{value}%")

        final_sql = base_sql
        if where_clauses:
            final_sql += " WHERE " + " AND ".join(where_clauses)

        calculated_limit = max(params.limit * 3, 12)
        final_sql += " LIMIT %s"
        query_params.append(calculated_limit)

        try:
            with self.db_manager.get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute(final_sql, tuple(query_params))
                    rows = cursor.fetchall()
        except mysql.connector.Error as err:
            raise err
        results = []
        for row in rows:
            results.append(
                ExerciseBase(
                    id=row["id"],
                    name_zh=row["name_zh"],
                    body_part_zh=row["body_part_zh"],
                    equipment_zh=row["equipment_zh"],
                    target_zh=row["target_zh"],
                    difficulty=row["difficulty"],
                    category_zh=row["category_zh"],
                )
            )
        logger.info(
            f"{LogColor.TOOL}[SQLTool] 🔍 正在输出SQL调用结果，Result: '{results}'{LogColor.RESET}"
        )
        return results

    async def search_exercise_detail(
        self, exercise_id: str
    ) -> Optional[ExerciseDetail]:

        detail_sql = """
        SELECT
            e.id, e.name_zh, e.difficulty,
            b.name_zh AS body_part_zh,
            eq.name_zh AS equipment_zh,
            t.name_zh AS target_zh,
            c.name_zh AS category_zh,
            e.instructions_zh,
            e.description_zh,
            e.local_gif_path AS gif_path
        FROM exercises e
        JOIN body_parts b ON e.body_part_id = b.id
        JOIN equipments eq ON e.equipment_id = eq.id
        JOIN targets t ON e.target_id = t.id
        JOIN categories c ON e.category_id = c.id
        WHERE e.id = %s
        """

        secondary_sql = """
        SELECT t.name_zh
        FROM exercise_secondary_muscles esm
        JOIN targets t ON esm.target_id = t.id
        WHERE esm.exercise_id = %s
        """
        try:
            with self.db_manager.get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute(detail_sql, (exercise_id,))
                    row = cursor.fetchone()

                    cursor.execute(secondary_sql, (exercise_id,))
                    secondary_rows = cursor.fetchall()
        except mysql.connector.Error as err:
            print(f"Database Error: {err}")
            raise err
        secondary_muscles_zh = [r["name_zh"] for r in secondary_rows]

        instructions_zh = row["instructions_zh"]
        if isinstance(instructions_zh, str):
            instructions_zh = json.loads(instructions_zh)
        if instructions_zh is None:
            instructions_zh = []

        result = ExerciseDetail(
            id=row["id"],
            name_zh=row["name_zh"],
            difficulty=row["difficulty"],
            body_part_zh=row["body_part_zh"],
            equipment_zh=row["equipment_zh"],
            target_zh=row["target_zh"],
            category_zh=row["category_zh"],
            instructions_zh=instructions_zh,
            secondary_muscles_zh=secondary_muscles_zh,
            description_zh=row["description_zh"],
            gif_path=row["gif_path"],
        )

        return result

    async def search_profile(self, id: int) -> Optional[UserProfileRequest]:
        base_sql = """
        SELECT username, gender,
            weight_kg, height_cm,
            fitness_level, fitness_goal, 
            available_equipments_raw, injury_joints_raw 
            FROM users WHERE id = %s """
        try:
            with self.db_manager.get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute(base_sql, (id,))
                    row = cursor.fetchone()

        except mysql.connector.Error as err:
            print(f"Database Error: {err}")
            raise err

        userProfile = UserProfileRequest(
            username=row["username"],
            gender=row["gender"],
            weight_kg=row["weight_kg"],
            height_cm=row["height_cm"],
            fitness_level=row["fitness_level"],
            fitness_goal=row["fitness_goal"],
            equipments=row["available_equipments_raw"],
            injuries=row["injury_joints_raw"],
        )

        return userProfile

    async def get_user_credentials_by_name(self, username: str):
        base_sql = """
        SELECT uc.password_hash, uc.user_id
        from user_credentials uc JOIN users u on u.id = uc.user_id 
        WHERE u.username = %s """
        try:
            with self.db_manager.get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute(base_sql, (username,))
                    row = cursor.fetchone()

        except mysql.connector.Error as err:
            print(f"Database Error: {err}")
            raise err

        return row

    def _sync_create_or_ignore_session(self, chatSession: ChatSession):
        """[内部同步核线]：会话主表激活"""
        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                query = "INSERT IGNORE INTO chat_sessions (session_id, user_id) VALUES (%s, %s)"
                cursor.execute(query, (chatSession.session_id, chatSession.user_id))
            conn.commit()

    def _sync_log_chat_transaction(
        self, userChatRecord: ChatRecord, coachChatRecord: ChatRecord
    ):
        """[内部同步核线]：chat_records 双写流水账"""
        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                query = "INSERT INTO chat_records (session_id, role, content) VALUES (%s, %s, %s)"
                # 开启显式强事务，一键砸入双向流水
                cursor.execute(
                    query, (userChatRecord.session_id, "user", userChatRecord.content)
                )
                cursor.execute(
                    query,
                    (coachChatRecord.session_id, "assistant", coachChatRecord.content),
                )
            conn.commit()

    def _sync_save_training_log(self, trainingLog: TrainingLog):
        """[内部同步核线]：training_logs 固化资产课表"""
        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    INSERT INTO training_logs (user_id, session_id, plan_title, generated_plan_json, is_completed) 
                    VALUES (%s, %s, %s, %s, 0)
                """
                extracted_data = [
                    {
                        "id": item.id,
                        "name_zh": item.name_zh
                    }
                    for item in trainingLog.generated_plan_json
                ]
                json_str = json.dumps(extracted_data, ensure_ascii=False)

                cursor.execute(
                    query,
                    (
                        trainingLog.user_id,
                        trainingLog.session_id,
                        trainingLog.coach_reply_summary,
                        json_str,
                    ),
                )
            conn.commit()

    def _sync_log_agent_plan_decision(self, agentPlanLog: AgentPlansLog):
        """[内部同步核线]：agent_plans_log 审计日志线落盘"""
        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    INSERT INTO agent_plans_log (session_id, user_query, loop_retry_count, macro_blueprint, native_full_plan, executed_results, analyzer_final_reason) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """

                extracted_data = [
                    {
                        "task_id": item.task_id,
                        "tool_name": item.tool_name,
                        "reason": item.reason,
                        "focused_query": item.focused_query
                    }
                    for item in agentPlanLog.macro_blueprint
                ]

                full_plan_payload = (
                    agentPlanLog.native_full_plan.model_dump()
                    if hasattr(agentPlanLog.native_full_plan, "model_dump")
                    else agentPlanLog.native_full_plan
                )
                executed_payload = agentPlanLog.executed_results
                if not isinstance(executed_payload, str):
                    executed_payload = json.dumps(
                        executed_payload, ensure_ascii=False, default=str
                    )

                cursor.execute(
                    query,
                    (
                        agentPlanLog.session_id,
                        agentPlanLog.user_query,
                        agentPlanLog.loop_retry_count,
                        json.dumps(extracted_data, ensure_ascii=False),
                        json.dumps(full_plan_payload, ensure_ascii=False, default=str),
                        executed_payload,
                        agentPlanLog.analyzer_final_reason,
                    ),
                )
            conn.commit()

    def _init_user(self, userSignupRequest: UserSignupRequest) -> int:
        """
        [内部同步强事务]：一键安全双写用户基础画像表与独立密码表，保障绝对的原子性
        """
        # 1. 🛡️ 大厂级金牌安全规范：在进入数据库前，将前端送来的明文密码执行 Bcrypt 强盐值哈希！
        # 产生安全的不可逆哈希串（形如 $2b$12$...）
        bytes_password = userSignupRequest.password.encode("utf-8")
        salt_bytes = bcrypt.gensalt()
        hashed_password_str = bcrypt.hashpw(bytes_password, salt_bytes).decode("utf-8")

        with self.db_manager.get_connection() as conn:
            conn.start_transaction()
            try:
                with conn.cursor() as cursor:
                    # 第一步：写入基础 users 表 (丢弃明文密码，只存画像)
                    insert_user_query = """
                        INSERT INTO users (username, gender, weight_kg, height_cm, fitness_level, fitness_goal, available_equipments_raw, injury_joints_raw)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(
                        insert_user_query,
                        (
                            userSignupRequest.username,
                            userSignupRequest.gender,
                            userSignupRequest.weight_kg,
                            userSignupRequest.height_cm,
                            userSignupRequest.fitness_level,
                            userSignupRequest.fitness_goal,
                            userSignupRequest.equipments,
                            userSignupRequest.injuries,
                        ),
                    )

                    new_user_id = cursor.lastrowid
                    print("new user id: ", new_user_id)

                    # 第二步：将物理隔离的哈希密码，塞进独立的凭证表 user_credentials
                    insert_cred_query = """
                        INSERT INTO user_credentials (user_id, password_hash)
                        VALUES (%s, %s)
                    """
                    cursor.execute(
                        insert_cred_query, (new_user_id, hashed_password_str)
                    )

                # 两个表同时写成功，才允许 Commit 物理落盘！
                conn.commit()
                return new_user_id

            except Exception as e:
                # 容灾自愈：一旦有任何一张表发生冲突（如用户名重名），执行全体回滚，绝不产生数据孤儿！
                conn.rollback()
                logger.error(f"[AuthDB] 注册双写事务触发原子性回滚！原因: {e}")
                raise e

    def _update_user_profile(self, userProfileRequest: UserProfileRequest):
        with self.db_manager.get_connection() as conn:
            conn.start_transaction()
            try:
                with conn.cursor() as cursor:
                    update_user_query = """
                        UPDATE users 
                        SET username = %s, gender = %s, 
                        weight_kg = %s, height_cm = %s,
                        fitness_level = %s, fitness_goal = %s,
                        available_equipments_raw = %s, injury_joints_raw = %s
                        WHERE username = %s
                    """
                    cursor.execute(
                        update_user_query,
                        (
                            userProfileRequest.username,
                            userProfileRequest.gender,
                            userProfileRequest.weight_kg,
                            userProfileRequest.height_cm,
                            userProfileRequest.fitness_level,
                            userProfileRequest.fitness_goal,
                            userProfileRequest.equipments,
                            userProfileRequest.injuries,
                            userProfileRequest.username,
                        ),
                    )

                # 两个表同时写成功，才允许 Commit 物理落盘！
                conn.commit()
                return "success"
            except Exception as e:
                # 容灾自愈：一旦有任何一张表发生冲突（如用户名重名），执行全体回滚，绝不产生数据孤儿！
                conn.rollback()
                logger.error(f"[AuthDB] 注册双写事务触发原子性回滚！原因: {e}")
                raise e

    async def create_or_ignore_session(self, chatSession: ChatSession):
        await asyncio.to_thread(self._sync_create_or_ignore_session, chatSession)

    async def log_chat_transaction(
        self, userChatRecord: ChatRecord, coachChatRecord: ChatRecord
    ):
        await asyncio.to_thread(
            self._sync_log_chat_transaction, userChatRecord, coachChatRecord
        )

    async def save_training_log(self, trainingLog: TrainingLog):
        await asyncio.to_thread(self._sync_save_training_log, trainingLog)

    async def log_agent_plan_decision(self, agentPlansLog: AgentPlansLog):
        await asyncio.to_thread(self._sync_log_agent_plan_decision, agentPlansLog)

    async def init_user(self, userSignupRequest: UserSignupRequest):
        new_user_id = await asyncio.to_thread(self._init_user, userSignupRequest)
        return new_user_id

    async def update_user_profile(self, userSignupRequest: UserSignupRequest):
        await asyncio.to_thread(self._update_user_profile, userSignupRequest)

    def _sync_get_user_semantic_raw(self, user_id: int) -> dict | None:
        query = """
            SELECT fitness_level, available_equipments_raw, injury_joints_raw
            FROM users WHERE id = %s
        """
        with self.db_manager.get_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, (user_id,))
                return cursor.fetchone()

    def _sync_update_user_semantic_raw(
        self,
        user_id: int,
        injury_joints_raw: str | None,
        available_equipments_raw: str,
    ) -> None:
        query = """
            UPDATE users
            SET injury_joints_raw = %s,
                available_equipments_raw = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """
        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (
                        injury_joints_raw or None,
                        available_equipments_raw or "自重",
                        user_id,
                    ),
                )
            conn.commit()

    async def get_user_semantic_raw(self, user_id: int) -> dict | None:
        return await asyncio.to_thread(self._sync_get_user_semantic_raw, user_id)

    async def update_user_semantic_raw(
        self,
        user_id: int,
        injury_joints_raw: str | None,
        available_equipments_raw: str,
    ) -> None:
        await asyncio.to_thread(
            self._sync_update_user_semantic_raw,
            user_id,
            injury_joints_raw,
            available_equipments_raw,
        )

    async def get_all_exercises(self) -> list[ExerciseBase]:
        sql_query = """
            SELECT
                e.id, e.name_zh, e.difficulty,
                b.name_zh AS body_part_zh,
                eq.name_zh AS equipment_zh,
                t.name_zh AS target_zh,
                c.name_zh AS category_zh
            FROM exercises e
            JOIN body_parts b ON e.body_part_id = b.id
            JOIN equipments eq ON e.equipment_id = eq.id
            JOIN targets t ON e.target_id = t.id
            JOIN categories c ON e.category_id = c.id
            """
        try:
            with self.db_manager.get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute(sql_query)
                    rows = cursor.fetchall()
        except mysql.connector.Error as err:
            raise err
        results = []
        for row in rows:
            results.append(
                ExerciseBase(
                    id=row["id"],
                    name_zh=row["name_zh"],
                    body_part_zh=row["body_part_zh"],
                    equipment_zh=row["equipment_zh"],
                    target_zh=row["target_zh"],
                    difficulty=row["difficulty"],
                    category_zh=row["category_zh"],
                )
            )
        return results

    async def get_user_sessions(self, user_id: str):
        sql_query = """SELECT cr.id as id,
                        cr.session_id as session_id,
                        cr.role as role,
                        cr.content as content,
                        cr.created_at as created_at
                    FROM chat_records as cr
                            JOIN chat_sessions cs on cs.session_id = cr.session_id
                    WHERE user_id = %s"""

        try:
            with self.db_manager.get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute(sql_query, (user_id,))
                    rows = cursor.fetchall()
                    print("rows: ", rows)
        except mysql.connector.Error as err:
            raise err
        
        sessions_map = {}
        for r in rows:
            if r["session_id"] not in sessions_map:
                sessions_map[r["session_id"]] = {
                    "session_id": r["session_id"],
                    "last_message": r["content"][:20] + "...",
                    "created_at": r["created_at"].strftime("%m-%d %H:%M")
                }
                
        return list(sessions_map.values())

    async def get_session_details(self, session_id):
        sql_query = """SELECT id, session_id,
                        role, content, created_at
                    FROM chat_records
                    WHERE session_id = %s
                    ORDER BY id ASC"""

        try:
            with self.db_manager.get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute(sql_query, (session_id,))
                    rows = cursor.fetchall()
        except mysql.connector.Error as err:
            raise err
        
        return rows

async def test():
    sql_tool = SQLTool()
    print("search base")
    params = SQLSearchSchema(
        difficulty="beginner", equipment_zh="哑铃", body_part_zh="腰腹", limit=10
    )
    result1 = await sql_tool.search_exercise_base(params)
    print(result1)

    # print("----------")

    # result2 = await sql_tool.search_exercise_detail("0012")
    # print(result2)


if __name__ == "__main__":
    asyncio.run(test())
    # print("search exercise id")
    # print(sql_tool.search_exercise_detail("0012"))
