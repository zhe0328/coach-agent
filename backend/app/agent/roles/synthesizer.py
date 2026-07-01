from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel, Field

from ..prompts.skill_guide import COACH_PERSONA, STREAM_GUIDANCE_SKILL, SYNTHESIZER_SKILL
from ..utils.logger import logger
from ...config import settings
from ...models.schema import CoachResponse, ExerciseBase, MacroPlanSchema

_ENRICH_MODEL = "gpt-4o-mini"
_MAX_REFERENCES = 24


class CoachEnrichMetadata(BaseModel):
    """Phase B — short copy fields only; exercises/references are deterministic."""

    greeting: str = Field(..., description="≤40 字开场")
    summary: str = Field(..., description="2–3 句总结，不复述全文")
    safety_alerts: list[str] = Field(default_factory=list)


class CoachSynthesizer:
    def __init__(self, client, skill_guide):
        self.client = client
        self.model = settings.LLM_MODEL_NAME
        self.skill_guide = skill_guide

    def _build_xml_context(self, executed_tasks: list) -> str:
        xml_context_parts: list[str] = []

        for task in executed_tasks:
            t_id = task.get("task_id")
            t_name = task.get("tool_name")
            t_reason = task.get("reason")
            f_query = task.get("focused_query")
            raw_data = task.get("data", [])

            if t_name == "sql_tool":
                exe_xml_blocks = []
                for exe in raw_data:
                    if isinstance(exe, ExerciseBase):
                        exe_xml_blocks.append(
                            f"  - 动作实体 [ACTION_ID: {exe.id}]\n"
                            f"    名称: {exe.name_zh}\n"
                            f"    目标肌肉: {exe.target_zh}\n"
                            f"    所需器械: {exe.equipment_zh}\n"
                            f"    难度: {exe.difficulty}\n"
                        )
                xml_context_parts.append(
                    f"<已核准安全动作资产 task_id='{t_id}'>\n"
                    f"  [此任务专属核心诉求]: {f_query}\n"
                    f"  [指挥官编排原因]: {t_reason}\n"
                    f"  [官方百科严密定义的动作属性库]:\n"
                    + "\n".join(exe_xml_blocks)
                    + "\n"
                    f"</已核准安全动作资产>"
                )

            elif t_name == "rag_tool":
                rag_details = []
                for item in raw_data:
                    if getattr(item, "data_type", "exercise") == "exercise":
                        rag_details.append(
                            f"动作要领: {item.description_zh} | "
                            f"步骤: {'/'.join(item.instructions_zh)}"
                        )
                    else:
                        rag_details.append(f"文献机制: {item.content}")

                xml_context_parts.append(
                    f"<外部权威科学文献背景 task_id='{t_id}'>\n"
                    f"  [此任务专属核心诉求]: {f_query}\n"
                    f"  [知识检索原因]: {t_reason}\n"
                    f"  [召回干货支持]: {' || '.join(rag_details)}\n"
                    f"</外部权威科学文献背景>"
                )

            elif t_name == "graph_tool":
                xml_context_parts.append(
                    f"<生理力学安全拦截与进退阶路径 task_id='{t_id}'>\n"
                    f"  [此任务专属伤病诉求]: {f_query}\n"
                    f"  [图谱推理原因]: {t_reason}\n"
                    f"  [安全防线建立数据]: {str(raw_data)}\n"
                    f"</生理力学安全拦截与进退阶路径>"
                )

        return "\n\n".join(xml_context_parts)

    def _generate_structured_prompts(
        self, user_input: str, macro_plan: MacroPlanSchema, executed_tasks: list
    ) -> tuple[str, str]:
        context_data = self._build_xml_context(executed_tasks)
        final_system_prompt = SYNTHESIZER_SKILL.format(context_data=context_data)

        selected_tools_literal = [
            intent.tool_name for intent in macro_plan.selected_tools
        ]
        final_user_prompt = (
            f"【核心约束：用户的最原始发问与主观要求（包含数量、强度、偏好等核心指标）】:\n"
            f"\" {user_input} \"\n\n"
            f"【宏观决策链逻辑总纲】:\n\"{macro_plan.routing_reason}\"\n\n"
            f"请严格基于上述被 XML 隔离的多任务高密度资产包，践行你的教练人格，"
            f"为用户产出一份因果逻辑严密、执教口令清晰、且绝对规避伤病风险的金牌训练指导!\n\n"
            f"【Deepeval账硬核死命令1】：\n"
            f"你最终输出的 JSON 对象中有一个 `references` 数组。请你睁大眼睛，"
            f"把你上面看到的、本次用来推演计划所【真正参考过的 XML 标签里的生文本或动作步骤】的原文字符串，"
            f"一字不差、完完整整地提取并添加进 `references` 数组列表中！"
            f"【Deepeval账硬核死命令2】\n"
            f"你最终输出的 JSON 对象中有一个 `selected_tools` 数组。"
            f"请你睁大眼睛，把{selected_tools_literal}注入selected_tools!"
        )
        return final_system_prompt, final_user_prompt

    def _generate_stream_prompts(
        self, user_input: str, macro_plan: MacroPlanSchema, executed_tasks: list
    ) -> tuple[str, str]:
        if not executed_tasks:
            return COACH_PERSONA, user_input

        context_data = self._build_xml_context(executed_tasks)
        system_prompt = STREAM_GUIDANCE_SKILL.format(context_data=context_data)
        user_prompt = (
            f"【用户原始发问】：\"{user_input}\"\n\n"
            f"【宏观决策依据】：\"{macro_plan.routing_reason}\"\n\n"
            "请基于上方资产包，用 Markdown 写一份专业教练指导（可用小标题、列表、加粗）。\n"
            "直接输出正文，不要 JSON、不要 XML 标签、不要字段名。\n"
            "开头 1–2 句鼓励性开场；涉及伤病时在文末提醒就医免责。"
        )
        return system_prompt, user_prompt

    def _unsafe_exercise_ids(self, executed_tasks: list) -> set[str]:
        unsafe: set[str] = set()
        for task in executed_tasks:
            if task.get("tool_name") != "graph_tool":
                continue
            for row in task.get("data") or []:
                if isinstance(row, dict) and row.get("unsafe_exercise_id"):
                    unsafe.add(str(row["unsafe_exercise_id"]))
        return unsafe

    def _sql_limits_by_task(self, macro_plan: MacroPlanSchema) -> dict[str, int]:
        return {
            intent.task_id: intent.limit
            for intent in macro_plan.selected_tools
            if intent.tool_name == "sql_tool"
        }

    def _resolve_exercises(
        self, executed_tasks: list, macro_plan: MacroPlanSchema
    ) -> list[ExerciseBase]:
        unsafe_ids = self._unsafe_exercise_ids(executed_tasks)
        limits_by_task = self._sql_limits_by_task(macro_plan)
        default_limit = 4
        exercises: list[ExerciseBase] = []
        seen: set[str] = set()

        for task in executed_tasks:
            if task.get("tool_name") != "sql_tool":
                continue
            task_limit = limits_by_task.get(task.get("task_id"), default_limit)
            taken = 0
            for item in task.get("data") or []:
                if not isinstance(item, ExerciseBase):
                    continue
                if item.id in unsafe_ids or item.id in seen:
                    continue
                seen.add(item.id)
                exercises.append(item)
                taken += 1
                if taken >= task_limit:
                    break

        return exercises

    def _build_references(self, executed_tasks: list) -> list[str]:
        refs: list[str] = []
        seen: set[str] = set()

        def _add(text: str) -> None:
            stripped = (text or "").strip()
            if not stripped or stripped in seen:
                return
            seen.add(stripped)
            refs.append(stripped[:500])

        for task in executed_tasks:
            t_name = task.get("tool_name")
            for item in task.get("data") or []:
                if isinstance(item, ExerciseBase):
                    if getattr(item, "description_zh", None):
                        _add(item.description_zh)
                    elif item.name_zh:
                        _add(f"{item.name_zh} — 目标: {item.target_zh or '综合'}")
                    if getattr(item, "instructions_zh", None):
                        steps = " / ".join(item.instructions_zh[:4])
                        _add(f"{item.name_zh} 步骤: {steps}")
                elif hasattr(item, "data_type") and getattr(item, "data_type") == "knowledge":
                    _add(item.content)
                elif hasattr(item, "data_type") and getattr(item, "data_type") == "exercise":
                    if getattr(item, "description_zh", None):
                        _add(item.description_zh)
                    steps = getattr(item, "instructions_zh", None) or []
                    if steps:
                        _add(f"{getattr(item, 'name_zh', '')} 步骤: {' / '.join(steps[:4])}")
                elif isinstance(item, dict):
                    unsafe = item.get("unsafe_name")
                    if unsafe:
                        _add(f"图谱安全拦截: 已标记高风险动作 {unsafe}")
                    for repl in item.get("safe_replacements") or []:
                        if isinstance(repl, dict) and repl.get("name_zh"):
                            _add(f"安全平替: {repl['name_zh']}")

        return refs[:_MAX_REFERENCES]

    def _rule_safety_alerts(
        self, executed_tasks: list, user_input: str
    ) -> list[str]:
        alerts: list[str] = []
        unsafe_count = len(self._unsafe_exercise_ids(executed_tasks))
        if unsafe_count:
            alerts.append(
                f"已基于图谱拦截 {unsafe_count} 个对受损关节高负载动作，请优先采用平替方案。"
            )
        if any(p in user_input for p in ("痛", "伤", "不适", "酸")):
            alerts.append("训练中出现刺痛或不适请立即停止，必要时就医。")
        return alerts

    def _fallback_greeting(self, guidance_text: str) -> str:
        stripped = guidance_text.strip()
        if not stripped:
            return "你好，以下是我的训练建议。"
        first_line = stripped.split("\n", 1)[0].strip()
        first_line = re.sub(r"^#+\s*", "", first_line)
        if len(first_line) > 80:
            for sep in ("。", "！", "？", ".", "!", "?"):
                idx = first_line.find(sep)
                if 0 < idx < 80:
                    first_line = first_line[: idx + 1]
                    break
            else:
                first_line = first_line[:77] + "…"
        return first_line or "你好，以下是我的训练建议。"

    def _fallback_summary(self, guidance_text: str) -> str:
        stripped = guidance_text.strip()
        if not stripped:
            return "训练指导已生成。"
        paragraphs = [p.strip() for p in stripped.split("\n\n") if p.strip()]
        if not paragraphs:
            return stripped[:200] + ("…" if len(stripped) > 200 else "")
        tail = paragraphs[-1]
        if len(tail) > 220:
            tail = tail[:217] + "…"
        return tail

    async def _llm_enrich_copy(
        self,
        guidance_text: str,
        user_input: str,
        rule_alerts: list[str],
    ) -> CoachEnrichMetadata | None:
        if not guidance_text.strip():
            return None

        prompt = (
            f"用户问题: \"{user_input}\"\n\n"
            f"教练正文（节选）:\n{guidance_text[:2500]}\n\n"
            "请输出 greeting（≤40字开场）、summary（2–3句总结，不要复制全文）、"
            f"safety_alerts（列表，可沿用或补充: {rule_alerts}）。"
        )

        def _call():
            return self.client.beta.chat.completions.parse(
                model=_ENRICH_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format=CoachEnrichMetadata,
                temperature=0.2,
            )

        try:
            response = await asyncio.to_thread(_call)
            return response.choices[0].message.parsed
        except Exception as exc:
            logger.warning(f"[Synthesizer] enrich LLM fallback: {exc}")
            return None

    async def enrich_metadata(
        self,
        guidance_text: str,
        user_input: str,
        macro_plan: MacroPlanSchema,
        executed_tasks: list,
    ) -> CoachResponse:
        exercises = self._resolve_exercises(executed_tasks, macro_plan)
        selected_tools: list[Literal["sql_tool", "graph_tool", "rag_tool"]] = [
            intent.tool_name for intent in macro_plan.selected_tools
        ]
        references = self._build_references(executed_tasks)
        rule_alerts = self._rule_safety_alerts(executed_tasks, user_input)

        enriched = await self._llm_enrich_copy(guidance_text, user_input, rule_alerts)
        if enriched:
            greeting = enriched.greeting.strip() or self._fallback_greeting(guidance_text)
            summary = enriched.summary.strip() or self._fallback_summary(guidance_text)
            safety_alerts = enriched.safety_alerts or rule_alerts
        else:
            greeting = self._fallback_greeting(guidance_text)
            summary = self._fallback_summary(guidance_text)
            safety_alerts = rule_alerts

        response_type: Literal["recommendation", "knowledge", "safety_warning", "nutrition"]
        if exercises:
            response_type = "recommendation"
        elif safety_alerts:
            response_type = "safety_warning"
        else:
            response_type = "knowledge"

        return CoachResponse(
            response_type=response_type,
            greeting=greeting,
            exercises=exercises or None,
            detailed_guidance=guidance_text,
            safety_alerts=safety_alerts,
            summary=summary,
            references=references,
            selected_tools=selected_tools,
        )

    def build_response_from_guidance(
        self,
        guidance_text: str,
        macro_plan: MacroPlanSchema,
        executed_tasks: list,
    ) -> CoachResponse:
        """Sync fallback — prefer enrich_metadata in async paths."""
        exercises = self._resolve_exercises(executed_tasks, macro_plan)
        selected_tools = [intent.tool_name for intent in macro_plan.selected_tools]
        return CoachResponse(
            response_type="recommendation" if exercises else "knowledge",
            greeting=self._fallback_greeting(guidance_text),
            exercises=exercises or None,
            detailed_guidance=guidance_text,
            safety_alerts=self._rule_safety_alerts(executed_tasks, ""),
            summary=self._fallback_summary(guidance_text),
            references=self._build_references(executed_tasks),
            selected_tools=selected_tools,
        )

    async def stream_guidance(
        self,
        user_input: str,
        macro_plan: MacroPlanSchema,
        executed_tasks: list,
    ) -> AsyncIterator[str]:
        from queue import Queue
        from threading import Thread

        system_prompt, user_prompt = self._generate_stream_prompts(
            user_input, macro_plan, executed_tasks
        )
        chunk_queue: Queue[str | None] = Queue()

        def _producer():
            try:
                stream = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.7,
                    stream=True,
                )
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        chunk_queue.put(delta.content)
            except Exception as exc:
                logger.error(f"[Synthesizer] stream_guidance producer failed: {exc}")
            finally:
                chunk_queue.put(None)

        Thread(target=_producer, daemon=True).start()

        while True:
            piece = await asyncio.to_thread(chunk_queue.get)
            if piece is None:
                break
            yield piece

    async def generate_response(
        self, user_input: str, macro_plan: MacroPlanSchema, executed_tasks: list
    ):
        final_system_prompt, final_user_prompt = self._generate_structured_prompts(
            user_input, macro_plan, executed_tasks
        )

        response = self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": final_system_prompt},
                {"role": "user", "content": final_user_prompt},
            ],
            temperature=0.7,
            response_format=CoachResponse,
        )

        parsed_object: CoachResponse = response.choices[0].message.parsed
        return parsed_object
