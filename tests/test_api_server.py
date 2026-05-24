"""ADR 005 단계 3: meta_agent 응답 형식 검증."""

from unittest import TestCase

from fastapi.testclient import TestClient

from src.api_server import app


class StandardErrorEnvelopeTest(TestCase):
    def test_validation_error_returns_standard_envelope(self) -> None:
        # project_id, final_markdown 누락 → 422 envelope
        response = TestClient(app).post("/api/v1/meta", json={})
        self.assertEqual(response.status_code, 422)
        body = response.json()
        for key in ("error_code", "message", "user_message", "retryable", "details"):
            self.assertIn(key, body, f"envelope must contain {key}")
        self.assertEqual(body["error_code"], "VALIDATION_FAILED")
        self.assertFalse(body["retryable"])
        self.assertGreater(len(body["details"]), 0)

    def test_health_endpoint_remains_ok(self) -> None:
        response = TestClient(app).get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
