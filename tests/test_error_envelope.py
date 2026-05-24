"""error_envelope 모듈의 직접 단위 검증."""

import asyncio
from unittest import TestCase

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError

from src.error_envelope import (
    default_retryable,
    http_exception_handler,
    make_envelope,
    validation_exception_handler,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.get_event_loop().is_running() else asyncio.new_event_loop().run_until_complete(coro)


class MakeEnvelopeTest(TestCase):
    def test_make_envelope_always_has_seven_fields(self):
        envelope = make_envelope("X", "msg", "사용자 메시지", status_code=500)
        for key in ("error_code", "message", "user_message", "retryable", "retry_after_seconds", "trace_id", "details"):
            self.assertIn(key, envelope)
        self.assertTrue(envelope["retryable"])  # 5xx default
        self.assertIsNone(envelope["retry_after_seconds"])
        self.assertIsNone(envelope["trace_id"])
        self.assertEqual(envelope["details"], [])

    def test_make_envelope_4xx_default_not_retryable(self):
        envelope = make_envelope("X", "m", "u", status_code=400)
        self.assertFalse(envelope["retryable"])

    def test_make_envelope_429_default_retryable(self):
        envelope = make_envelope("X", "m", "u", status_code=429)
        self.assertTrue(envelope["retryable"])

    def test_make_envelope_explicit_retryable_overrides_default(self):
        envelope = make_envelope("X", "m", "u", retryable=False, status_code=500)
        self.assertFalse(envelope["retryable"])


class DefaultRetryableTest(TestCase):
    def test_5xx_retryable(self):
        self.assertTrue(default_retryable(500))
        self.assertTrue(default_retryable(503))

    def test_429_retryable(self):
        self.assertTrue(default_retryable(429))

    def test_4xx_not_retryable(self):
        self.assertFalse(default_retryable(400))
        self.assertFalse(default_retryable(404))


class HttpExceptionHandlerTest(TestCase):
    def test_dict_detail_with_error_code_passes_through(self):
        exc = HTTPException(
            status_code=404,
            detail={"error_code": "X_NOT_FOUND", "user_message": "없음"},
        )
        response = asyncio.new_event_loop().run_until_complete(http_exception_handler(None, exc))
        import json
        body = json.loads(response.body)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(body["error_code"], "X_NOT_FOUND")
        # setdefault 가 envelope shape 의 모든 키를 채움
        for key in ("message", "user_message", "retryable", "retry_after_seconds", "trace_id", "details"):
            self.assertIn(key, body)

    def test_string_detail_uses_status_default(self):
        exc = HTTPException(status_code=401, detail="some english raw detail")
        response = asyncio.new_event_loop().run_until_complete(http_exception_handler(None, exc))
        import json
        body = json.loads(response.body)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(body["error_code"], "UNAUTHENTICATED")
        # raw 영어 detail 은 message 에 들어가고 user_message 는 한국어 default
        self.assertEqual(body["message"], "some english raw detail")
        self.assertEqual(body["user_message"], "인증이 필요합니다.")

    def test_unknown_status_falls_back_to_generic(self):
        exc = HTTPException(status_code=418, detail=None)
        response = asyncio.new_event_loop().run_until_complete(http_exception_handler(None, exc))
        import json
        body = json.loads(response.body)
        self.assertEqual(response.status_code, 418)
        self.assertEqual(body["error_code"], "HTTP_ERROR")


class ValidationExceptionHandlerTest(TestCase):
    def test_validation_error_envelope(self):
        # Pydantic v2: errors() 는 dict list 반환. RequestValidationError 는 errors list 를 받음.
        errors = [{"loc": ("body", "x"), "msg": "field required", "type": "missing"}]
        exc = RequestValidationError(errors)
        response = asyncio.new_event_loop().run_until_complete(validation_exception_handler(None, exc))
        import json
        body = json.loads(response.body)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(body["error_code"], "VALIDATION_FAILED")
        self.assertEqual(len(body["details"]), 1)
        for key in ("loc", "msg", "type"):
            self.assertIn(key, body["details"][0])
