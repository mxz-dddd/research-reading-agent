"""应用级领域异常。

业务层（repositories / services / agent）不依赖 FastAPI，
统一抛出这里定义的异常；HTTP 状态码映射由 app.main 中的
异常处理器完成。
"""

from __future__ import annotations


class AppError(Exception):
    """业务异常基类，默认映射为 HTTP 500。"""

    status_code: int = 500

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class InvalidRequestError(AppError):
    """请求参数不合法，映射为 HTTP 400。"""

    status_code = 400


class UnauthorizedError(AppError):
    """鉴权失败，映射为 HTTP 401。"""

    status_code = 401


class NotFoundError(AppError):
    """资源不存在，映射为 HTTP 404。"""

    status_code = 404
