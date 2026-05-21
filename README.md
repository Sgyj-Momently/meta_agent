# Meta Agent

리뷰가 끝난 최종 마크다운을 받아 네이버 블로그 검색 유입에 도움이 되는
메타데이터(제목 후보, 해시태그, 메타 디스크립션, 추천 카테고리)와
C-Rank 자가 점검 신호를 생성한다.

Ollama LLM 호출 한 번 + 결정론 후처리 + 키워드 기반 fallback 구조다.
LLM이 비활성/실패해도 키워드만 있으면 최소한의 후보를 반환한다.

## API

- `GET /health`
- `POST /api/v1/meta`

## 환경 변수

- `META_MODEL` (기본 `qwen2.5:14b`)
- `OLLAMA_BASE_URL` (기본 `http://localhost:11434`)
- `OLLAMA_TIMEOUT_SECONDS` (기본 `120`)
- `META_DISABLE_LLM` — `1` 이면 LLM 호출 없이 결정론 fallback 만 사용

## Verification

```bash
PYTHON=/path/to/python scripts/verify.sh
```
