# agent/analyzer.py
from .utils.logger import logger, LogColor
import json
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Tuple


class AnalysisResult(BaseModel):
    is_complete: bool = Field(
        ..., description="工具召回的数据是否已经足够完整地回答用户的问题"
    )
    reason: str = Field(..., description="对数据完备性的简要诊断分析")
    feedback: str = Field(
        ...,
        description="如果未完成，请给出具体的、能够指导 Planner 修正方向的反思指令；若已完成则为空字符串",
    )


class PlanAnalyzer:
    def __init__(self, client):
        self.client = client

    async def evaluate(
        self, user_input: str, tool_results: List[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        """
        质检引擎：判断当前多模态工具返回的混合结果，能否完美闭环回答用户
        """
        logger.info(f"{LogColor.ANALYZER}[Analyzer] 🕵️‍♂️ 启动数据完备性多维质检...{LogColor.RESET}")
        # 1. 极速工程硬核检查（对齐性能要求）：如果用户有推荐动作意图，但 SQL 查出来是一个空列表
        has_sql_data = any(
            r.get("type") == "sql"
            and isinstance(r.get("data"), list)
            and len(r["data"]) > 0
            for r in tool_results
        )

        # 判定特征关键词
        if any(
            kw in user_input for kw in ["练", "推荐", "动作", "深蹲", "卧推", "计划"]
        ):
            if not has_sql_data:
                # 触发反思回滚，直接提示 Planner
                logger.warning(f"{LogColor.ANALYZER}[Analyzer] ❌ 规则拦截：检测到核心动作资产查空！准备触发回滚。{LogColor.RESET}")
                return (
                    False,
                    "【SQL拦截反馈】：未能检索到任何标准动作资产。原因可能是你的 SQL 筛选属性（如难易度、器械、目标肌肉）映射过严或条件冲突。建议下一轮扩大参数门槛、移除不确定参数或增加 RAG 知识检索来扩充信息量。",
                )

        # 2. 智能化内容分析：抽取工具返回信息的骨架，交给轻量模型进行语义完备度审查
        simplified_logs = []
        for r in tool_results:
            log_item = {"type": r.get("type")}
            if r.get("type") == "sql" and r.get("data"):
                log_item["extracted_names"] = [item.name_zh for item in r["data"]]
            else:
                log_item["content_snippet"] = str(r.get("data", r.get("error", "")))[
                    :150
                ]
            simplified_logs.append(log_item)

        analyzer_prompt = f"""你是一名严谨的 AI 健身系统【数据反思质检员】。
            用户的真实输入是: "{user_input}"
            当前系统通过执行 Planner 编排的工具，收集到的数据快照如下:
            {json.dumps(simplified_logs, ensure_ascii=False)}

            请评估：当前数据对于回答用户的问题而言是否足够全面、精准？
            是否存在答非所问、工具调用缺失（例如用户问怎么做但未触发 RAG）或数据全部为空的情况？
            如果不够，请将其标记为 False，并给出如何调整工具调用的‘反思修正指令’。

            你必须严格输出 JSON 结构，不允许带有任何额外的解释文本。
            """

        try:
            # 使用较小且快速的模型做结构化反思，控制模型成本和延迟
            response = self.client.beta.chat.completions.parse(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": analyzer_prompt}],
                response_format=AnalysisResult,
            )
            analysis: AnalysisResult = response.choices[0].message.parsed
            
            logger.info(f"{LogColor.ANALYZER}[Analyzer] 诊断结论: 是否完备={analysis.is_complete} | 原因: {analysis.reason}{LogColor.RESET}")
            if not analysis.is_complete:
                logger.info(f"{LogColor.ANALYZER}[Analyzer] 💡 产出反思指令: {analysis.feedback}{LogColor.RESET}")
            return analysis.is_complete, analysis.feedback
        except Exception as e:
            print(f"Analyzer 异常兜底放行: {e}")
            return True, ""
