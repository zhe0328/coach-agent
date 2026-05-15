import json
import asyncio
from app.database.mysql_db import MySQLManager
from app.models.schema import ExerciseBase, ExerciseDetail, SQLSearchSchema
from typing import Optional


class SQLTool:
    def __init__(self):
        self.db_manager = MySQLManager()

    async def search_exercise_base(
        self, params: SQLSearchSchema
    ) -> list[ExerciseBase]:

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
            print(f"Database Error: {err}")
            return []
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
        print("[SQL Result Length]: ", len(results))
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
            return []
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

async def test():
    sql_tool = SQLTool();
    print("search base")
    params = SQLSearchSchema(
        difficulty="beginner",
        equipment_zh="哑铃",
        body_part_zh="腰腹",
        limit=10
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