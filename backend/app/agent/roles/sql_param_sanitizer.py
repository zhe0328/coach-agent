"""Post-process SQLSearchSchema — resolve name/body_part/target conflicts using DB catalog."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Union, get_args, get_origin

from app.models.schema import ExerciseFields, SQLSearchSchema

if TYPE_CHECKING:
    from app.tools.sql_tool import SQLTool

# Colloquial terms that do not appear in body_parts.name_zh but appear in user speech.
COLLOQUIAL_BODY_PART: dict[str, str] = {
    "核心": "腰腹",
    "练核心": "腰腹",
}

_ACTION_NAME_HINTS = re.compile(
    r"(推|拉|蹲|举|弯|伸|卷|抬|摆|撑|跳|跑|走|划|振|旋|桥|踢|蹬|握|吊|悬|卧|站|坐|跪|冲|击|甩|提|按|压|推起|下拉|飞鸟|硬拉|划船|俯卧撑|波比|平板|支撑|开合|登山|超人|死虫|鸟狗|臀桥|弓步|阶梯|提踵)"
)


def body_part_literals_from_schema() -> frozenset[str]:
    """Read body_part_zh Literal values from SQLSearchSchema (single source of truth)."""
    ann = ExerciseFields.model_fields["body_part_zh"].annotation
    if get_origin(ann) is Union:
        ann = next(a for a in get_args(ann) if a is not type(None))
    return frozenset(get_args(ann))


@dataclass(frozen=True)
class SqlParamCatalog:
    """MySQL-backed vocabulary for SQL param sanitization."""

    body_parts: frozenset[str]
    targets: frozenset[str]
    target_to_body_parts: dict[str, frozenset[str]]

    @classmethod
    def bootstrap(cls) -> SqlParamCatalog:
        return cls(
            body_parts=body_part_literals_from_schema(),
            targets=frozenset(),
            target_to_body_parts={},
        )

    @classmethod
    def from_db_rows(
        cls,
        *,
        body_part_rows: list[str],
        target_body_part_rows: list[tuple[str, str]],
    ) -> SqlParamCatalog:
        schema_parts = body_part_literals_from_schema()
        body_parts = frozenset(body_part_rows) & schema_parts or schema_parts

        target_map: dict[str, set[str]] = {}
        for target_zh, body_part_zh in target_body_part_rows:
            if body_part_zh not in schema_parts:
                continue
            target_map.setdefault(target_zh, set()).add(body_part_zh)

        return cls(
            body_parts=body_parts,
            targets=frozenset(target_map.keys()),
            target_to_body_parts={
                target: frozenset(parts) for target, parts in target_map.items()
            },
        )

    def blocked_name_terms(self) -> frozenset[str]:
        return self.body_parts | self.targets | frozenset(COLLOQUIAL_BODY_PART.keys())


def _normalize_token(text: str | None) -> str:
    return (text or "").strip()


def _resolve_colloquial(token: str, catalog: SqlParamCatalog) -> str | None:
    cleaned = _normalize_token(token)
    if cleaned in COLLOQUIAL_BODY_PART:
        part = COLLOQUIAL_BODY_PART[cleaned]
        return part if part in catalog.body_parts else None
    for alias, part in sorted(COLLOQUIAL_BODY_PART.items(), key=lambda x: -len(x[0])):
        if alias in cleaned:
            return part if part in catalog.body_parts else None
    return None


def _match_body_part(token: str, catalog: SqlParamCatalog) -> str | None:
    cleaned = _normalize_token(token)
    if not cleaned:
        return None
    if cleaned in catalog.body_parts:
        return cleaned

    colloquial = _resolve_colloquial(cleaned, catalog)
    if colloquial:
        return colloquial

    for part in sorted(catalog.body_parts, key=len, reverse=True):
        if part in cleaned or cleaned in part:
            return part

    for part in sorted(catalog.body_parts, key=len, reverse=True):
        if len(part) >= 2 and part[0] in cleaned:
            return part

    return None


def _infer_body_part_from_text(text: str, catalog: SqlParamCatalog) -> str | None:
    for alias, part in sorted(COLLOQUIAL_BODY_PART.items(), key=lambda x: -len(x[0])):
        if alias in text and part in catalog.body_parts:
            return part

    for part in sorted(catalog.body_parts, key=len, reverse=True):
        if part in text:
            return part

    for part in sorted(catalog.body_parts, key=len, reverse=True):
        if len(part) >= 2 and part[0] in text:
            return part

    return None


def _resolve_target_body_parts(target: str, catalog: SqlParamCatalog) -> frozenset[str]:
    cleaned = _normalize_token(target)
    if not cleaned:
        return frozenset()

    if cleaned in catalog.target_to_body_parts:
        return catalog.target_to_body_parts[cleaned]

    matches: set[str] = set()
    for target_name, parts in catalog.target_to_body_parts.items():
        if target_name in cleaned or cleaned in target_name:
            matches.update(parts)
    return frozenset(matches)


def _target_compatible_with_body_part(
    target: str,
    body_part: str,
    catalog: SqlParamCatalog,
) -> bool:
    allowed = _resolve_target_body_parts(target, catalog)
    if allowed:
        return body_part in allowed

    cleaned = _normalize_token(target)
    if body_part in cleaned or cleaned in body_part:
        return True
    if len(body_part) >= 2 and body_part[0] in cleaned:
        return True
    return False


def _looks_like_exercise_name(name: str, catalog: SqlParamCatalog) -> bool:
    cleaned = _normalize_token(name)
    if not cleaned or len(cleaned) < 2:
        return False
    if cleaned in catalog.blocked_name_terms():
        return False
    if _match_body_part(cleaned, catalog) and not _ACTION_NAME_HINTS.search(cleaned):
        return False
    return True


def sanitize_sql_search_params(
    params: SQLSearchSchema,
    *,
    focused_query: str = "",
    catalog: SqlParamCatalog | None = None,
) -> SQLSearchSchema:
    """
    Normalize small-planner SQL params:
    - name_zh: real exercise names only (not body part / muscle / region)
    - body_part_zh vs target_zh: avoid AND conflicts; prefer one axis
    """
    cat = catalog or SqlParamCatalog.bootstrap()
    data = params.model_dump()

    name = _normalize_token(data.get("name_zh"))
    body = data.get("body_part_zh")
    target = _normalize_token(data.get("target_zh"))

    if name and not _looks_like_exercise_name(name, cat):
        inferred = _match_body_part(name, cat)
        if inferred and not body:
            data["body_part_zh"] = inferred
        data["name_zh"] = None
        name = None

    if target:
        if target in cat.body_parts:
            if not body:
                data["body_part_zh"] = target
            data["target_zh"] = None
            target = None
        else:
            inferred_from_target = _match_body_part(target, cat)
            resolved_targets = _resolve_target_body_parts(target, cat)
            if inferred_from_target and not resolved_targets:
                if not body:
                    data["body_part_zh"] = inferred_from_target
                data["target_zh"] = None
                target = None

    body = data.get("body_part_zh")
    target = _normalize_token(data.get("target_zh"))

    if body and body not in cat.body_parts:
        data["body_part_zh"] = _match_body_part(str(body), cat)
        body = data.get("body_part_zh")

    if not body and focused_query:
        inferred = _infer_body_part_from_text(focused_query, cat)
        if inferred:
            data["body_part_zh"] = inferred
            body = inferred

    target = _normalize_token(data.get("target_zh"))
    if body and target and not _target_compatible_with_body_part(target, body, cat):
        data["target_zh"] = None
        target = None

    if body and target:
        # Redundant narrow AND — keep regional body_part for recall.
        data["target_zh"] = None

    name = _normalize_token(data.get("name_zh"))
    body = data.get("body_part_zh")
    target = _normalize_token(data.get("target_zh"))
    if name and (name == target or name == body):
        data["name_zh"] = None

    return SQLSearchSchema.model_validate(data)


async def load_sql_param_catalog(sql_tool: SqlTool | None = None) -> SqlParamCatalog:
    if sql_tool is None:
        return SqlParamCatalog.bootstrap()
    try:
        return await sql_tool.fetch_sql_param_catalog()
    except Exception:
        return SqlParamCatalog.bootstrap()
