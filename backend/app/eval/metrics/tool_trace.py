"""Expected vs actual planner tool topology checks."""

from __future__ import annotations

from dataclasses import dataclass

ALLOWED_TOOLS = frozenset({"sql_tool", "rag_tool", "graph_tool"})


@dataclass(frozen=True)
class ToolTraceResult:
    expected_tools: list[str]
    actual_tools: list[str]
    missing_tools: list[str]
    extra_tools: list[str]
    passed: bool

    @property
    def accuracy(self) -> float:
        if not self.expected_tools:
            return 1.0
        expected = set(self.expected_tools)
        matched = expected.intersection(self.actual_tools)
        return len(matched) / len(expected)


def normalize_tools(tools: list[str] | None) -> list[str]:
    if not tools:
        return []
    normalized: list[str] = []
    for tool in tools:
        name = str(tool).strip()
        if not name:
            continue
        if name not in ALLOWED_TOOLS:
            raise ValueError(f"Unknown tool name in trace: {name}")
        if name not in normalized:
            normalized.append(name)
    return normalized


def check_tool_trace(
    expected_tools: list[str] | None,
    actual_tools: list[str] | None,
) -> ToolTraceResult:
    expected = normalize_tools(expected_tools)
    actual = normalize_tools(actual_tools)

    if not expected:
        return ToolTraceResult(
            expected_tools=expected,
            actual_tools=actual,
            missing_tools=[],
            extra_tools=[],
            passed=True,
        )

    expected_set = set(expected)
    actual_set = set(actual)
    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)

    return ToolTraceResult(
        expected_tools=expected,
        actual_tools=actual,
        missing_tools=missing,
        extra_tools=extra,
        passed=not missing and not extra,
    )
