from fastapi import APIRouter, Query

from app.schemas.workflow import (
    ResearchWorkflowRequest,
    ResearchWorkflowResponse,
    WorkflowRunDetailResponse,
    WorkflowRunHistoryResponse,
    WorkflowRunLatestResponse,
    WorkflowReportResponse,
)
from app.services.research_workflow_service import ResearchWorkflowService
from app.services.workflow_report_service import WorkflowReportService

router = APIRouter(tags=["workflow"])
workflow_service = ResearchWorkflowService()
workflow_report_service = WorkflowReportService()


@router.post("/run", response_model=ResearchWorkflowResponse)
def run_research_workflow(payload: ResearchWorkflowRequest) -> ResearchWorkflowResponse:
    return workflow_service.run(payload)


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
