"""
곁눈(Gyeotnun) - 임베딩 기반 공식 문서 검색
담당: 김유리 (검색)

BM25(corpus_index.match_official_docs)와는 완전히 다른, 의미 기반 검색이다.
같은 OFFICIAL_CHUNKS(공식 문서 재청킹 결과)를 벡터로 미리 인덱싱해 두고,
질의 문장을 같은 방식으로 벡터화해 코사인 유사도로 가장 가까운 청크를 찾는다.

제공자: Upstage Solar Embedding (한국어 특화, 국내 API - 2026-08 Voyage 에서 전환).
  - 문서용/질의용 모델이 분리돼 있다: solar-embedding-1-large-passage(색인),
    solar-embedding-1-large-query(검색). ★★ 절대 섞어 쓰지 않는다 - 섞으면
    같은 벡터공간이라도 검색 품질이 크게 떨어진다(Upstage 문서 명시).

★ provider 를 바꿀 수 있도록 구조를 분리해 뒀다 - 나중에 다른 임베딩 제공자와
  비교하려면 _embed_<provider>() 계열 함수만 추가하고 embed_texts() 의 분기만
  넓히면 된다. build_index()/match_embedding_docs() 등 바깥쪽 인터페이스는
  그대로 유지된다.

★ 절대 하지 않는 것
  - 매 기동 시 재임베딩. 인덱스는 api/tools/build_embedding_index.py 로
    1회성 배치 작업으로 만들고, 파일(EMBEDDING_INDEX_PATH)에 저장해 재사용한다.
    이 모듈은 그 파일을 "읽기만" 한다 - API 키가 있어도 기동 시점에 임베딩 API 를
    호출하지 않는다(비용·시간 낭비 방지, 사용자 요청 명시 사항).
  - 인덱스 파일이 없거나, 저장된 provider/모델/차원수가 지금 설정과 다르면
    조용히 0건으로 동작한다(다른 모델로 만든 인덱스가 섞여 검색이 망가지는 것을
    막기 위해서다 - 절대 "그냥 써 본다"로 넘어가지 않는다).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from config import settings
from services import corpus_index

log = logging.getLogger("gyeotnun.embeddings")

# ==================================================== 제공자 설정 (Upstage)
EMBEDDING_PROVIDER = "upstage"
EMBEDDING_MODEL_DOCUMENT = "solar-embedding-1-large-passage"   # 색인(문서) 전용
EMBEDDING_MODEL_QUERY = "solar-embedding-1-large-query"        # 검색(질의) 전용
EMBEDDING_DIMENSIONS = 4096
UPSTAGE_EMBED_URL = "https://api.upstage.ai/v1/solar/embeddings"

# ★ corpus/ 는 컨테이너에 읽기 전용으로 마운트돼 있다(docker-compose.yml `:ro` -
#   원본 코퍼스를 실수로 건드리지 못하게 하는 의도적 제약). 임베딩 인덱스는 그
#   코퍼스에서 "파생된 출력물"이라 corpus/ 바깥, api/ 밑의 쓰기 가능한 위치에
#   저장한다(api/ 는 `./api:/app` 로 읽기-쓰기 마운트돼 있다).
EMBEDDING_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "embeddings"
EMBEDDING_INDEX_PATH = EMBEDDING_DATA_DIR / f"embedding_index_{EMBEDDING_PROVIDER}_solar_large.npz"

# 20건 소량 테스트로 실측(2026-08-02): 청크당 평균 407.6 토큰. 100건씩 묶어도
# 요청당 약 4만 토큰 수준이라 여유롭다 - 오히려 요청 "횟수"가 많을수록 레이트리밋
# (429)에 걸리기 쉬웠던 걸 실측으로 확인해서, 요청 수를 줄이는 쪽으로 배치를 키웠다.
BATCH_SIZE = 100
# 배치 사이 짧은 간격을 둔다 - 레이트리밋을 애초에 덜 만나게 하는 예방 조치
# (429 를 만나면 _embed_upstage() 가 별도로 재시도/백오프한다).
BATCH_PAUSE_SEC = 1.0


def _embed_upstage(texts: List[str], model: str, max_retries: int = 5) -> Tuple[List[List[float]], int]:
    """Upstage Solar Embedding 호출 1건. (벡터 목록, 사용 토큰 수) 를 돌려준다.

    ★ 429(레이트리밋)는 재시도한다 - 새 계정/짧은 시간에 배치를 몰아서 보내면
      실제로 걸린다(2026-08-02 전체 인덱싱 중 실측). Retry-After 헤더가 있으면
      그 값을, 없으면 지수 백오프(2, 4, 8, 16, 32초)를 쓴다.
    """
    import time

    import httpx

    for attempt in range(1, max_retries + 1):
        resp = httpx.post(
            UPSTAGE_EMBED_URL,
            headers={
                "Authorization": f"Bearer {settings.UPSTAGE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"input": texts, "model": model},
            timeout=60,
        )
        if resp.status_code == 429 and attempt < max_retries:
            wait = float(resp.headers.get("Retry-After", 2 ** attempt))
            log.warning("[embeddings] 429 레이트리밋 - %.0f초 대기 후 재시도 (%d/%d)", wait, attempt, max_retries)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        payload = resp.json()
        vectors = [item["embedding"] for item in payload["data"]]
        tokens = int(payload.get("usage", {}).get("total_tokens", 0))
        return vectors, tokens
    raise RuntimeError("Upstage 임베딩 재시도 한도 초과")


def embed_texts(texts: List[str], input_type: str) -> Tuple[List[List[float]], int]:
    """텍스트 목록을 배치로 나눠 임베딩한다. input_type 은 'document'|'query'.

    ★★ 문서용/질의용 모델을 여기서 정확히 갈라 쓴다 - 색인할 때(document)와
      검색할 때(query)를 절대 같은 모델로 섞지 않는다(Upstage 공식 문서 경고).
    """
    if EMBEDDING_PROVIDER != "upstage":
        raise NotImplementedError(f"미지원 임베딩 제공자: {EMBEDDING_PROVIDER}")
    model = EMBEDDING_MODEL_DOCUMENT if input_type == "document" else EMBEDDING_MODEL_QUERY

    import time as _time

    out: List[List[float]] = []
    total_tokens = 0
    n_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE
    for bi, i in enumerate(range(0, len(texts), BATCH_SIZE)):
        batch = texts[i : i + BATCH_SIZE]
        vectors, tokens = _embed_upstage(batch, model)
        out.extend(vectors)
        total_tokens += tokens
        log.info(
            "[embeddings] 배치 %d~%d/%d 완료 (모델=%s, 이번 배치 토큰=%s, 누적=%s)",
            i, i + len(batch), len(texts), model, tokens, total_tokens,
        )
        if bi < n_batches - 1:
            _time.sleep(BATCH_PAUSE_SEC)
    return out, total_tokens


def build_index(chunks: Optional[list] = None) -> None:
    """청크 목록을 임베딩해 EMBEDDING_INDEX_PATH 에 저장한다.

    ★ 1회성 배치 작업이다 - api/tools/build_embedding_index.py 로만 실행한다.
      이 함수는 이 모듈이나 서버 기동 경로 어디에서도 자동 호출되지 않는다.
    chunks 를 생략하면 corpus_index.OFFICIAL_CHUNKS 전체를 쓴다 - 소량 테스트
    시(예: 20건)에는 build_embedding_index.py 가 일부만 잘라 넘긴다.
    """
    chunks = chunks if chunks is not None else corpus_index._OFFICIAL_CHUNKS
    if not chunks:
        log.warning("[embeddings] 임베딩할 청크가 없다.")
        return

    texts = [c.text for c in chunks]
    log.info(
        "[embeddings] %d개 청크 임베딩 시작 (제공자=%s, 모델=%s)",
        len(texts), EMBEDDING_PROVIDER, EMBEDDING_MODEL_DOCUMENT,
    )
    vectors, total_tokens = embed_texts(texts, input_type="document")

    arr = np.array(vectors, dtype=np.float32)
    if arr.shape[1] != EMBEDDING_DIMENSIONS:
        log.warning(
            "[embeddings] 응답 차원(%d)이 예상(%d)과 다르다 - EMBEDDING_DIMENSIONS 를 확인할 것",
            arr.shape[1], EMBEDDING_DIMENSIONS,
        )
    # 코사인 유사도를 내적(dot product)만으로 계산할 수 있도록 저장 시점에 정규화해 둔다.
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    arr = arr / norms

    chunk_ids = np.array([c.chunk_id for c in chunks])
    record_ids = np.array([c.record_id for c in chunks])

    EMBEDDING_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        EMBEDDING_INDEX_PATH,
        vectors=arr,
        chunk_ids=chunk_ids,
        record_ids=record_ids,
        provider=np.array([EMBEDDING_PROVIDER]),
        model=np.array([EMBEDDING_MODEL_DOCUMENT]),
        dimensions=np.array([arr.shape[1]]),
    )
    log.info(
        "[embeddings] 인덱스 저장 완료: %s (%d개 벡터, 차원=%d, 총 %s 토큰 사용)",
        EMBEDDING_INDEX_PATH, arr.shape[0], arr.shape[1], total_tokens,
    )
    print(f"사용된 토큰: {total_tokens:,} (제공자={EMBEDDING_PROVIDER}, 모델={EMBEDDING_MODEL_DOCUMENT})")


class EmbeddingIndex:
    """저장된 인덱스 파일을 읽기 전용으로 들고 있는다. 파일이 없거나 지금 설정과
    provider/모델/차원수가 다르면 빈 인덱스로 동작한다(다른 모델 벡터가 섞여
    검색이 조용히 망가지는 것을 막기 위한 방어 로직)."""

    def __init__(self, path: Path):
        self.record_ids: Optional[np.ndarray] = None
        self.vectors: Optional[np.ndarray] = None
        self.provider: Optional[str] = None
        self.model: Optional[str] = None
        if not path.exists():
            log.info("[embeddings] 인덱스 파일 없음(%s) - 임베딩 검색은 0건으로 동작한다.", path.name)
            return
        try:
            data = np.load(path, allow_pickle=False)
            provider = str(data["provider"][0]) if "provider" in data else "unknown"
            model = str(data["model"][0])
            dims = int(data["dimensions"][0]) if "dimensions" in data else data["vectors"].shape[1]

            if provider != EMBEDDING_PROVIDER or model != EMBEDDING_MODEL_DOCUMENT or dims != EMBEDDING_DIMENSIONS:
                log.warning(
                    "[embeddings] 인덱스 메타데이터 불일치(파일: provider=%s model=%s dim=%s / "
                    "현재 설정: provider=%s model=%s dim=%s) - 다른 모델로 만든 인덱스는 쓰지 않는다. "
                    "임베딩 검색 0건으로 동작.",
                    provider, model, dims, EMBEDDING_PROVIDER, EMBEDDING_MODEL_DOCUMENT, EMBEDDING_DIMENSIONS,
                )
                return

            self.vectors = data["vectors"]
            self.record_ids = data["record_ids"]
            self.provider = provider
            self.model = model
            log.info(
                "[embeddings] 인덱스 로드 완료: %s (%d개 벡터, 제공자=%s, 모델=%s)",
                path.name, self.vectors.shape[0], provider, model,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("[embeddings] 인덱스 로드 실패(%s) - 임베딩 검색 비활성화: %s", path.name, e)

    @property
    def ready(self) -> bool:
        return self.vectors is not None and len(self.vectors) > 0


_INDEX = EmbeddingIndex(EMBEDDING_INDEX_PATH)

# ★ 임계값(0.45)의 근거: 30건 평가세트 + 잡음 문장으로 실측했다(2026-08-02).
#   완전히 무관한 문장("오늘 날씨가 좋네요" 등)의 최고 유사도는 0.23~0.35였고,
#   실제로 대응하는 공식 문서가 있는 '정상' 10건의 최저 유사도는 0.5378이었다 -
#   0.35와 0.5378 사이가 비어 있어(잡음 최고점 < 임계값 < 진짜 매칭 최저점) 0.45를
#   그 사이에 놓았다. 이걸 안 하면(임계값 0) 완전히 무관한 문장에도 "가장 가까운"
#   문서를 항상 돌려주게 되어, '확인 불가' 로 갈 길이 임베딩 경로에서는 구조적으로
#   막힌다(BM25 를 처음 붙였을 때와 같은 문제 - docs/evaluation/eval_30_report.md
#   §match_official_docs 임계값 근거와 같은 논리).
EMBEDDING_MIN_SCORE = 0.45


def match_embedding_docs(text: str, limit: int = 2, min_score: float = EMBEDDING_MIN_SCORE) -> List[tuple]:
    """질의 문장을 임베딩해 코사인 유사도로 가장 가까운 공식 문서를 찾는다.

    BM25 와 동일하게 청크 단위로 검색하고 문서(record_id) 단위로 최고점만 남긴다.
    반환값은 (score, OfficialDoc) 튜플 리스트다.
    """
    if not settings.has_embeddings or not _INDEX.ready:
        return []
    try:
        vectors, _tokens = embed_texts([text], input_type="query")
        q_vec = vectors[0]
    except Exception as e:  # noqa: BLE001
        log.warning("[embeddings] 질의 임베딩 실패(무시하고 0건 반환): %s", e)
        return []

    q = np.array(q_vec, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return []
    q = q / q_norm

    sims = _INDEX.vectors @ q  # 저장 시 이미 정규화했으므로 내적 = 코사인 유사도

    best_per_doc: dict = {}
    for record_id, sim in zip(_INDEX.record_ids, sims):
        rid = str(record_id)
        if sim <= 0:
            continue
        prev = best_per_doc.get(rid)
        if prev is None or sim > prev:
            best_per_doc[rid] = float(sim)

    scored = [(score, rid) for rid, score in best_per_doc.items() if score >= min_score]
    scored.sort(key=lambda x: -x[0])

    result = []
    for score, rid in scored[:limit]:
        doc = corpus_index._OFFICIAL_DOCS_BY_ID.get(rid)
        if doc is None:
            continue
        log.info("[match_embedding] doc=%s score=%.4f", doc.id, score)
        result.append((score, doc))
    return result
