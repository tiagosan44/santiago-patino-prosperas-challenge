"""/jobs router (create / get / list)."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..core import aws as aws_factories
from ..core.config import get_settings
from ..models.job import (
    Job, JobCreateRequest, JobPage, JobStatus,
)
from ..services import jobs as jobs_svc
from ..services import queue as queue_svc
from .auth import get_current_user

router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_jobs_table():
    return aws_factories.jobs_table()


def get_sqs_client():
    return aws_factories.sqs_client()


def get_s3_client():
    return aws_factories.s3_client()


class JobResponse(BaseModel):
    job_id: str
    user_id: str
    status: JobStatus
    report_type: str
    priority: str
    result_url: str | None = None
    error: str | None = None
    attempts: int
    created_at: str
    updated_at: str

    @classmethod
    def from_job(cls, job: Job, *, presigned_url: str | None = None) -> "JobResponse":
        return cls(
            job_id=job.job_id,
            user_id=job.user_id,
            status=job.status,
            report_type=job.report_type,
            priority=job.priority.value,
            result_url=presigned_url if presigned_url else None,
            error=job.error,
            attempts=job.attempts,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreateRequest,
    current_user=Depends(get_current_user),
    table=Depends(get_jobs_table),
    sqs=Depends(get_sqs_client),
):
    priority = queue_svc.priority_for_report_type(payload.report_type)
    job = jobs_svc.create_job(
        table,
        user_id=current_user.user_id,
        report_type=payload.report_type,
        priority=priority,
        params={"date_range": payload.date_range, "format": payload.format},
    )
    queue_svc.publish_job(
        sqs,
        job_id=job.job_id,
        user_id=job.user_id,
        report_type=job.report_type,
        priority=priority,
        params=job.params,
    )
    return JobResponse.from_job(job)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    current_user=Depends(get_current_user),
    table=Depends(get_jobs_table),
    s3=Depends(get_s3_client),
):
    job = jobs_svc.get_job(table, job_id)
    if job is None or job.user_id != current_user.user_id:
        # Same response for "not found" and "not yours" — no enumeration
        raise HTTPException(status_code=404, detail="job not found")

    presigned = None
    if job.status == JobStatus.COMPLETED and job.result_url:
        settings = get_settings()
        presigned = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_reports_bucket, "Key": job.result_url},
            ExpiresIn=900,
        )
    return JobResponse.from_job(job, presigned_url=presigned)


@router.get("", response_model=JobPage)
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    current_user=Depends(get_current_user),
    table=Depends(get_jobs_table),
):
    return jobs_svc.list_jobs_by_user(
        table, user_id=current_user.user_id, limit=limit, cursor=cursor
    )
