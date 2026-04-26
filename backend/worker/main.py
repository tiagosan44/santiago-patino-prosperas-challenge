"""Async worker entrypoint.

Spawns N concurrent tasks (default 4) that each loop over:
  1. Poll SQS (high-priority first, then standard).
  2. Run handle_message for any message received.
  3. Delete the message from SQS if handle_message returned True.

Concurrency is achieved via asyncio.gather + asyncio.to_thread:
- asyncio.gather coordinates the N tasks.
- asyncio.to_thread delegates the blocking boto3 calls to a thread
  pool. Since boto3 releases the GIL during network I/O, threads
  scale fine for a handful of workers.

Why not aioboto3: it would require migrating the entire consumer and
service layer to async. The throughput gain at our scale (single-digit
workers per container) does not justify the refactor. If the system
needs to handle thousands of msgs/s per container we would revisit.

Graceful shutdown: SIGTERM and SIGINT set a stop_event that the loops
check every iteration. ECS sends SIGTERM during deploys, giving the
worker up to 30 seconds to finish in-flight messages before it is
killed.
"""
import asyncio
import logging
import signal
import sys

from app.core import aws as aws_factories
from app.core.config import get_settings
from . import consumer

logger = logging.getLogger(__name__)


# Indirection for tests (lets us patch without monkeypatching boto3 directly).
def _high_queue_url() -> str:
    return get_settings().sqs_high_queue_url


def _standard_queue_url() -> str:
    return get_settings().sqs_standard_queue_url


async def run_one_worker(
    *,
    worker_id: int,
    sqs,
    jobs_table,
    s3,
    redis_client,
    bucket: str,
    stop_event: asyncio.Event,
    idle_sleep: float = 0.5,
) -> None:
    """One concurrent worker task. Polls and processes until stop_event is set."""
    logger.info("worker %d starting", worker_id)
    while not stop_event.is_set():
        try:
            message = await asyncio.to_thread(consumer.poll_next_message, sqs)
        except Exception:  # noqa: BLE001
            logger.exception("worker %d poll error, backing off", worker_id)
            await asyncio.sleep(idle_sleep)
            continue

        if message is None:
            # No message — small async sleep to avoid a tight loop when
            # both queues are empty and long-polling returns instantly.
            await asyncio.sleep(idle_sleep)
            continue

        try:
            should_ack = await asyncio.to_thread(
                consumer.handle_message,
                message,
                jobs_table=jobs_table,
                s3=s3,
                redis_client=redis_client,
                bucket=bucket,
            )
        except Exception:  # noqa: BLE001
            logger.exception("worker %d handle_message crashed", worker_id)
            should_ack = False

        if should_ack:
            # Determine which queue this came from. The body has
            # report_type, but we only know the queue from where we
            # polled. Simplest: try high first; if the receipt is
            # invalid SQS will return InvalidParameterValue silently
            # in our tests (moto). For real SQS, both deletes are
            # cheap; the wrong one fails harmlessly.
            queue_url = (
                _high_queue_url()
                if _is_high_priority(message)
                else _standard_queue_url()
            )
            try:
                await asyncio.to_thread(
                    sqs.delete_message,
                    QueueUrl=queue_url,
                    ReceiptHandle=message["ReceiptHandle"],
                )
            except Exception:  # noqa: BLE001
                logger.exception("worker %d delete_message failed", worker_id)
    logger.info("worker %d stopped", worker_id)


def _is_high_priority(message: dict) -> bool:
    """Decide which queue to delete from based on message body.

    The publisher records the priority via report_type indirectly. We
    inspect the body and use the same routing rule as the producer.
    """
    import json
    try:
        body = json.loads(message["Body"])
    except (json.JSONDecodeError, KeyError):
        return False
    from app.services.queue import HIGH_PRIORITY_REPORT_TYPES
    return body.get("report_type") in HIGH_PRIORITY_REPORT_TYPES


async def run_workers(
    *,
    concurrency: int,
    sqs,
    jobs_table,
    s3,
    redis_client,
    bucket: str,
    stop_event: asyncio.Event,
) -> None:
    """Spawn `concurrency` workers and wait until all complete."""
    tasks = [
        asyncio.create_task(
            run_one_worker(
                worker_id=i,
                sqs=sqs,
                jobs_table=jobs_table,
                s3=s3,
                redis_client=redis_client,
                bucket=bucket,
                stop_event=stop_event,
            )
        )
        for i in range(concurrency)
    ]
    await asyncio.gather(*tasks)


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_event_loop()

    def _signal():
        logger.info("shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal)
        except NotImplementedError:
            # Windows or restricted environments; fall back to default
            pass


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    logger.info(
        "worker booting (concurrency=%d, region=%s, endpoint=%s)",
        settings.worker_concurrency,
        settings.aws_region,
        settings.aws_endpoint_url,
    )

    from app.services import realtime
    redis_client = realtime.get_redis_client()

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    await run_workers(
        concurrency=settings.worker_concurrency,
        sqs=aws_factories.sqs_client(),
        jobs_table=aws_factories.jobs_table(),
        s3=aws_factories.s3_client(),
        redis_client=redis_client,
        bucket=settings.s3_reports_bucket,
        stop_event=stop_event,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
