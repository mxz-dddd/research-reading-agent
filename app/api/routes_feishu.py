from __future__ import annotations

from fastapi import APIRouter
from fastapi import Request

from app.services.feishu_service import FeishuService

router = APIRouter(prefix="/feishu", tags=["feishu"])
feishu_service = FeishuService()


@router.post("/webhook")
async def receive_webhook(request: Request) -> dict:
    raw_body = await request.body()
    headers = dict(request.headers)
    return feishu_service.handle_webhook(raw_body=raw_body, headers=headers)
