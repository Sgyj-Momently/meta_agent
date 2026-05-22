import json
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api_server import app
from src.meta_generator import generate_meta


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        envelope = {"response": json.dumps(self._payload, ensure_ascii=False)}
        return json.dumps(envelope, ensure_ascii=False).encode("utf-8")


def _ollama_patch(payload: dict):
    return patch(
        "src.meta_generator.urllib_request.urlopen",
        return_value=_FakeResponse(payload),
    )


class MetaGeneratorLlmPathTest(TestCase):
    def test_generate_uses_llm_titles_and_hashtags(self):
        fake = {
            "titles": [
                "제주 흑돼지 맛집 솔직 후기 두툼한 한 끼",
                "혼자서도 좋은 제주 흑돼지 맛집 추천 리스트",
                "제주 여행에서 꼭 들러야 할 흑돼지 맛집",
            ],
            "hashtags": ["제주흑돼지", "제주맛집", "흑돼지맛집", "제주여행", "맛집추천"],
            "meta_description": "제주 흑돼지 맛집 후기 — 두툼한 고기와 분위기까지 정리한 솔직 리뷰.",
            "recommended_category": "맛집",
        }
        with _ollama_patch(fake):
            result = generate_meta(
                {
                    "final_markdown": (
                        "# 제주 흑돼지 맛집 후기\n\n"
                        "두툼한 흑돼지를 먹었다. 정말 만족스러웠다."
                    ),
                    "target_keywords": "제주 흑돼지 맛집",
                }
            )

        self.assertEqual(result["meta_status"], "ok")
        self.assertEqual(len(result["title_candidates"]), 3)
        self.assertTrue(result["title_candidates"][0]["contains_primary_keyword"])
        self.assertGreaterEqual(len(result["hashtags"]), 5)
        self.assertLessEqual(len(result["hashtags"]), 10)
        self.assertIn("제주", result["meta_description"])
        self.assertEqual(result["recommended_category"], "맛집")

    def test_no_keywords_marks_status_and_keeps_empty_occurrence_map(self):
        fake = {
            "titles": [
                "오늘 다녀온 카페 기록 한 장면",
                "분위기 좋은 카페 한 곳을 다녀왔어요",
                "주말 카페 산책 후기 한 줄 정리",
            ],
            "hashtags": ["카페", "주말카페", "분위기카페", "동네카페", "카페투어"],
            "meta_description": "주말에 들른 카페에서 보낸 한낮의 기록.",
            "recommended_category": "맛집",
        }
        with _ollama_patch(fake):
            result = generate_meta(
                {
                    "final_markdown": (
                        "# 주말 카페 기록\n\n분위기가 좋은 카페에서 시간을 보냈다."
                    ),
                }
            )

        self.assertEqual(result["meta_status"], "ok_no_keywords")
        self.assertEqual(result["meta_signals"]["keyword_occurrences"], {})

    def test_meta_description_truncated_to_max_length(self):
        long_text = "가" * 300
        fake = {
            "titles": ["테스트 제목 한 줄짜리 검증용 문장입니다", "테스트 제목 두 번째 후보", "테스트 제목 세 번째"],
            "hashtags": ["테스트", "검증", "샘플", "기록", "예시"],
            "meta_description": long_text,
            "recommended_category": "일상",
        }
        with _ollama_patch(fake):
            result = generate_meta(
                {
                    "final_markdown": "# 테스트 글\n\n본문입니다.",
                    "target_keywords": "테스트",
                }
            )

        self.assertLessEqual(len(result["meta_description"]), 155)


class MetaGeneratorFallbackTest(TestCase):
    def test_falls_back_when_ollama_fails(self):
        with patch(
            "src.meta_generator.urllib_request.urlopen",
            side_effect=ConnectionError("ollama down"),
        ):
            result = generate_meta(
                {
                    "final_markdown": "# 제주 흑돼지 후기\n\n맛있게 먹었다.",
                    "target_keywords": "제주 흑돼지",
                }
            )

        self.assertEqual(result["meta_status"], "ok_fallback")
        self.assertEqual(len(result["title_candidates"]), 3)
        self.assertTrue(
            any(cand["contains_primary_keyword"] for cand in result["title_candidates"])
        )
        self.assertIn("제주흑돼지", result["hashtags"])


class MetaSignalsTest(TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {"META_DISABLE_LLM": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_counts_images_and_body_chars(self):
        markdown = "# 일기\n\n오늘은 평범했다.\n\n![pic](a.jpg)"
        result = generate_meta(
            {
                "final_markdown": markdown,
                "target_keywords": "전혀안나오는키워드",
            }
        )

        signals = result["meta_signals"]
        self.assertEqual(signals["image_count"], 1)
        self.assertGreater(signals["body_char_count"], 0)
        self.assertTrue(
            any("주력 검색어" in w for w in signals["warnings"]),
            f"warnings={signals['warnings']}",
        )

    def test_owned_photo_ratio_from_exif_signals(self):
        result = generate_meta(
            {
                "final_markdown": "# 사진\n\n사진을 첨부합니다.",
                "photos": [
                    {"file_name": "a.jpg", "has_exif": True},
                    {"file_name": "b.jpg", "captured_at": "2026-05-22"},
                    {"file_name": "c.jpg"},
                    {"file_name": "d.jpg"},
                ],
            }
        )

        signals = result["meta_signals"]
        self.assertEqual(signals["owned_photo_ratio"], 0.5)


class MetaEndpointTest(TestCase):
    def test_health(self):
        client = TestClient(app)
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["service"], "meta_agent")

    def test_meta_endpoint_returns_candidates(self):
        with patch.dict("os.environ", {"META_DISABLE_LLM": "1"}):
            client = TestClient(app)
            response = client.post(
                "/api/v1/meta",
                json={
                    "project_id": "sample",
                    "final_markdown": "# 제주 흑돼지\n\n맛있게 먹었다.",
                    "target_keywords": "제주 흑돼지",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["project_id"], "sample")
        self.assertEqual(len(body["title_candidates"]), 3)
        self.assertGreaterEqual(len(body["hashtags"]), 1)

    def test_metrics_endpoint_returns_prometheus_data(self):
        client = TestClient(app)

        response = client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn("http_request_duration_seconds", response.text)
