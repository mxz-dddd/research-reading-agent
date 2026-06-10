from __future__ import annotations

from app.core.exceptions import AppError, InvalidRequestError, UnauthorizedError

import base64
import hashlib
import hmac
import json
import logging
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi

from app.core.config import settings
from app.schemas.agent import AgentQueryRequest
from app.services.agent_service import AgentService

logger = logging.getLogger(__name__)


class FeishuService:
    def __init__(
        self,
        agent_service: AgentService | None = None,
    ) -> None:
        self.agent_service = agent_service if agent_service is not None else AgentService()

    def handle_webhook(self, raw_body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        payload = self._load_payload(raw_body)

        if self._is_challenge(payload):
            self._verify_token(payload)
            return {"challenge": payload["challenge"]}

        self._verify_token(payload)
        self._verify_signature_if_needed(raw_body, headers)

        event_type = self._event_type(payload)
        if event_type != "im.message.receive_v1":
            return {
                "message": "已收到飞书事件，但当前只处理文本消息事件。",
                "event_type": event_type,
            }

        message = self._extract_message(payload)
        if message["message_type"] != "text":
            final_answer = "我目前只支持文本消息。请直接发送研究方向、论文编号或操作请求。"
            send_result = self._reply_to_feishu(message["message_id"], final_answer)
            return {
                "message": "非文本消息已友好回复",
                "send_result": send_result,
            }

        if not message["text"]:
            final_answer = "我没有读到有效文本，请重新发送你的问题。"
            send_result = self._reply_to_feishu(message["message_id"], final_answer)
            return {
                "message": "空文本消息已友好回复",
                "send_result": send_result,
            }

        agent_response = self.agent_service.query(
            AgentQueryRequest(
                user_id=f"feishu:{message['open_id'] or message['chat_id']}",
                session_id=f"feishu:{message['chat_id'] or message['open_id']}",
                message=message["text"],
            )
        )
        reply_text = self._format_agent_reply(agent_response.model_dump())
        send_result = self._reply_to_feishu(message["message_id"], reply_text)
        return {
            "message": "飞书文本消息已处理",
            "agent": agent_response.model_dump(),
            "send_result": send_result,
        }

    def _load_payload(self, raw_body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise InvalidRequestError(f"飞书请求体不是合法 JSON：{exc}") from exc

        if "encrypt" in payload:
            # TODO: 后续支持飞书加密事件解密。当前建议事件订阅先使用明文推送。
            raise InvalidRequestError("当前暂不支持飞书加密事件，请先关闭事件加密。")
        return payload

    def _is_challenge(self, payload: dict[str, Any]) -> bool:
        return payload.get("type") == "url_verification" and "challenge" in payload

    def _verify_token(self, payload: dict[str, Any]) -> None:
        expected = settings.feishu_verification_token
        if not expected:
            logger.warning("FEISHU_VERIFICATION_TOKEN 未配置，已跳过 token 校验。")
            return

        token = payload.get("token") or payload.get("header", {}).get("token")
        if token != expected:
            raise UnauthorizedError("飞书 verification token 校验失败")

    def _verify_signature_if_needed(self, raw_body: bytes, headers: dict[str, str]) -> None:
        if not settings.feishu_enable_signature_check:
            return
        if not settings.feishu_encrypt_key:
            raise AppError("已启用飞书签名校验，但缺少 FEISHU_ENCRYPT_KEY")

        timestamp = headers.get("x-lark-request-timestamp") or headers.get("x-feishu-request-timestamp")
        nonce = headers.get("x-lark-request-nonce") or headers.get("x-feishu-request-nonce")
        signature = headers.get("x-lark-signature") or headers.get("x-feishu-signature")
        if not timestamp or not nonce or not signature:
            raise UnauthorizedError("飞书签名请求头不完整")

        base = f"{timestamp}{nonce}{settings.feishu_encrypt_key}".encode("utf-8") + raw_body
        digest = hmac.new(settings.feishu_encrypt_key.encode("utf-8"), base, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        if not hmac.compare_digest(expected, signature):
            raise UnauthorizedError("飞书签名校验失败")

    def _event_type(self, payload: dict[str, Any]) -> str | None:
        return payload.get("header", {}).get("event_type") or payload.get("event", {}).get("type")

    def _extract_message(self, payload: dict[str, Any]) -> dict[str, str | None]:
        event = payload.get("event", {})
        sender_id = event.get("sender", {}).get("sender_id", {})
        message = event.get("message", {})
        content = message.get("content") or "{}"
        try:
            content_data = json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError:
            content_data = {}

        return {
            "open_id": sender_id.get("open_id"),
            "chat_id": message.get("chat_id"),
            "message_id": message.get("message_id"),
            "message_type": message.get("message_type"),
            "text": (content_data.get("text") or "").strip(),
        }

    def _tenant_access_token(self) -> str:
        if not settings.feishu_app_id or not settings.feishu_app_secret:
            raise RuntimeError("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET，无法获取 tenant_access_token")

        body = json.dumps(
            {
                "app_id": settings.feishu_app_id,
                "app_secret": settings.feishu_app_secret,
            }
        ).encode("utf-8")
        request = Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=20, context=self._ssl_context()) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败：{data}")
        return data["tenant_access_token"]

    def _reply_to_feishu(self, message_id: str | None, text: str) -> dict[str, Any]:
        if not message_id:
            return {"success": False, "error": "缺少 message_id，无法回复飞书消息"}

        try:
            token = self._tenant_access_token()
            body = json.dumps(
                {
                    "msg_type": "text",
                    "content": json.dumps({"text": self._truncate_text(text)}, ensure_ascii=False),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            request = Request(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
                data=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urlopen(request, timeout=20, context=self._ssl_context()) as response:
                data = json.loads(response.read().decode("utf-8"))
            if data.get("code") != 0:
                logger.error("飞书消息回复失败：%s", data)
                return {"success": False, "error": data}
            return {"success": True, "response": data}
        except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            logger.error("飞书消息回复异常：%s", exc)
            return {"success": False, "error": str(exc)}

    def _format_agent_reply(self, agent_response: dict[str, Any]) -> str:
        text = agent_response.get("final_answer") or "已处理。"
        status = [
            "",
            f"已调用工具：{agent_response.get('chosen_tool')}",
            f"路由方式：{agent_response.get('routing_method')}",
        ]
        return text + "\n".join(status)

    def _truncate_text(self, text: str, max_chars: int = 1800) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n内容较长，已截断。可在后端查看完整结果。"

    def _ssl_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())
