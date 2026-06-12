"""
Ragas retrieval evaluation for the RAG tool.

Used by the eval harness, pytest suite, and future CI gates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

from openai import AsyncOpenAI
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.llms import llm_factory
from ragas.metrics import ContextPrecision, ContextRecall

from app.config import settings
from app.eval.paths import DEFAULT_RAG_DATASET, resolve_dataset, resolve_output_dir
from app.models.schema import ExerciseDetail, KnowledgeChunk, RAGSearchSchema
from app.tools.rag_tool import RAGTool

DEFAULT_RECALL_THRESHOLD = 0.80
DEFAULT_PRECISION_THRESHOLD = 0.70


@dataclass(frozen=True)
class RagasEvalResult:
    case_count: int
    mean_context_recall: float
    mean_context_precision: float
    output_path: Path | None
    passed: bool

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        return (
            f"Ragas eval {status}: n={self.case_count}, "
            f"recall={self.mean_context_recall:.3f}, "
            f"precision={self.mean_context_precision:.3f}"
        )


def format_rag_output(
    rag_results: List[Union[ExerciseDetail, KnowledgeChunk]],
) -> List[str]:
    formatted_contexts: list[str] = []

    for item in rag_results:
        data_type = getattr(item, "data_type", None)

        if data_type == "exercise":
            name = getattr(item, "name_zh", "未知动作")
            body_part = getattr(item, "body_part_zh", "全身")
            target = getattr(item, "target_zh", "核心肌肉群")
            equipment = getattr(item, "equipment_zh", "徒手")
            description = getattr(item, "description_zh", "") or "暂无简介"
            instructions = getattr(item, "instructions_zh", [])
            text_block = (
                f"动作名称：{name}。训练部位：{body_part}。主目标肌群：{target}。"
                f"器材：{equipment}动作简介：{description}。执行步骤规范：{instructions}"
            )
            formatted_contexts.append(text_block)
        elif data_type == "knowledge":
            source_book = getattr(item, "source_book", "专业文献")
            chapter_title = getattr(item, "chapter_title", "基础理论")
            content = getattr(item, "content", "")
            text_block = (
                f"【图书来源】: {source_book} | 【所属章节主题】: {chapter_title}\n"
                f"【核心生理学与执教知识点】:\n{content}"
            )
            formatted_contexts.append(text_block)
        else:
            formatted_contexts.append(str(item))

    return formatted_contexts


def load_rag_dataset(dataset_path: str | Path | None = None) -> list[dict]:
    path = resolve_dataset(dataset_path, DEFAULT_RAG_DATASET)
    if not path.exists():
        raise FileNotFoundError(f"Ragas dataset not found: {path}")

    with open(path, encoding="utf-8") as handle:
        raw_data = json.load(handle)

    cleaned: list[dict] = []
    for idx, item in enumerate(raw_data):
        user_input = item.get("user_input")
        ref_contexts = item.get("reference_contexts")
        if isinstance(ref_contexts, str):
            ref_contexts = [ref_contexts]
        if not user_input or not ref_contexts:
            continue
        cleaned.append(
            {
                "user_input": user_input,
                "reference_contexts": ref_contexts,
                "intent": item.get("intent"),
                "reference": item.get("reference"),
            }
        )

    if not cleaned:
        raise ValueError(f"No valid RAG golden rows in {path}")
    return cleaned


def _build_evaluator_llm():
    client = AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
    )
    return llm_factory(model="gpt-4o", client=client)


async def run_ragas_eval_async(
    *,
    dataset_path: str | Path | None = None,
    limit: int | None = None,
    output_dir: str | Path | None = None,
    recall_threshold: float = DEFAULT_RECALL_THRESHOLD,
    precision_threshold: float = DEFAULT_PRECISION_THRESHOLD,
) -> RagasEvalResult:
    rows = load_rag_dataset(dataset_path)
    if limit is not None:
        rows = rows[:limit]

    rag_tool = RAGTool()
    evaluator_llm = _build_evaluator_llm()
    metrics = [
        ContextRecall(llm=evaluator_llm),
        ContextPrecision(llm=evaluator_llm),
    ]

    samples: list[SingleTurnSample] = []
    for data in rows:
        query = RAGSearchSchema(
            query_text=data["user_input"],
            intent=data.get("intent"),
        )
        actual_contexts = await rag_tool.search_knowledge(query)
        formatted_contexts = format_rag_output(actual_contexts)
        samples.append(
            SingleTurnSample(
                user_input=data["user_input"],
                retrieved_contexts=formatted_contexts,
                reference_contexts=data["reference_contexts"],
                reference=data.get("reference"),
            )
        )

    results = evaluate(
        dataset=EvaluationDataset(samples=samples),
        metrics=metrics,
        raise_exceptions=True,
    )
    df_details = results.to_pandas()

    mean_recall = float(df_details["context_recall"].mean())
    mean_precision = float(df_details["context_precision"].mean())
    passed = mean_recall >= recall_threshold and mean_precision >= precision_threshold

    out_dir = resolve_output_dir(output_dir)
    output_path = out_dir / "rag_eval_latest.csv"
    df_details.to_csv(output_path, index=False)

    return RagasEvalResult(
        case_count=len(rows),
        mean_context_recall=mean_recall,
        mean_context_precision=mean_precision,
        output_path=output_path,
        passed=passed,
    )


def run_ragas_eval(
    *,
    dataset_path: str | Path | None = None,
    limit: int | None = None,
    output_dir: str | Path | None = None,
    recall_threshold: float = DEFAULT_RECALL_THRESHOLD,
    precision_threshold: float = DEFAULT_PRECISION_THRESHOLD,
) -> RagasEvalResult:
    import asyncio

    return asyncio.run(
        run_ragas_eval_async(
            dataset_path=dataset_path,
            limit=limit,
            output_dir=output_dir,
            recall_threshold=recall_threshold,
            precision_threshold=precision_threshold,
        )
    )
