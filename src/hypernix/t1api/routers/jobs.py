from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import AuthContext
from ..deps import get_auth_context, get_job_queue, get_request_id
from ..jobs import JobQueue
from ..schemas import JobCreateRequest, JobDetailResponse, JobItem, JobListResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_item(entry) -> JobItem:
    return JobItem(**entry.to_dict())


@router.post("", response_model=JobDetailResponse)
def create_job(
    body: JobCreateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    queue: JobQueue = Depends(get_job_queue),
    request_id: str = Depends(get_request_id),
) -> JobDetailResponse:
    """Submitting a job with an unregistered ``kind`` raises
    ``NOT_SUPPORTED`` — see ``t1api.jobs``'s module docstring for why that's
    the correct behavior rather than a generic 400/500."""
    job = queue.submit(body.kind, body.payload, created_by=ctx.key_id)
    return JobDetailResponse(job=_to_item(job), request_id=request_id)


@router.get("/{job_id}", response_model=JobDetailResponse)
def get_job(
    job_id: str,
    queue: JobQueue = Depends(get_job_queue),
    request_id: str = Depends(get_request_id),
) -> JobDetailResponse:
    job = queue.require(job_id)
    return JobDetailResponse(job=_to_item(job), request_id=request_id)


@router.post("/{job_id}/cancel", response_model=JobDetailResponse)
def cancel_job(
    job_id: str,
    queue: JobQueue = Depends(get_job_queue),
    request_id: str = Depends(get_request_id),
) -> JobDetailResponse:
    job = queue.cancel(job_id)
    return JobDetailResponse(job=_to_item(job), request_id=request_id)


__all__ = ["router"]
