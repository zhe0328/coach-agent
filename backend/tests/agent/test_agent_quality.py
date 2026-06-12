import pytest
import deepeval

from app.eval.deepeval_eval import (
    append_pytest_record,
    evaluate_agent_golden,
    flush_pytest_records,
    load_agent_dataset,
)

pytestmark = pytest.mark.asyncio(loop_scope="function")


@pytest.mark.parametrize("test_data", load_agent_dataset())
async def test_agent_trajectory_performance(test_data):
    record = await evaluate_agent_golden(test_data)
    append_pytest_record(record)
    assert record.passed, record.to_report_row()


@deepeval.on_test_run_end
def after_test_run():
    output_path = flush_pytest_records()
    if output_path:
        print(f"\nAgent eval report: {output_path}")
