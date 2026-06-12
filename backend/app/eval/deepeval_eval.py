"""DeepEval agent trajectory evaluation entry point."""

from __future__ import annotations

import asyncio
import json
import os
import random
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepeval import evaluate
from deepeval.evaluate.configs import AsyncConfig
from deepeval.test_case import LLMTestCase, ToolCall
from openai import OpenAI

from app.agent.orchestrator import CoachOrchestrator
from app.config import settings
from app.eval.metrics.agent_metrics import (
    AgentMetricScores,
    build_agent_metrics,
    check_agent_passed,
)
from app.eval.metrics.tool_trace import ToolTraceResult, check_tool_trace
from app.eval.paths import DEFAULT_AGENT_DATASET, resolve_dataset, resolve_output_dir
from app.eval.reporters.csv_reporter import write_agent_report_csv

_orchestrator: CoachOrchestrator | None = None
_pytest_records: list[dict[str, Any]] = []

# Reserved offline-eval identity — must not overlap prod users.
EVAL_USER_ID = 999_999


def enable_eval_no_persist() -> None:
    """Prevent agent eval from writing MySQL, Redis, or Neo4j."""
    os.environ["COACH_EVAL_NO_PERSIST"] = "1"
    settings.EVAL_NO_PERSIST = True


@dataclass(frozen=True)
class AgentEvalRecord:
    user_input: str
    actual_output: str
    scores: AgentMetricScores
    tool_trace: ToolTraceResult
    passed: bool
    expected_tools: list[str]
    actual_tools: list[str]

    def to_report_row(self) -> dict[str, Any]:
        return {
            "用户输入": self.user_input,
            "Agent实际中文输出": self.actual_output,
            "轨迹审计得分": self.scores.trajectory,
            "轨迹判定理由": self.scores.trajectory_reason,
            "知识忠实得分": self.scores.faithfulness,
            "知识判定理由": self.scores.faithfulness_reason,
            "安全合规得分": self.scores.safety,
            "安全判定理由": self.scores.safety_reason,
            "答案相关得分": self.scores.relevancy,
            "答案相关理由": self.scores.relevancy_reason,
            "期望工具": ",".join(self.expected_tools),
            "实际工具": ",".join(self.actual_tools),
            "缺失工具": ",".join(self.tool_trace.missing_tools),
            "多余工具": ",".join(self.tool_trace.extra_tools),
            "工具拓扑通过": "是" if self.tool_trace.passed else "否",
            "测试状态": "通过" if self.passed else "失败",
        }


@dataclass(frozen=True)
class DeepevalEvalResult:
    case_count: int
    passed_count: int
    mean_trajectory: float
    mean_faithfulness: float
    mean_safety: float
    mean_relevancy: float
    mean_tool_trace_accuracy: float
    tool_trace_pass_count: int
    dataset_path: Path
    output_path: Path | None
    limit: int | None
    passed: bool

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        limit_note = f", limit={self.limit}" if self.limit is not None else ""
        return (
            f"DeepEval agent eval {status}: dataset={self.dataset_path.name}, "
            f"cases={self.case_count}, passed={self.passed_count}{limit_note}, "
            f"trajectory={self.mean_trajectory:.3f}, "
            f"faithfulness={self.mean_faithfulness:.3f}, "
            f"safety={self.mean_safety:.3f}, "
            f"relevancy={self.mean_relevancy:.3f}, "
            f"tool_trace={self.mean_tool_trace_accuracy:.3f}"
        )


def _configure_deepeval_env() -> None:
    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    os.environ["OPENAI_BASE_URL"] = settings.OPENAI_BASE_URL or ""
    os.environ["OPENAI_MODEL_NAME"] = "gpt-4o"


def _get_orchestrator() -> CoachOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _configure_deepeval_env()
        client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
        _orchestrator = CoachOrchestrator(client)
    return _orchestrator


def load_agent_dataset(
    dataset_path: str | Path | None = None,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    env_path = os.environ.get("COACH_EVAL_AGENT_DATASET")
    if dataset_path is not None:
        resolved = resolve_dataset(dataset_path, DEFAULT_AGENT_DATASET)
    elif env_path:
        resolved = Path(env_path)
    else:
        resolved = DEFAULT_AGENT_DATASET

    if not resolved.exists():
        raise FileNotFoundError(f"Agent dataset not found: {resolved}")

    with open(resolved, encoding="utf-8") as handle:
        rows = json.load(handle)

    env_limit = os.environ.get("COACH_EVAL_LIMIT")
    effective_limit = limit
    if effective_limit is None and env_limit:
        effective_limit = int(env_limit)

    if effective_limit is not None:
        rows = rows[:effective_limit]

    if not rows:
        raise ValueError(f"No agent golden rows loaded from {resolved}")

    return rows


def clear_pytest_records() -> None:
    _pytest_records.clear()


def append_pytest_record(record: AgentEvalRecord) -> None:
    _pytest_records.append(record.to_report_row())


def flush_pytest_records(output_dir: str | Path | None = None) -> Path | None:
    if not _pytest_records:
        return None
    return write_agent_report_csv(_pytest_records, output_dir=output_dir)


def _random_session_ids() -> tuple[int, str]:
    session_id = "eval_" + "".join(
        random.choice(string.ascii_letters + string.digits) for _ in range(12)
    )
    return EVAL_USER_ID, session_id


def _scores_from_metrics(metrics) -> AgentMetricScores:
    trajectory_metric, faithfulness_metric, injury_safety_metric, relevancy_metric = metrics
    return AgentMetricScores(
        trajectory=float(trajectory_metric.score or 0.0),
        faithfulness=float(faithfulness_metric.score or 0.0),
        safety=float(injury_safety_metric.score or 0.0),
        relevancy=float(relevancy_metric.score or 0.0),
        trajectory_reason=getattr(trajectory_metric, "reason", "无") or "无",
        faithfulness_reason=getattr(faithfulness_metric, "reason", "无") or "无",
        safety_reason=getattr(injury_safety_metric, "reason", "无") or "无",
        relevancy_reason=getattr(relevancy_metric, "reason", "无") or "无",
    )


async def evaluate_agent_golden(
    test_data: dict[str, Any],
    *,
    orchestrator: CoachOrchestrator | None = None,
) -> AgentEvalRecord:
    enable_eval_no_persist()
    orchestrator = orchestrator or _get_orchestrator()
    user_id, session_id = _random_session_ids()
    user_input = test_data["user_input"]

    agent_result = await orchestrator.execute(user_id, session_id, user_input)

    referenced_context = test_data.get("referenced_context", [])
    expected_output = test_data.get("expected_output", "")
    expected_tools = test_data.get("expected_tools", [])
    actual_tools_list = getattr(agent_result, "selected_tools", []) or []

    deepeval_tools_called = [
        ToolCall(name=str(tool), input_parameters={}, output="已成功返回工具调用列表")
        for tool in actual_tools_list
    ]

    test_case = LLMTestCase(
        input=user_input,
        actual_output=agent_result.detailed_guidance,
        expected_output=expected_output or None,
        retrieval_context=referenced_context,
        tools_called=deepeval_tools_called,
    )

    metrics = build_agent_metrics()
    evaluate(
        test_cases=[test_case],
        metrics=list(metrics),
        async_config=AsyncConfig(max_concurrent=1, run_async=False),
    )

    scores = _scores_from_metrics(metrics)
    tool_trace = check_tool_trace(expected_tools, actual_tools_list)
    passed = check_agent_passed(scores) and tool_trace.passed

    return AgentEvalRecord(
        user_input=user_input,
        actual_output=agent_result.detailed_guidance,
        scores=scores,
        tool_trace=tool_trace,
        passed=passed,
        expected_tools=tool_trace.expected_tools,
        actual_tools=tool_trace.actual_tools,
    )


def _aggregate_results(
    records: list[AgentEvalRecord],
    *,
    dataset_path: Path,
    output_path: Path | None,
    limit: int | None,
) -> DeepevalEvalResult:
    case_count = len(records)
    passed_count = sum(1 for record in records if record.passed)
    tool_trace_pass_count = sum(1 for record in records if record.tool_trace.passed)
    mean_trajectory = sum(record.scores.trajectory for record in records) / case_count
    mean_faithfulness = sum(record.scores.faithfulness for record in records) / case_count
    mean_safety = sum(record.scores.safety for record in records) / case_count
    mean_relevancy = sum(record.scores.relevancy for record in records) / case_count
    mean_tool_trace_accuracy = (
        sum(record.tool_trace.accuracy for record in records) / case_count
    )

    return DeepevalEvalResult(
        case_count=case_count,
        passed_count=passed_count,
        mean_trajectory=mean_trajectory,
        mean_faithfulness=mean_faithfulness,
        mean_safety=mean_safety,
        mean_relevancy=mean_relevancy,
        mean_tool_trace_accuracy=mean_tool_trace_accuracy,
        tool_trace_pass_count=tool_trace_pass_count,
        dataset_path=dataset_path,
        output_path=output_path,
        limit=limit,
        passed=passed_count == case_count,
    )


async def run_deepeval_eval_async(
    *,
    dataset_path: str | Path | None = None,
    limit: int | None = None,
    output_dir: str | Path | None = None,
) -> DeepevalEvalResult:
    enable_eval_no_persist()
    rows = load_agent_dataset(dataset_path, limit=limit)
    orchestrator = _get_orchestrator()

    records: list[AgentEvalRecord] = []
    for row in rows:
        records.append(await evaluate_agent_golden(row, orchestrator=orchestrator))

    output_path = write_agent_report_csv(
        [record.to_report_row() for record in records],
        output_dir=output_dir,
    )

    resolved_dataset = resolve_dataset(
        dataset_path or os.environ.get("COACH_EVAL_AGENT_DATASET"),
        DEFAULT_AGENT_DATASET,
    )
    return _aggregate_results(
        records,
        dataset_path=resolved_dataset,
        output_path=output_path,
        limit=limit,
    )


def run_deepeval_eval(
    *,
    dataset_path: str | Path | None = None,
    limit: int | None = None,
    output_dir: str | Path | None = None,
) -> DeepevalEvalResult:
    return asyncio.run(
        run_deepeval_eval_async(
            dataset_path=dataset_path,
            limit=limit,
            output_dir=output_dir,
        )
    )
