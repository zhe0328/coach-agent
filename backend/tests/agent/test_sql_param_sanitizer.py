import pytest

from app.agent.roles.sql_param_sanitizer import (
    SqlParamCatalog,
    body_part_literals_from_schema,
    sanitize_sql_search_params,
)
from app.models.schema import SQLSearchSchema


@pytest.fixture
def catalog() -> SqlParamCatalog:
    parts = body_part_literals_from_schema()
    return SqlParamCatalog.from_db_rows(
        body_part_rows=list(parts),
        target_body_part_rows=[
            ("胸肌", "胸部"),
            ("胸大肌", "胸部"),
            ("腹直肌", "腰腹"),
        ],
    )


def test_clears_name_zh_when_region_term(catalog):
    raw = SQLSearchSchema(name_zh="胸肌", body_part_zh="胸部", limit=4)
    cleaned = sanitize_sql_search_params(raw, catalog=catalog)

    assert cleaned.name_zh is None
    assert cleaned.body_part_zh == "胸部"


def test_moves_target_region_to_body_part(catalog):
    raw = SQLSearchSchema(target_zh="胸部", limit=4)
    cleaned = sanitize_sql_search_params(raw, catalog=catalog)

    assert cleaned.body_part_zh == "胸部"
    assert cleaned.target_zh is None


def test_drops_conflicting_target_when_body_part_set(catalog):
    raw = SQLSearchSchema(body_part_zh="腰腹", target_zh="胸肌", limit=4)
    cleaned = sanitize_sql_search_params(raw, catalog=catalog)

    assert cleaned.body_part_zh == "腰腹"
    assert cleaned.target_zh is None


def test_drops_redundant_target_when_body_part_set(catalog):
    raw = SQLSearchSchema(body_part_zh="胸部", target_zh="胸大肌", limit=4)
    cleaned = sanitize_sql_search_params(raw, catalog=catalog)

    assert cleaned.body_part_zh == "胸部"
    assert cleaned.target_zh is None


def test_keeps_real_exercise_name(catalog):
    raw = SQLSearchSchema(name_zh="反向卷腹", body_part_zh="腰腹", limit=4)
    cleaned = sanitize_sql_search_params(raw, catalog=catalog)

    assert cleaned.name_zh == "反向卷腹"


def test_infers_body_part_from_focused_query(catalog):
    raw = SQLSearchSchema(equipment_zh="哑铃", limit=4)
    cleaned = sanitize_sql_search_params(
        raw, focused_query="用哑铃练胸", catalog=catalog
    )

    assert cleaned.body_part_zh == "胸部"
    assert cleaned.name_zh is None


def test_catalog_from_db_rows_uses_schema_intersection():
    catalog = SqlParamCatalog.from_db_rows(
        body_part_rows=["胸部", "NOT_IN_SCHEMA"],
        target_body_part_rows=[("胸大肌", "胸部"), ("胸大肌", "NOT_IN_SCHEMA")],
    )

    assert "胸部" in catalog.body_parts
    assert "NOT_IN_SCHEMA" not in catalog.body_parts
    assert catalog.target_to_body_parts["胸大肌"] == frozenset({"胸部"})
