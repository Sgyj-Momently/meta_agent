"""ADR 005 표준 에러 응답 envelope.

FastAPI 의 기본 에러 본문(`{"detail": "..."}` 또는 RequestValidationError 의 list)
을 ADR 005 envelope `{error_code, message, user_message, retryable, retry_after_seconds,
trace_id, details}` 로 통일한다. orchestrator 의 `AgentErrorParser` 가 `error_code`
필드 존재로 표준 envelope 을 감지하므로 형식이 정확히 일치해야 한다.

사용법:

- 새 에러는 ``raise HTTPException(status_code=..., detail=make_envelope(...))`` 으로
  명시적으로 envelope 을 만든다.
- 그렇지 않은 기존 ``HTTPException`` / ``RequestValidationError`` 는 본 모듈의 handler 가
  status_code 기반 default mapping 으로 자동 wrap 한다.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


# status code → 기본 error_code / user_message 매핑.
# 명시적 error_code 가 detail dict 로 들어오면 이 매핑보다 우선한다.
_DEFAULTS: dict[int, tuple[str, str]] = {
    400: ("INVALID_REQUEST", "요청을 처리할 수 없습니다. 입력값을 확인해 주세요."),
    401: ("UNAUTHENTICATED", "인증이 필요합니다."),
    403: ("FORBIDDEN", "접근 권한이 없습니다."),
    404: ("NOT_FOUND", "요청한 리소스를 찾을 수 없습니다."),
    409: ("CONFLICT", "요청이 현재 상태와 충돌합니다."),
    422: ("VALIDATION_FAILED", "입력값을 확인해 주세요."),
    429: ("RATE_LIMITED", "요청이 잠시 제한됐습니다. 잠시 후 다시 시도해 주세요."),
    500: ("INTERNAL_ERROR", "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."),
    502: ("BAD_GATEWAY", "업스트림 서비스가 응답하지 않습니다."),
    503: ("SERVICE_UNAVAILABLE", "서비스가 일시적으로 사용 불가합니다."),
    504: ("GATEWAY_TIMEOUT", "응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."),
}


def default_retryable(status_code: int) -> bool:
    """status 기반 retryable 기본값. 5xx 와 429 만 retryable."""
    return status_code >= 500 or status_code == 429


def make_envelope(
    error_code: str,
    message: str,
    user_message: str,
    *,
    retryable: Optional[bool] = None,
    status_code: int = 500,
    retry_after_seconds: Optional[int] = None,
    trace_id: Optional[str] = None,
    details: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """ADR 005 표준 envelope dict 생성.

    ``retryable`` 이 명시되지 않으면 ``status_code`` 기반 default 를 사용한다.
    응답의 shape 가 항상 일관되도록 optional 필드도 모두 키를 두고 미설정 시 null/[] 로 채운다.
    """
    return {
        "error_code": error_code,
        "message": message,
        "user_message": user_message,
        "retryable": retryable if retryable is not None else default_retryable(status_code),
        "retry_after_seconds": retry_after_seconds,
        "trace_id": trace_id,
        "details": details or [],
    }


async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    """HTTPException 을 표준 envelope 으로 변환.

    ``detail`` 이 dict 이고 ``error_code`` 가 있으면 그 envelope 을 그대로 사용.
    문자열이면 status_code 기반 default mapping 으로 wrap.
    """
    status_code = exc.status_code
    headers = exc.headers or {}

    if isinstance(exc.detail, dict) and exc.detail.get("error_code"):
        envelope = dict(exc.detail)
        envelope.setdefault("message", envelope.get("user_message", ""))
        envelope.setdefault("user_message", envelope.get("message", ""))
        envelope.setdefault("retryable", default_retryable(status_code))
        envelope.setdefault("retry_after_seconds", None)
        envelope.setdefault("trace_id", None)
        envelope.setdefault("details", [])
    else:
        default_code, default_user = _DEFAULTS.get(
            status_code,
            ("HTTP_ERROR", "요청을 처리하지 못했습니다."),
        )
        # 기존 HTTPException 의 detail 이 영어/raw 일 가능성. message 에는 기술적 raw 값,
        # user_message 에는 한국어 default 를 둬서 콘솔에 raw 가 노출되지 않게 함.
        raw_detail = str(exc.detail) if exc.detail else default_user
        envelope = make_envelope(
            default_code,
            raw_detail,
            default_user,
            status_code=status_code,
        )

    return JSONResponse(status_code=status_code, content=envelope, headers=headers)


async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    """FastAPI RequestValidationError 를 표준 envelope + details 로 변환."""
    details = [
        {
            "loc": [str(item) for item in err.get("loc", [])],
            "msg": str(err.get("msg", "")),
            "type": str(err.get("type", "")),
        }
        for err in exc.errors()
    ]
    envelope = make_envelope(
        "VALIDATION_FAILED",
        "request validation failed",
        "입력값을 확인해 주세요.",
        status_code=422,
        details=details,
    )
    return JSONResponse(status_code=422, content=envelope)


def install_envelope_handlers(app: Any) -> None:
    """FastAPI 앱에 표준 envelope handler 들을 등록한다."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
