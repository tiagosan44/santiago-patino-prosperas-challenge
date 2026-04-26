"""Unit tests for the jobs service."""
import pytest

from app.models.job import JobStatus, JobPriority
from app.services import jobs as jobs_svc


# ---- create ----

def test_create_job_persists_with_pending_status_and_version_1(jobs_table):
    job = jobs_svc.create_job(
        jobs_table,
        user_id="u-123",
        report_type="sales",
        priority=JobPriority.STANDARD,
        params={"date_range": "2026-01-01..2026-04-26", "format": "json"},
    )
    assert job.job_id  # non-empty UUID
    assert "-" in job.job_id
    assert job.user_id == "u-123"
    assert job.status == JobStatus.PENDING
    assert job.version == 1
    assert job.report_type == "sales"
    assert job.priority == JobPriority.STANDARD
    assert job.params == {"date_range": "2026-01-01..2026-04-26", "format": "json"}
    assert job.created_at  # ISO 8601
    assert job.updated_at == job.created_at  # same on first write
    assert job.attempts == 0


def test_create_job_persists_to_table(jobs_table):
    job = jobs_svc.create_job(
        jobs_table, user_id="u-1", report_type="sales", priority=JobPriority.HIGH, params={}
    )
    item = jobs_table.get_item(Key={"job_id": job.job_id}).get("Item")
    assert item is not None
    assert item["status"] == "PENDING"
    assert int(item["version"]) == 1


# ---- get ----

def test_get_job_returns_existing(jobs_table):
    created = jobs_svc.create_job(
        jobs_table, user_id="u-1", report_type="sales", priority=JobPriority.STANDARD, params={}
    )
    found = jobs_svc.get_job(jobs_table, created.job_id)
    assert found is not None
    assert found.job_id == created.job_id


def test_get_job_returns_none_for_missing(jobs_table):
    assert jobs_svc.get_job(jobs_table, "nonexistent-id") is None


# ---- list ----

def test_list_jobs_by_user_returns_only_owner_jobs(jobs_table):
    a = jobs_svc.create_job(
        jobs_table, user_id="u-A", report_type="sales", priority=JobPriority.STANDARD, params={}
    )
    jobs_svc.create_job(
        jobs_table, user_id="u-B", report_type="audit", priority=JobPriority.HIGH, params={}
    )
    page = jobs_svc.list_jobs_by_user(jobs_table, user_id="u-A", limit=10)
    assert len(page.items) == 1
    assert page.items[0].job_id == a.job_id
    assert page.next_cursor is None


def test_list_jobs_returns_descending_by_created_at(jobs_table):
    # Create three jobs; the GSI is sorted by created_at, so newest should
    # come first when ScanIndexForward=False
    j1 = jobs_svc.create_job(jobs_table, "u-A", "sales", JobPriority.STANDARD, {})
    j2 = jobs_svc.create_job(jobs_table, "u-A", "sales", JobPriority.STANDARD, {})
    j3 = jobs_svc.create_job(jobs_table, "u-A", "sales", JobPriority.STANDARD, {})

    page = jobs_svc.list_jobs_by_user(jobs_table, user_id="u-A", limit=10)
    ids = [j.job_id for j in page.items]
    # Newest first (j3, j2, j1)
    assert ids == [j3.job_id, j2.job_id, j1.job_id]


def test_list_jobs_paginates_with_cursor(jobs_table):
    for _ in range(5):
        jobs_svc.create_job(jobs_table, "u-A", "sales", JobPriority.STANDARD, {})

    first = jobs_svc.list_jobs_by_user(jobs_table, user_id="u-A", limit=2)
    assert len(first.items) == 2
    assert first.next_cursor is not None  # base64 string

    second = jobs_svc.list_jobs_by_user(jobs_table, user_id="u-A", limit=2, cursor=first.next_cursor)
    assert len(second.items) == 2
    assert second.next_cursor is not None

    third = jobs_svc.list_jobs_by_user(jobs_table, user_id="u-A", limit=2, cursor=second.next_cursor)
    assert len(third.items) == 1
    assert third.next_cursor is None


# ---- update with optimistic locking ----

def test_update_job_status_increments_version(jobs_table):
    job = jobs_svc.create_job(jobs_table, "u-A", "sales", JobPriority.STANDARD, {})
    updated = jobs_svc.update_job_status(
        jobs_table, job_id=job.job_id, expected_version=1,
        status=JobStatus.PROCESSING,
    )
    assert updated.status == JobStatus.PROCESSING
    assert updated.version == 2
    assert updated.updated_at >= job.updated_at


def test_update_job_status_rejects_stale_version(jobs_table):
    job = jobs_svc.create_job(jobs_table, "u-A", "sales", JobPriority.STANDARD, {})
    # First update succeeds (version 1 -> 2)
    jobs_svc.update_job_status(
        jobs_table, job_id=job.job_id, expected_version=1, status=JobStatus.PROCESSING
    )
    # Second update with the now-stale version 1 must raise
    with pytest.raises(jobs_svc.OptimisticLockError):
        jobs_svc.update_job_status(
            jobs_table, job_id=job.job_id, expected_version=1, status=JobStatus.COMPLETED
        )


def test_update_job_status_to_completed_sets_result_url(jobs_table):
    job = jobs_svc.create_job(jobs_table, "u-A", "sales", JobPriority.STANDARD, {})
    updated = jobs_svc.update_job_status(
        jobs_table, job_id=job.job_id, expected_version=1,
        status=JobStatus.COMPLETED, result_url="reports/u-A/abc/result.json",
    )
    assert updated.status == JobStatus.COMPLETED
    assert updated.result_url == "reports/u-A/abc/result.json"
    assert updated.version == 2


def test_update_job_status_to_failed_sets_error(jobs_table):
    job = jobs_svc.create_job(jobs_table, "u-A", "sales", JobPriority.STANDARD, {})
    updated = jobs_svc.update_job_status(
        jobs_table, job_id=job.job_id, expected_version=1,
        status=JobStatus.FAILED, error="downstream timeout",
    )
    assert updated.status == JobStatus.FAILED
    assert updated.error == "downstream timeout"


def test_update_job_increments_attempts(jobs_table):
    job = jobs_svc.create_job(jobs_table, "u-A", "sales", JobPriority.STANDARD, {})
    updated = jobs_svc.update_job_status(
        jobs_table, job_id=job.job_id, expected_version=1,
        status=JobStatus.PROCESSING, increment_attempts=True,
    )
    assert updated.attempts == 1
