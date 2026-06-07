from collections.abc import AsyncIterator

from ..prompts.skill_guide import SYNTHESIZER_SKILL, COACH_PERSONA
from ...config import settings
from ...models.schema import CoachResponse, ExerciseBase, MacroPlanSchema


class CoachSynthesizer:
    def __init__(self, client, skill_guide):
        self.client = client
        self.model = settings.LLM_MODEL_NAME
        self.skill_guide = skill_guide

    def _generate_prompts(
        self, user_input: str, macro_plan: MacroPlanSchema, executed_tasks: list
    ):
        xml_context_parts = []

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
                    f"  [官方百科严密定义的动作属性库]:\n" + "\n".join(exe_xml_blocks) + "\n"
                    f"</已核准安全动作资产>"
                )

            elif t_name == "rag_tool":
                rag_details = []
                for item in raw_data:
                    if getattr(item, "data_type", "exercise") == "exercise":
                        rag_details.append(
                            f"动作要领: {item.description_zh} | 步骤: {'/'.join(item.instructions_zh)}"
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

        final_system_prompt = SYNTHESIZER_SKILL.format(
            context_data="\n\n".join(xml_context_parts)
        )

        selected_tools_literal = [
            intent.tool_name for intent in macro_plan.selected_tools
        ]
        final_user_prompt = (
            f"【核心约束：用户的最原始发问与主观要求（包含数量、强度、偏好等核心指标）】:\n"
            f"\" {user_input} \"\n\n"
            f"【宏观决策链逻辑总纲】:\n\"{macro_plan.routing_reason}\"\n\n"
            f"请严格基于上述被 XML 隔离的多任务高密度资产包，践行你的教练人格，"
            f"为用户产出一份因果逻辑严密、执教口令清晰、且绝对规避伤病风险的流式金牌训练指导!\n\n"
            f"【Deepeval账硬核死命令1】：\n"
            f"你最终输出的 JSON 对象中有一个 `references` 数组。请你睁大眼睛，"
            f"把你上面看到的、本次用来推演计划所【真正参考过的 XML 标签里的生文本或动作步骤】的原文字符串，"
            f"一字不差、完完整整地提取并添加进 `references` 数组列表中！这是系统用来执行 Ragas 科学测谎和反幻觉对账的唯一红线！"
            f"【Deepeval账硬核死命令2】\n"
            f"你最终输出的 JSON 对象中有一个 `selected_tools` 数组。请你睁大眼睛，把{selected_tools_literal}注入selected_tools!"
        )

        return final_system_prompt, final_user_prompt

    def _resolve_prompts(
        self, user_input: str, macro_plan: MacroPlanSchema, executed_tasks: list
    ):
        if executed_tasks:
            return self._generate_prompts(user_input, macro_plan, executed_tasks)
        return COACH_PERSONA, user_input

    def _extract_exercises(self, executed_tasks: list) -> list[ExerciseBase]:
        exercises: list[ExerciseBase] = []
        seen: set[str] = set()
        for task in executed_tasks:
            if task.get("tool_name") != "sql_tool":
                continue
            for item in task.get("data", []):
                if isinstance(item, ExerciseBase) and item.id not in seen:
                    seen.add(item.id)
                    exercises.append(item)
        return exercises

    def build_response_from_guidance(
        self,
        guidance_text: str,
        macro_plan: MacroPlanSchema,
        executed_tasks: list,
    ) -> CoachResponse:
        exercises = self._extract_exercises(executed_tasks)
        selected_tools = [intent.tool_name for intent in macro_plan.selected_tools]
        summary = guidance_text.strip()
        if len(summary) > 200:
            summary = summary[:200] + "..."
        return CoachResponse(
            response_type="recommendation" if exercises else "knowledge",
            greeting="",
            exercises=exercises or None,
            detailed_guidance=guidance_text,
            summary=summary or "训练指导已生成",
            selected_tools=selected_tools,
        )

    async def stream_guidance(
        self,
        user_input: str,
        macro_plan: MacroPlanSchema,
        executed_tasks: list,
    ) -> AsyncIterator[str]:
        import asyncio
        from queue import Queue
        from threading import Thread

        system_prompt, user_prompt = self._resolve_prompts(
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
                    delta = chunk.choices[0].delta.content
                    if delta:
                        chunk_queue.put(delta)
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
        final_system_prompt, final_user_prompt = self._resolve_prompts(
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
