from ...models.schema import FullPlan

class PlannerAgent:
    def __init__(self, client, skill_guide):
        self.client = client
        self.skill_guide = skill_guide

    async def plan(self, user_input: str) -> FullPlan:
        system_prompt = """你是一个专业的健身训练调度员。你的任务是根据用户的需求，从三个专业工具中选择最合适的组合。

            【核心教练逻辑】
            {self.skill_guide}

            【关键准则：非必要不填充】
            - 只有当用户显式提到了某个属性时，才填充对应的参数。
            - 严禁脑补用户没说的信息。如果用户没提部位，该字段必须保持 null（None）。
            - 严禁将用户提到的“部位”同时填入 name_zh 和 target_zh。

            【字段填充指南】
            - name_zh: 仅当用户提到具体的动作名称（如“卧推”、“深蹲”）时填写。不要把部位填在这里。
            - target_zh/body_part_zh: 只有用户明确说了“练哪里”才填。
            - category_zh: 除非用户明确说“有氧”或“力量”，否则不填。

            【核心分发逻辑 - 按优先级排序】

            1. 优先检查 SQL_tool (结构化筛选):
            - 触发条件：只要用户提到了 目标肌肉、器材名称、难度等级(初/中/高)、动作类别 或 身体部位。
            - 典型词：'三角肌'、'杠铃'、'初学者'、'有氧运动'、'背部'。
            - 动作：必须将这些词映射到 SQL 对应的属性字段中。

            2. 其次检查 graph_tool (生理逻辑推理):
            - 触发条件：涉及动作切换(太难/太易/换一个)、伤病规避(痛/受伤/保护关节)、或寻找协同动作。
            - 动作：如果你识别到关节名称或“进阶/退让”意图，必须调用此工具。

            3. 最后检查 rag_tool (百科知识检索):
            - 触发条件：用户询问“怎么做”、呼吸方式、发力感、动作原理，或者用户的描述极其模糊（如“想让屁股更有型”）。
            - 注意：如果 SQL 已经能找到动作，且用户没问“怎么做”，则无需调用 RAG，除非你需要补充该动作的详细描述。

            【组合策略】
            - 用户搜动作 + 问做法：SQL_tool + rag_tool。
            - 用户有伤病 + 搜动作：graph_tool + SQL_tool。
            - 用户觉得动作难 + 问原理：graph_tool + rag_tool。

            【严格约束】
            - 必须使用中文填充参数。
            - 难度字段必须映射为: beginner, intermediate, advanced。

            【执行范例】
            - 输入: "初学者弹力带练大腿" -> 动作: 仅调用 SQL_tool {equipment_zh: "弹力带", body_part_zh: "大腿", difficulty: "beginner"}
            - 输入: "深蹲腰痛怎么办" -> 动作: 调用 graph_tool {scenario: "injury_avoidance", joint_name: "脊柱"} + RAG_tool {query_text: "深蹲 腰部 保护"}
            - 输入: "波比跳的发力感" -> 动作: 仅调用 RAG_tool {query_text: "波比跳 发力感 呼吸"}
            - 输入: "俯卧撑太难了" -> 动作: 调用 graph_tool {scenario: "regression", exercise_name: "俯卧撑"}

            """

        
        response = self.client.beta.chat.completions.parse(
            model="gpt-4.1", # 涉及复杂规划，建议用强模型
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            response_format=FullPlan
        )
        print(response)
        return response.choices[0].message.parsed
