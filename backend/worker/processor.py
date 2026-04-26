"""Worker job processor.

Pure-function-style: given a job message, generate dummy report data,
upload to S3, return the S3 key. The actual sleep is simulated to
emulate realistic processing time (5–30 s) and is patchable for tests.

Design choice: the processor does NOT touch DynamoDB or SQS. Those
side effects live in the consumer (Task 3.2). This separation makes
the processor trivially unit-testable and allows future evolution
(swap simulate_sleep for real work, add new report types) without
reaching into queue handling.
"""
import json
import random
import time
from datetime import UTC, datetime
from typing import Any


class ProcessingError(Exception):
    """Raised by the processor on a recoverable failure.

    The consumer treats this as a signal to use SQS visibility-timeout
    back-off (Task 5.4 / B4) rather than immediately delete the
    message.
    """


# Tunable bounds for simulate_sleep. Module-level so tests can patch.
SLEEP_MIN_SECONDS = 5.0
SLEEP_MAX_SECONDS = 30.0


def simulate_sleep() -> None:
    """Sleep a random duration to emulate variable processing time."""
    duration = random.uniform(SLEEP_MIN_SECONDS, SLEEP_MAX_SECONDS)
    time.sleep(duration)


def generate_dummy_data(*, report_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable dict shaped like a 'real' report.

    Different report types produce different column shapes so the
    frontend can show meaningful previews.
    """
    rng = random.Random(report_type)  # deterministic per report_type for test stability
    rows: list[dict[str, Any]] = []
    if report_type == "sales":
        for i in range(rng.randint(10, 30)):
            rows.append({
                "order_id": f"ord-{i:04d}",
                "amount": round(rng.uniform(10, 5000), 2),
                "currency": rng.choice(["USD", "EUR", "COP"]),
            })
    elif report_type == "inventory":
        for i in range(rng.randint(10, 30)):
            rows.append({
                "sku": f"sku-{i:04d}",
                "qty_on_hand": rng.randint(0, 500),
                "warehouse": rng.choice(["WH-A", "WH-B", "WH-C"]),
            })
    else:
        # generic fallback — still useful for users / executive_summary / audit
        for i in range(rng.randint(5, 15)):
            rows.append({"id": i, "value": rng.random()})

    return {
        "report_type": report_type,
        "params": params,
        "generated_at": datetime.now(UTC).isoformat(),
        "row_count": len(rows),
        "rows": rows,
    }


def process_job(
    *,
    s3,
    bucket: str,
    user_id: str,
    job_id: str,
    report_type: str,
    params: dict[str, Any],
) -> str:
    """Generate dummy data, sleep, upload to S3, return key.

    Test hook: report_type == 'force_failure' raises ProcessingError so
    integration tests and the frontend can exercise the FAILED path.
    """
    simulate_sleep()

    if report_type == "force_failure":
        raise ProcessingError(f"forced failure for job {job_id}")

    data = generate_dummy_data(report_type=report_type, params=params)
    key = f"reports/{user_id}/{job_id}/result.json"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data).encode("utf-8"),
        ContentType="application/json",
    )
    return key
