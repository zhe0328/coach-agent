import asyncio
import re
from typing import Any

from app.agent.utils.logger import LogColor, logger
from app.models.memory import InjurySnifferSchema
from app.tools.sql_tool import SQLTool


class MemoryConsolidator:
    def __init__(self, graph_tool, sql_tool: SQLTool, client):
        self.graph_tool = graph_tool
        self.sql_tool = sql_tool
        self.client = client
        self.model = "gpt-4o-mini"

    def _parse_csv_field(self, raw: str | None) -> list[str]:
        if not raw or not str(raw).strip():
            return []
        return [part.strip() for part in re.split(r"[,，]", str(raw)) if part.strip()]

    def _format_csv_field(self, items: list[str], default: str | None = None) -> str | None:
        cleaned = [item.strip() for item in items if item and item.strip()]
        if not cleaned:
            return default
        return ",".join(cleaned)

    async def _load_profile(
        self,
        user_id: int,
        semantic_profile: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        mysql_row = await self.sql_tool.get_user_semantic_raw(user_id)
        neo = self._normalize_neo4j_profile(semantic_profile)

        if mysql_row:
            injuries = self._parse_csv_field(mysql_row.get("injury_joints_raw"))
            equipment = self._parse_csv_field(
                mysql_row.get("available_equipments_raw")
            ) or ["自重"]
            level = mysql_row.get("fitness_level") or neo["level"]
        else:
            injuries = neo["injuries"]
            equipment = neo["equipment_list"] or ["自重"]
            level = neo["level"]

        return {
            "level": level,
            "injuries": injuries,
            "equipment_list": equipment,
        }

    def _normalize_neo4j_profile(
        self, semantic_profile: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        if not semantic_profile:
            return {"level": "beginner", "injuries": [], "equipment_list": []}

        row = semantic_profile[0]
        injuries = [j for j in row.get("injuries") or [] if j]
        equipment = [e for e in row.get("equipment_list") or [] if e]
        return {
            "level": row.get("level") or "beginner",
            "injuries": injuries,
            "equipment_list": equipment,
        }

    def _build_profile_context(self, profile: dict[str, Any]) -> str:
        injuries = "、".join(profile["injuries"]) if profile["injuries"] else "无"
        equipment = (
            "、".join(profile["equipment_list"])
            if profile["equipment_list"]
            else "自重"
        )
        return (
            f"- 体能级别: {profile['level']}\n"
            f"- 已存储伤病关节: {injuries}\n"
            f"- 已存储可用器械: {equipment}"
        )

    def _filter_new_items(self, candidates: list[str], existing: list[str]) -> list[str]:
        existing_set = set(existing)
        return [item for item in candidates if item and item not in existing_set]

    def _resolve_conflicts(
        self,
        sniff: InjurySnifferSchema,
        profile: dict[str, Any],
    ) -> InjurySnifferSchema:
        if not sniff.conflicts_with_stored_profile:
            sniff.conflict_resolution = "none"
            return sniff

        if sniff.conflict_resolution == "none":
            if sniff.has_injury_resolution or sniff.has_equipment_removal:
                sniff.conflict_resolution = "trust_current_input"
            else:
                sniff.conflict_resolution = "keep_stored_profile"
                logger.warning(
                    f"[Consolidator] 检测到画像矛盾但未明确恢复/移除信号，保留档案: "
                    f"{sniff.conflict_reason}"
                )
        return sniff

    async def _sniff_profile_delta(
        self, user_query: str, profile: dict[str, Any]
    ) -> InjurySnifferSchema | None:
        system_prompt = """你是一个体育科学数据审计员。
            你的任务是对比【已存储用户画像】与【本轮用户原话】，判断语义记忆应如何演进。

            请识别以下四类信号：
            1. 新增伤病或不适关节（has_new_injury / joint）
            2. 伤病恢复或不再受限（has_injury_resolution / resolved_joints）
            3. 新增可用器械（has_new_equipment / equipment_name）
            4. 不再拥有或不再使用的器械（has_equipment_removal / removed_equipment）

            【矛盾处理规则】
            - 若本轮原话与档案冲突（例如档案有膝关节伤，但用户说“膝盖已经不痛了”），设置 conflicts_with_stored_profile=true。
            - 用户明确否定旧限制时，conflict_resolution=trust_current_input，并填写 resolved_joints / removed_equipment。
            - 用户只是忽略档案继续训练、但未明确否定旧限制时，conflict_resolution=keep_stored_profile，不要移除档案项。
            - 关节名称必须严格使用：脊柱、肩关节、膝关节、踝关节、腕关节、肘关节、髋关节。
            """

        user_prompt = (
            f"【已存储画像】\n{self._build_profile_context(profile)}\n\n"
            f"【本轮用户原话】\n\"{user_query}\"\n\n"
            "请输出结构化的画像演进判定。"
        )

        response = await asyncio.to_thread(
            self.client.beta.chat.completions.parse,
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=InjurySnifferSchema,
            temperature=0.0,
        )
        return response.choices[0].message.parsed

    async def _sync_mysql_semantic_raw(
        self, user_id: int, profile: dict[str, Any]
    ) -> None:
        injury_raw = self._format_csv_field(profile["injuries"])
        equipment_raw = self._format_csv_field(
            profile["equipment_list"], default="自重"
        )
        await self.sql_tool.update_user_semantic_raw(
            user_id=user_id,
            injury_joints_raw=injury_raw,
            available_equipments_raw=equipment_raw or "自重",
        )
        logger.info(
            f"{LogColor.TOOL}[Consolidator] MySQL 画像已同步 "
            f"(injuries={injury_raw or '无'}, equipments={equipment_raw}){LogColor.RESET}"
        )

    async def consolidate_session_to_graph(
        self,
        user_id: int,
        user_query: str,
        semantic_profile: list[dict[str, Any]] | None = None,
    ):
        """对比已有语义画像，将演进结果双写至 Neo4j 与 MySQL users 表。"""
        profile_changed = False

        try:
            if semantic_profile is None:
                semantic_profile = await self.graph_tool.fetch_user_semantic_memory(
                    user_id
                )

            profile = await self._load_profile(user_id, semantic_profile)
            sniff = await self._sniff_profile_delta(user_query, profile)
            if not sniff:
                return

            sniff = self._resolve_conflicts(sniff, profile)

            if sniff.conflicts_with_stored_profile:
                logger.info(
                    f"{LogColor.TOOL}[Consolidator] 画像矛盾: {sniff.conflict_reason} "
                    f"→ 裁决 {sniff.conflict_resolution}{LogColor.RESET}"
                )

            if sniff.conflict_resolution != "keep_stored_profile":
                if sniff.has_injury_resolution and sniff.resolved_joints:
                    stored_resolved = [
                        j for j in sniff.resolved_joints if j in profile["injuries"]
                    ]
                    if stored_resolved:
                        await self.graph_tool.remove_injuries_from_profile(
                            user_id, stored_resolved
                        )
                        profile["injuries"] = [
                            j for j in profile["injuries"] if j not in stored_resolved
                        ]
                        profile_changed = True

                if sniff.has_equipment_removal and sniff.removed_equipment:
                    stored_removed = [
                        e
                        for e in sniff.removed_equipment
                        if e in profile["equipment_list"]
                    ]
                    if stored_removed:
                        await self.graph_tool.remove_equipment_from_profile(
                            user_id, stored_removed
                        )
                        profile["equipment_list"] = [
                            e
                            for e in profile["equipment_list"]
                            if e not in stored_removed
                        ]
                        if not profile["equipment_list"]:
                            profile["equipment_list"] = ["自重"]
                        profile_changed = True

            if sniff.has_new_injury and sniff.joint:
                new_injuries = self._filter_new_items(sniff.joint, profile["injuries"])
                if new_injuries:
                    await self.graph_tool.append_injury_list_to_profile(
                        user_id, new_injuries
                    )
                    profile["injuries"].extend(new_injuries)
                    profile_changed = True

            if sniff.has_new_equipment and sniff.equipment_name:
                new_equipment = self._filter_new_items(
                    sniff.equipment_name, profile["equipment_list"]
                )
                if new_equipment:
                    await self.graph_tool.append_equipment_list_to_profile(
                        user_id, new_equipment
                    )
                    profile["equipment_list"].extend(new_equipment)
                    profile_changed = True

            if profile_changed:
                await self._sync_mysql_semantic_raw(user_id, profile)

            logger.info(
                f"{LogColor.TOOL}[Consolidator] 语义画像演进完成 "
                f"(user_id={user_id}, changed={profile_changed}){LogColor.RESET}"
            )

        except Exception as e:
            logger.error(f"[Consolidator] 后台长效语义记忆异步演进断裂: {e}")
