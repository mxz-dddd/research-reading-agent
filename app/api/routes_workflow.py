from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.schemas.workflow import (
    ResearchWorkflowRequest,
    ResearchWorkflowResponse,
    WorkflowRunDetailResponse,
    WorkflowRunHistoryResponse,
    WorkflowRunLatestResponse,
    WorkflowReportResponse,
)
from app.services.research_workflow_service import ResearchWorkflowService
from app.services.workflow_job_service import workflow_job_store
from app.services.workflow_report_service import WorkflowReportService

router = APIRouter(tags=["workflow"])
workflow_service = ResearchWorkflowService()
workflow_report_service = WorkflowReportService()


@router.post("/run", response_model=ResearchWorkflowResponse)
def run_research_workflow(payload: ResearchWorkflowRequest) -> ResearchWorkflowResponse:
    return workflow_service.run(payload)


def _run_workflow_job(job_id: str, payload: ResearchWorkflowRequest) -> None:
    workflow_job_store.mark_running(job_id)
    try:
        result = workflow_service.run(payload)
        workflow_job_store.mark_completed(
            job_id,
            run_id=result.run_id,
            success=result.success,
            error=result.error,
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务需要兜底记录失败原因
        workflow_job_store.mark_failed(job_id, error=str(exc))


@router.post("/run-async")
def run_research_workflow_async(
    payload: ResearchWorkflowRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """异步触发 workflow：立即返回 job_id，用 GET /api/workflow/jobs/{job_id} 轮询状态。"""
    job_id = workflow_job_store.create_job(topic=payload.topic)
    background_tasks.add_task(_run_workflow_job, job_id, payload)
    return {"success": True, "job_id": job_id, "status": "queued"}


@router.get("/jobs/{job_id}")
def get_workflow_job(job_id: str) -> dict:
    job = workflow_job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_id 不存在")
    return {"success": True, "job": job}


@router.get("/latest", response_model=WorkflowRunLatestResponse)
def get_latest_workflow() -> WorkflowRunLatestResponse:
    run = workflow_service.latest_workflow()
    if run is None:
        return WorkflowRunLatestResponse(success=False, data=None, message="还没有 workflow run 记录")
    return WorkflowRunLatestResponse(success=True, data=run)


@router.get("/history", response_model=WorkflowRunHistoryResponse)
def list_workflow_history(limit: int = Query(default=10, ge=1, le=100)) -> WorkflowRunHistoryResponse:
    return WorkflowRunHistoryResponse(
        success=True,
        items=workflow_service.list_workflow_history(limit=limit),
    )


@router.post("/{run_id}/report", response_model=WorkflowReportResponse)
def generate_workflow_report(run_id: str) -> WorkflowReportResponse:
    return workflow_report_service.generate_report(run_id)


@router.get("/{run_id}/report", response_model=WorkflowReportResponse)
def get_workflow_report(run_id: str) -> WorkflowReportResponse:
    return workflow_report_service.get_report(run_id)


@router.get("/{run_id}", response_model=WorkflowRunDetailResponse)
def get_workflow_detail(run_id: str) -> WorkflowRunDetailResponse:
    return WorkflowRunDetailResponse(success=True, data=workflow_service.get_workflow_detail(run_id))
