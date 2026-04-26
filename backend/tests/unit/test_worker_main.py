"""Tests for the async worker main loop.

Uses pytest-asyncio (config in pyproject.toml has `asyncio_mode = auto`).
The test exercises the orchestration layer; the consumer's sync
functions are mocked so we don't actually need LocalStack.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from worker import main as worker_main


@pytest.mark.asyncio
async def test_run_one_task_processes_until_stop_event():
    """One task: poll returns a message, handle returns True, delete is called, loop exits on stop event."""
    fake_message = {"MessageId": "m1", "ReceiptHandle": "rh1", "Body": "{}", "Attributes": {}}
    sqs = MagicMock()
    deletes = []
    sqs.delete_message.side_effect = lambda **kw: deletes.append(kw)

    poll_calls = [fake_message, None, None]  # one message then drain

    def fake_poll(_sqs, **kwargs):
        if poll_calls:
            return poll_calls.pop(0)
        return None

    handle_calls = []

    def fake_handle(message, **kwargs):
        handle_calls.append(message)
        return True

    stop_event = asyncio.Event()

    async def stopper():
        # Let the loop iterate a couple of times, then signal stop
        await asyncio.sleep(0.1)
        stop_event.set()

    with patch("worker.consumer.poll_next_message", side_effect=fake_poll), \
         patch("worker.consumer.handle_message", side_effect=fake_handle), \
         patch.object(worker_main, "_high_queue_url", return_value="http://x/high"), \
         patch.object(worker_main, "_standard_queue_url", return_value="http://x/standard"):
        await asyncio.gather(
            worker_main.run_one_worker(
                worker_id=0,
                sqs=sqs,
                jobs_table=MagicMock(),
                s3=MagicMock(),
                redis_client=MagicMock(),
                bucket="b",
                stop_event=stop_event,
                idle_sleep=0.01,
            ),
            stopper(),
        )

    assert len(handle_calls) == 1
    assert len(deletes) == 1
    assert deletes[0]["QueueUrl"] in ("http://x/high", "http://x/standard")


@pytest.mark.asyncio
async def test_run_one_task_does_not_delete_when_handle_returns_false():
    """If handle_message returns False, the message must NOT be deleted (SQS retries)."""
    fake_message = {"MessageId": "m1", "ReceiptHandle": "rh1", "Body": "{}", "Attributes": {}}
    sqs = MagicMock()

    def fake_poll(_sqs, **kwargs):
        if fake_poll.served:
            return None
        fake_poll.served = True
        return fake_message
    fake_poll.served = False

    stop_event = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.1)
        stop_event.set()

    with patch("worker.consumer.poll_next_message", side_effect=fake_poll), \
         patch("worker.consumer.handle_message", return_value=False), \
         patch.object(worker_main, "_high_queue_url", return_value="http://x/high"), \
         patch.object(worker_main, "_standard_queue_url", return_value="http://x/standard"):
        await asyncio.gather(
            worker_main.run_one_worker(
                worker_id=0,
                sqs=sqs,
                jobs_table=MagicMock(),
                s3=MagicMock(),
                redis_client=MagicMock(),
                bucket="b",
                stop_event=stop_event,
                idle_sleep=0.01,
            ),
            stopper(),
        )

    sqs.delete_message.assert_not_called()


@pytest.mark.asyncio
async def test_run_concurrent_workers_runs_n_tasks():
    """run_workers spawns N concurrent run_one_worker calls."""
    sqs = MagicMock()
    stop_event = asyncio.Event()

    started: list[int] = []

    async def fake_one_worker(*, worker_id, **kwargs):
        started.append(worker_id)
        await stop_event.wait()

    async def stopper():
        await asyncio.sleep(0.05)
        stop_event.set()

    with patch.object(worker_main, "run_one_worker", side_effect=fake_one_worker):
        await asyncio.gather(
            worker_main.run_workers(
                concurrency=4,
                sqs=sqs,
                jobs_table=MagicMock(),
                s3=MagicMock(),
                redis_client=MagicMock(),
                bucket="b",
                stop_event=stop_event,
            ),
            stopper(),
        )

    assert sorted(started) == [0, 1, 2, 3]
