from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.services.feishu_service import FeishuService

router = APIRouter(prefix="/feishu", tags=["feishu"])
feishu_service = FeishuService()


@router.post("/webhook")
async def receive_webhook(request: Request) -> dict:
    raw_body = await request.body()
    headers = dict(request.headers)
    # handle_webhook 内部有同步网络调用（飞书回复），放入线程池避免阻塞事件循环
    return await run_in_threadpool(feishu_service.handle_webhook, raw_body=raw_body, headers=headers)
