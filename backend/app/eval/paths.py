"""Repository-relative paths for eval datasets and reports."""

from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = BACKEND_ROOT / "tests"
DATASET_DIR = TESTS_ROOT / "dataset"
RESULTS_DIR = TESTS_ROOT / "results"

DEFAULT_RAG_DATASET = DATASET_DIR / "fitness_ground_truth.json"
DEFAULT_AGENT_DATASET = DATASET_DIR / "coach_agent_advanced_goldens.json"

EVAL_ROOT = Path(__file__).resolve().parent
SMOKE_RAG_DATASET = EVAL_ROOT / "datasets" / "smoke" / "rag_smoke.json"
SMOKE_AGENT_DATASET = EVAL_ROOT / "datasets" / "smoke" / "agent_smoke.json"
SMOKE_ROUTING_DATASET = EVAL_ROOT / "datasets" / "smoke" / "routing_smoke.json"

RAG_TEST_FILE = TESTS_ROOT / "tools" / "test_rag_quality.py"
AGENT_TEST_FILE = TESTS_ROOT / "agent" / "test_agent_quality.py"


def dataset(name: str) -> Path:
    return DATASET_DIR / name


def resolve_dataset(path: str | Path | None, default: Path) -> Path:
    if path is None:
        return default
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return BACKEND_ROOT / candidate


def resolve_output_dir(path: str | Path | None) -> Path:
    if path is None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        return RESULTS_DIR
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = BACKEND_ROOT / candidate
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate
