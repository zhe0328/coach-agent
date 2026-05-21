from openai import OpenAI
from ..prompts.skill_guide import SYNTHESIZER_SKILL, COACH_PERSONA
from ...config import settings
from ...models.schema import CoachResponse, ExerciseBase, MacroPlanSchema, ToolTask

class CoachSynthesizer:
    def __init__(self, client, skill_guide):
        self.client = client
        self.model = settings.LLM_MODEL_NAME
        self.skill_guide = skill_guide

    def _generate_prompts(self, user_input: str, macro_plan: MacroPlanSchema, executed_tasks: list):
        """
        流式话术合成官：【终极对齐版】
        通过完全结构化的任务切片与子原因，强行让大模型拥有 100% 绝对安全的场景辨识指纹！
        """
        xml_context_parts = []
        
        # 1. 遍历上游执行完毕、且通过了 Analyzer 质检的具名多任务报告
        print("total tasks in synthesizer: ", len(executed_tasks))
        for task in executed_tasks:
            t_id = task.get("task_id")
            t_name = task.get("tool_name")
            t_reason = task.get("reason")          # 👈 大指挥官为该任务下的特定密令
            f_query = task.get("focused_query")    # 👈 大指挥官裁剪好的纯净提问切片
            raw_data = task.get("data", [])
            
            if t_name == "sql_tool":
                exe_xml_blocks = []
                for exe in raw_data:
                    print("sql exe: ", exe, type(exe))
                    if isinstance(exe, ExerciseBase): # 已经完成二级回填的满血字典
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
                # 区分 RAG 的动作百科和文献
                rag_details = []
                for item in raw_data:
                    if getattr(item, "data_type", "exercise") == "exercise":
                        rag_details.append(f"动作要领: {item.description_zh} | 步骤: {'/'.join(item.instructions_zh)}")
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

            # 2. 动态读取并拼接你在 skill_guide.py 里的 COACH_PERSONA 和 PROGRAMMING_LOGIC
            # 此时，SYNTHESIZER_SYSTEM_TEMPLATE 里的 {context_data} 会被无缝替换为干净的多任务 XML 资产包
            final_system_prompt = SYNTHESIZER_SKILL.format(
                context_data="\n\n".join(xml_context_parts)
            )
            
            # 3. 构造极度纯净的 User Prompt，不再给大模型留任何脑补和分心的空间
            final_user_prompt = (
                f"【核心约束：用户的最原始发问与主观要求（包含数量、强度、偏好等核心指标）】:\n"
                f"\" {user_input} \"\n\n" 
                f"【宏观决策链逻辑总纲】:\n\"{macro_plan.routing_reason}\"\n\n"
                f"请严格基于上述被 XML 隔离的多任务高密度资产包，践行你的教练人格，"
                f"为用户产出一份因果逻辑严密、执教口令清晰、且绝对规避伤病风险的流式金牌训练指导："
            )

        return final_system_prompt, final_user_prompt


    async def generate_response(self, user_input: str, macro_plan: MacroPlanSchema, executed_tasks: list):
        """
        结合多路检索结果与 SKILL.md 生成专业回复
        """

        if executed_tasks and len(executed_tasks) > 0:
            final_system_prompt, final_user_prompt = self._generate_prompts(user_input, macro_plan, executed_tasks)

        else: 
            final_system_prompt = COACH_PERSONA
            final_user_prompt = user_input

        response = self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": final_system_prompt},
                {"role": "user", "content": final_user_prompt}
            ],
            temperature=0.7, # 保持一定的教练亲和力
            response_format=CoachResponse
        )
        
        parsed_object: CoachResponse = response.choices[0].message.parsed

        return parsed_object