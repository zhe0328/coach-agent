from app.models.memory import WorkingMemory
from ...models.schema import MacroPlanSchema

class MacroPlannerAgent:
    def __init__(self, client):
        self.client = client

    async def plan(self, user_input: str, history_context: list, semantic_profile: list[dict[str, any]], memory: WorkingMemory) -> MacroPlanSchema:
        semantic_constraints = ""
        if len(semantic_profile) != 0:
            semantic_constraints = (
                f"【来自图数据库（Neo4j）的当前用户长效硬性指标与物理红线】:\n"
                f"- 用户当前体能级别硬钢印: {semantic_profile[0].get('level', 'beginner')}\n"
                f"- 用户当前【主诉受损/严禁过度负载】的身体关节: {', '.join(semantic_profile[0].get('injuries', [])) if semantic_profile[0].get('injuries') else '全身健康无受损'}\n"
                f"- 用户家里目前【仅拥有且仅能调遣】的常备训练器械库: {', '.join(semantic_profile[0].get('equipment_list', [])) if semantic_profile[0].get('equipment_list') else '自重'}\n\n"
                f"【最高硬核调度约束】：\n"
                f"1. 安全红线：如果受损关节包含'脊柱'（如腰椎突出），本轮如果涉及到下肢或背部训练，你【必须且强制】选装图任务实例（task_graph_injury）去从医学图谱层面严格拉黑并剔除高风险重载动作（如硬拉、杠铃深蹲）！\n"
                f"2. 器械边界：在为工具拆分多任务实例（selected_tools）时，你配置的专属 `focused_query` 和 `reason` 中【必须严格限定器械范围】！如果可用器械库只有'哑铃,弹力带'，你的 `focused_query` 绝对禁止提及'杠铃、单杠'等无中生有的违规设备，防止微观参数提取器发生符号漂移脑补！"
                f"你【必须且强制】将当前用户的体能级别字面量「{semantic_profile[0].get('level', 'beginner')}」作为核心约束词，直接写入 `focused_query` 文本中！\n"
            )

        system_prompt = f"""你是一个专业的健身训练调度员（Macro Planner）。你的唯一任务是审视用户的需求，从三个专业工具中选择最合适的组合，并定义它们的依赖拓扑关系。

            【微观单槽（Single Slot）多实例拆分铁律 —— 违反则下游全盘崩溃】：
            你的下游微观工具（SQL_tool、graph_tool）在参数设计上是【单内聚的】，它们每次【只支持且只允许】接收单个器械或单个关节名称！

            【复合多任务实例拆分铁律】：
            如果用户的输入包含多个不同的动作需求、多处伤病或多重理论疑问，你必须将它们拆解为【多个独立的工具实例】，每个实例赋予唯一的 `task_id`。
            - 例如：输入: "我想用哑铃练胸，还要用弹力带练背，但我肩膀痛。另外卧推和划船怎么排课？"
                -> 动作: 拆解并选装 4 个工具任务节点：
                1. {{ "task_id": "task_sql_chest", "tool_name": "sql_tool", "reason": "筛选哑铃练胸的抗阻动作" }}
                2. {{ "task_id": "task_sql_back", "tool_name": "sql_tool", "reason": "筛选弹力带练背的抗阻动作" }}
                3. {{ "task_id": "task_graph_shoulder", "tool_name": "graph_tool", "reason": "针对肩关节伤病执行运动风险规避与定点动作裁剪", "depends_on": ["task_sql_chest", "task_sql_back"] }}
                4. {{ "task_id": "task_rag_logic", "tool_name": "rag_tool", "rag_intent": "knowledge", "reason": "检索卧推和划船抗阻训练组合与排课的生理学干扰机制" }}
            
            【核心工具分发准则】
            1. SQL_tool (结构化筛选)：只要用户提到了目标肌肉、器材名称、难度等级、动作类别或身体部位时触发。
            2. graph_tool (生理逻辑推理)：涉及动作切换(太难/太易)、伤病规避(痛/受伤/关节不适/关节强化)、或寻找协同动作时触发。
            3. rag_tool (双库检索)：
            - 用户问具体动作“怎么做”、精细发力感 -> 设置 intent="exercise"
            - 用户问动作先后顺序、组合、行不行、生理机制、疲劳原因、训练计划、饮食/营养方案、运动生理学 -> 设置 intent="knowledge"
            - 用户描述模糊、需要综合理论与实操背景 -> 设置 intent="mixed"

            【任务依赖生成指南 (Topological Dependency Rules)】
            - 默认情况下，所有任务都是【并行的】，它们不互相依赖，`depends_on` 应保持为空数组 `[]`。
            - 【关键串行场景】：当且仅当发生“伤病规避”或“动作切换”需要调用 graph_tool，且同时需要针对用户匹配动作调用 sql_tool 时。
            - 逻辑如下：graph_tool 为了避免返回成百上千个无关动作导致上下文冗余，【必须】等待 sql_tool 查出候选动作后进行定点裁剪。
            - 在此场景下：
            1. 为 sql_tool 任务赋予固定的标识：`task_id: "task_sql_base"`
            2. 为 graph_tool 任务赋予标识：`task_id: "task_graph_injury"`
            3. 【强行约束】：必须将 graph_tool 的 `depends_on` 字段声明为 `["task_sql_base"]`。

            【组合策略】
            - 用户搜动作 + 问做法：SQL_tool + rag_tool。
            - 用户有伤病 + 搜动作：graph_tool + SQL_tool。
            - 用户觉得动作难 + 问原理：graph_tool + rag_tool。

            【严格约束】
            - 此时你只需决定触发哪个工具，不需要提取具体的动作细节参数。
            - 如果你分析出用户的提问没有提到任何与运动有关的信息，比如动作名、肌肉群、器械、伤病或任何运动学百科全书查询，请绝对不要选装任何工具。将 routing_mode 锁死为 'chat_only'，并保持 selected_tools 为空数组 []。
            """

        messages = [{"role": "system", "content": system_prompt}]

        if history_context:
            messages.extend(history_context)

        user_content = f"{semantic_constraints}【当前用户的最新发问】：\n\"{user_input}\"\n"

        if memory.latest_analyzer_feedback:
            user_content += (
                f"【自愈复盘报告 —— 你在上一轮由于调度不当被质检官打回了！】\n"
                f"- 质检官的反思修正指令: \"{memory.latest_analyzer_feedback}\"\n"
            )

        messages.append({"role": "user", "content": user_content})
        
        response = self.client.beta.chat.completions.parse(
            model="gpt-4o", # 涉及复杂规划，建议用强模型
            messages=messages,
            response_format=MacroPlanSchema
        )
        return response.choices[0].message.parsed
