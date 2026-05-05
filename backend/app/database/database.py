import mysql.connector
import json
import os
from dotenv import load_dotenv
from ..config import settings
from typing import Optional
from ..models.schema import ExerciseBase, ExerciseDetail


def _get_connection():
    load_dotenv()
    return mysql.connector.connect(
        host=settings.DB_HOST,
        user=settings.DB_USERNAME,
        password=settings.DB_PASSWORD,
        database=settings.DB_DATABASE,
    )


def search_exercise_base(
    target=None,
    equipment=None,
    category=None,
    body_part=None,
    difficulty=None,
    name=None,
    limit=10,
):
    conn = _get_connection()
    cursor = conn.cursor(dictionary=True)

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
        "t.name_zh": target,
        "eq.name_zh": equipment,
        "c.name_zh": category,
        "b.name_zh": body_part,
        "e.difficulty": difficulty,
        "e.name_zh": name,
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

    final_sql += " LIMIT %s"
    query_params.append(limit)

    cursor.execute(final_sql, tuple(query_params))
    rows = cursor.fetchall()

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

    cursor.close()
    conn.close()
    return results


def search_exercise_detail(exercise_id: str) -> Optional[ExerciseDetail]:
    conn = _get_connection()
    cursor = conn.cursor(dictionary=True)

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

    cursor.execute(detail_sql, (exercise_id,))
    row = cursor.fetchone()

    if not row:
        cursor.close()
        conn.close()
        return None

    secondary_sql = """
    SELECT t.name_zh
    FROM exercise_secondary_muscles esm
    JOIN targets t ON esm.target_id = t.id
    WHERE esm.exercise_id = %s
    """
    cursor.execute(secondary_sql, (exercise_id,))
    secondary_muscles_zh = [r["name_zh"] for r in cursor.fetchall()]

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

    cursor.close()
    conn.close()
    return result


if __name__ == "__main__":
    # result = search_exercise_base(target="臀大肌", category="力量训练", body_part="大腿", difficulty="beginner")
    # print(result)
    result_detail = search_exercise_detail("0534")
    print(result_detail)
