# meta_agent

리뷰가 끝난 최종 Markdown을 받아 네이버 블로그 SEO 메타데이터를 생성하는 FastAPI 에이전트.

## 역할

파이프라인에서 `review_agent` 직후, 사용자 확인 단계 직전에 호출된다. Spring orchestrator가 최종 Markdown과 선택적 검색어를 전달하면, Ollama LLM 한 번으로 제목 후보·해시태그·메타 디스크립션·추천 카테고리를 생성하고 C-Rank 자가 점검 신호를 함께 반환한다. LLM이 비활성이거나 실패해도 키워드 기반 결정론적 fallback으로 최소한의 후보를 반환한다.

**입력**: 최종 Markdown + (선택) 검색어 + (선택) 사진 메타 목록  
**출력**: SEO 메타데이터 (제목 후보 3개, 해시태그, 메타 디스크립션, 추천 카테고리, C-Rank 신호)

## API

### `GET /health`

서비스 활성 확인.

**응답**
```json
{"status": "ok", "service": "meta_agent"}
```

---

### `POST /api/v1/meta`

최종 Markdown에서 네이버 블로그 메타데이터를 생성한다.

**요청 본문**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `project_id` | string | Y | 프로젝트 식별자 (최소 1자) |
| `final_markdown` | string | Y | 리뷰가 완료된 최종 Markdown 본문 |
| `target_keywords` | string | N | 쉼표·줄바꿈·세미콜론으로 구분된 주력 검색어 |
| `photos` | array | N | 사진 메타 객체 목록 (C-Rank 자체 촬영 비율 계산용) |

`photos` 항목 예시: `{"file_name": "img.jpg", "has_exif": true, "captured_at": "2026-05-22", "has_gps": false}`  
`has_exif`, `captured_at`, `has_gps` 중 하나라도 있으면 자체 촬영 사진으로 간주한다.

**응답**

```json
{
  "project_id": "proj-123",
  "meta_status": "ok",
  "title_candidates": [
    {
      "title": "제주 흑돼지 맛집 솔직 후기",
      "length": 17,
      "contains_primary_keyword": true,
      "contains_any_keyword": true,
      "intent_note": "주력 검색어 포함"
    }
  ],
  "hashtags": ["제주흑돼지", "제주맛집", "흑돼지맛집"],
  "meta_description": "제주 흑돼지 맛집 후기 — 두툼한 고기와 분위기까지 정리한 솔직 리뷰.",
  "recommended_category": "맛집",
  "meta_signals": {
    "body_char_count": 1823,
    "image_count": 7,
    "owned_photo_ratio": 0.85,
    "keyword_occurrences": {"제주 흑돼지": 3},
    "warnings": []
  }
}
```

**`meta_status` 값**

| 값 | 의미 |
|----|------|
| `ok` | LLM 성공, 검색어 있음 |
| `ok_no_keywords` | LLM 성공, 검색어 없음 |
| `ok_fallback` | LLM 실패 → 결정론적 fallback |

**`intent_note` 값** (제목 후보별)

| 값 | 의미 |
|----|------|
| `주력 검색어 포함` | 첫 번째 검색어가 제목에 포함됨 |
| `보조 검색어 포함` | 두 번째 이후 검색어가 포함됨 |
| `검색어 미반영` | 어느 검색어도 없음 |
| `짧음 — 검색 노출 약함` | 제목 18자 미만 |
| `긺 — 모바일 잘림 위험` | 제목 40자 초과 |

**`meta_signals.warnings`** — 아래 조건에 해당하면 경고 문자열이 추가됨:
- 본문 글자수 1,500자 미만
- 이미지 5장 미만
- 자체 촬영 추정 비율 50% 미만
- 주력 검색어가 본문에 한 번도 등장하지 않음

## 실행

### 로컬

```bash
pip install -r requirements.txt
uvicorn src.api_server:app --reload --port 8100
```

### Docker

```bash
# deploy/ 의 docker-compose에서 meta_agent 서비스로 포함되어 있음
docker compose up --build meta_agent
```

컨테이너 내부 포트는 `PORT` 환경 변수로 지정하며 기본값은 `8100`이다.

## 설정

| 이름 | 설명 | 기본값 |
|------|------|--------|
| `OLLAMA_BASE_URL` | Ollama API 엔드포인트 | `http://localhost:11434` |
| `META_MODEL` | 사용할 Ollama 모델 | `qwen2.5:14b` |
| `OLLAMA_TIMEOUT_SECONDS` | Ollama 요청 타임아웃 (초) | `120` |
| `META_DISABLE_LLM` | `1`이면 LLM 호출 없이 결정론적 fallback만 사용 | (미설정) |

## 테스트

```bash
# .venv 사용 시
scripts/verify.sh

# Python 경로 지정 시
PYTHON=/usr/bin/python3 scripts/verify.sh
```

커버리지 기준: **85% 이상** (미달 시 스크립트가 0이 아닌 코드로 종료).

## 구조

```
src/
  api_server.py        # FastAPI 앱 + MetaRequest 모델 + 라우터
  meta_generator.py    # generate_meta() 핵심 로직, Ollama 호출,
                       # 제목/해시태그/메타디스크립션/카테고리 결정론적 후처리,
                       # C-Rank 신호 계산 (_compute_meta_signals)
tests/
  test_meta_generator.py  # unittest 기반 통합/단위 테스트
scripts/
  verify.sh            # coverage run + 85% 기준 체크
requirements.txt       # fastapi, uvicorn, pydantic, httpx, coverage
```
