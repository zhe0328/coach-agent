from app.eval.ragas_eval import run_ragas_eval


def test_rag_tool_retrieval_performance():
    """Delegate to the shared Ragas harness runner used by `app.eval.harness`."""
    result = run_ragas_eval()
    assert result.passed, result.summary()
