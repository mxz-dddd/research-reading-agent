import logging

from fastapi import APIRouter, BackgroundTasks
from fastapi import Request

from app.services.feishu_service import FeishuService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feishu", tags=["feishu"])
feishu_service = FeishuService()


@router.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    raw_body = await request.body()
    headers = dict(request.headers)
    logger.info(
        "feishu_webhook_http_received content_length=%s",
        len(raw_body),
    )
    return feishu_service.handle_webhook(
        raw_body=raw_body,
        headers=headers,
        background_tasks=background_tasks,
    )
