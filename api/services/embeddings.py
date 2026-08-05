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

# ==================================================== 제공자 설정
# ★ 2026-08-04 전환: upstage(상용 API) → local(로컬 모델).
#   이 상수 하나만 "upstage" 로 되돌리면 즉시 원복된다 - 아래 Upstage 코드는
#   지우지 않고 그대로 뒀다(롤백 경로 보존).
#
#   전환 근거(docs/evaluation/local_embeddings_report.md, 30건 실측):
#     지표          Upstage   e5-small-ko-v2
#     Recall@3        0.65        0.65   (동일)
#     근거검색        0.867       0.900   (로컬이 더 높음)
#     기대판단일치율   0.667       0.667   (동일)
#     정상10건 오판    0/10        0/10   (절대조건 유지)
#     질의 응답       112ms       141ms
#   그리고 로컬 후보 5종 중 **유일하게** 경계/정상 유사도가 분리된다
#   (정상min 0.6820 > 경계max 0.6760). 다른 모델은 역전되어 확신 판정이 불가능했다.
#
#   가장 큰 이유는 성능이 아니라 개인정보다 - 질의 텍스트가 외부로 나가지 않는다.
EMBEDDING_PROVIDER = "local"

# ---- 로컬 제공자 설정
LOCAL_EMBED_MODEL = "dragonkue/multilingual-e5-small-ko-v2"   # Apache-2.0
LOCAL_EMBED_DIMENSIONS = 384
# ★ e5 계열은 "query: "/"passage: " 접두어가 필수다(모델 카드 공식 권고).
#   안 붙이면 검색 품질이 크게 떨어진다 - 색인과 질의에서 반드시 같은 규약을 쓴다.
LOCAL_QUERY_PREFIX = "query: "
LOCAL_PASSAGE_PREFIX = "passage: "

# ---- Upstage 제공자 설정 (롤백용으로 보존)
EMBEDDING_MODEL_DOCUMENT = "solar-embedding-1-large-passage"   # 색인(문서) 전용
EMBEDDING_MODEL_QUERY = "solar-embedding-1-large-query"        # 검색(질의) 전용
EMBEDDING_DIMENSIONS = 4096
UPSTAGE_EMBED_URL = "https://api.upstage.ai/v1/solar/embeddings"

# ★ corpus/ 는 컨테이너에 읽기 전용으로 마운트돼 있다(docker-compose.yml `:ro` -
#   원본 코퍼스를 실수로 건드리지 못하게 하는 의도적 제약). 임베딩 인덱스는 그
#   코퍼스에서 "파생된 출력물"이라 corpus/ 바깥, api/ 밑의 쓰기 가능한 위치에
#   저장한다(api/ 는 `./api:/app` 로 읽기-쓰기 마운트돼 있다).
EMBEDDING_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "embeddings"
_UPSTAGE_INDEX_PATH = EMBEDDING_DATA_DIR / "embedding_index_upstage_solar_large.npz"
# 로컬 인덱스는 실험 모듈이 만든 파일을 그대로 쓴다(재생성 불필요).
_LOCAL_INDEX_PATH = (Path(__file__).resolve().parents[1] / "data" / "local_embeddings"
                     / "local_index_e5-small-ko-v2.npz")
EMBEDDING_INDEX_PATH = _LOCAL_INDEX_PATH if EMBEDDING_PROVIDER == "local" else _UPSTAGE_INDEX_PATH

# 20건 소량 테스트로 실측(2026-08-02): 청크당 평균 407.6 토큰. 100건씩 묶어도
# 요청당 약 4만 토큰 수준이라 여유롭다 - 오히려 요청 "횟수"가 많을수록 레이트리밋
# (429)에 걸리기 쉬웠던 걸 실측으로 확인해서, 요청 수를 줄이는 쪽으로 배치를 키웠다.
BATCH_SIZE = 100
# 배치 사이 짧은 간격을 둔다 - 레이트리밋을 애초에 덜 만나게 하는 예방 조치
# (429 를 만나면 _embed_upstage() 가 별도로 재시도/백오프한다).
BATCH_PAUSE_SEC = 1.0


def _embed_upstage(
    texts: List[str], model: str, max_retries: int = 5, timeout: float = 60.0,
) -> Tuple[List[List[float]], int]:
    """Upstage Solar Embedding 호출 1건. (벡터 목록, 사용 토큰 수) 를 돌려준다.

    ★ 429(레이트리밋)는 재시도한다 - 새 계정/짧은 시간에 배치를 몰아서 보내면
      실제로 걸린다(2026-08-02 전체 인덱싱 중 실측). Retry-After 헤더가 있으면
      그 값을, 없으면 지수 백오프(2, 4, 8, 16, 32초)를 쓴다.
    ★ max_retries=1 이면 재시도 없이 즉시 실패한다 - 실시간 검색 경로
      (match_embedding_docs)가 쓰는 모드. 인덱싱(build_index)은 기본값(5)으로
      느긋하게 재시도한다 - 그쪽은 사용자가 기다리는 경로가 아니다.
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
            timeout=timeout,
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


_local_model = None


def _get_local_model():
    """로컬 임베딩 모델 싱글턴. 최초 1회만 로드한다(약 1.1GB 상주).

    ★ 기동 시점에 로드하지 않고 첫 질의 때 지연 로드한다 - 서버가 뜨는 속도를
      늦추지 않기 위해서다. 첫 질의만 모델 로드 시간(약 3초)이 더 걸린다.
    """
    global _local_model
    if _local_model is None:
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(int(__import__("os").cpu_count() or 1))
        log.info("[embeddings] 로컬 모델 로드: %s", LOCAL_EMBED_MODEL)
        _local_model = SentenceTransformer(LOCAL_EMBED_MODEL, device="cpu")
    return _local_model


def _embed_local(texts: List[str], input_type: str) -> Tuple[List[List[float]], int]:
    """로컬 모델로 임베딩한다. 외부로 나가는 요청이 전혀 없다."""
    prefix = LOCAL_QUERY_PREFIX if input_type == "query" else LOCAL_PASSAGE_PREFIX
    vecs = _get_local_model().encode([prefix + t for t in texts], normalize_embeddings=True)
    return [list(map(float, v)) for v in vecs], 0   # 토큰 과금이 없으므로 0


def embed_texts(
    texts: List[str], input_type: str, timeout: float = 60.0, max_retries: int = 5,
) -> Tuple[List[List[float]], int]:
    """텍스트 목록을 배치로 나눠 임베딩한다. input_type 은 'document'|'query'.

    ★★ 문서용/질의용을 여기서 정확히 갈라 쓴다 - 색인할 때(document)와
      검색할 때(query)를 절대 섞지 않는다. Upstage 는 모델 자체가 나뉘어 있고,
      로컬(e5 계열)은 접두어로 나뉜다. 둘 다 섞으면 검색 품질이 떨어진다.
    """
    if EMBEDDING_PROVIDER == "local":
        return _embed_local(texts, input_type)
    if EMBEDDING_PROVIDER != "upstage":
        raise NotImplementedError(f"미지원 임베딩 제공자: {EMBEDDING_PROVIDER}")
    model = EMBEDDING_MODEL_DOCUMENT if input_type == "document" else EMBEDDING_MODEL_QUERY

    import time as _time

    out: List[List[float]] = []
    total_tokens = 0
    n_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE
    for bi, i in enumerate(range(0, len(texts), BATCH_SIZE)):
        batch = texts[i : i + BATCH_SIZE]
        vectors, tokens = _embed_upstage(batch, model, max_retries=max_retries, timeout=timeout)
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

            # ★ 메타데이터가 0차원 스칼라로 저장된 경우와 1차원 배열인 경우가 둘 다
            #   있다(만든 도구가 다르다). 어느 쪽이든 값 하나를 꺼내도록 감싼다.
            def _meta(key, default=None):
                if key not in data:
                    return default
                a = data[key]
                return a.item() if getattr(a, "ndim", 0) == 0 else a[0]

            provider = str(_meta("provider", "unknown"))
            model = str(_meta("model", ""))
            dims = int(_meta("dimensions", data["vectors"].shape[1]))

            # ★ 기대값은 제공자별로 다르다. 로컬 인덱스는 실험 모듈이 만든 것이라
            #   provider 필드에 모델 별칭(e5-small-ko-v2)이 들어 있다.
            if EMBEDDING_PROVIDER == "local":
                want_provider, want_model, want_dims = "e5-small-ko-v2", LOCAL_EMBED_MODEL, LOCAL_EMBED_DIMENSIONS
            else:
                want_provider, want_model, want_dims = EMBEDDING_PROVIDER, EMBEDDING_MODEL_DOCUMENT, EMBEDDING_DIMENSIONS

            if provider != want_provider or model != want_model or dims != want_dims:
                log.warning(
                    "[embeddings] 인덱스 메타데이터 불일치(파일: provider=%s model=%s dim=%s / "
                    "기대: provider=%s model=%s dim=%s) - 다른 모델로 만든 인덱스는 쓰지 않는다. "
                    "임베딩 검색 0건으로 동작.",
                    provider, model, dims, want_provider, want_model, want_dims,
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
#   ★ 2026-08-04 로컬 전환: 모델이 바뀌면 유사도 분포도 달라져 임계값을 그대로
#     쓸 수 없다. e5-small-ko-v2 로 같은 방식(잡음/정상/경계 3분포)으로 재실측했다.
#       잡음 최고 0.5490 < 정상 최저 0.6820  → 그 사이 0.6155 를 min_score 로
#     (Upstage 값 0.45 는 아래에 보존 - 롤백 시 그대로 쓴다)
_MIN_SCORE_BY_PROVIDER = {"upstage": 0.45, "local": 0.6155}
EMBEDDING_MIN_SCORE = _MIN_SCORE_BY_PROVIDER[EMBEDDING_PROVIDER]

# ★ 실시간 검색(사용자 요청 경로) 전용 타임아웃 - 인덱싱과 다르다. 실측(10회 반복,
#   docs/evaluation/hybrid_search_report.md §0-1) 결과 API 왕복이 평균 110.6ms,
#   최대 333.9ms였다. 3초면 그 최댓값의 9배 여유가 있어 정상 응답을 절대 짧게
#   끊지 않으면서도, 사용자를 그 이상 기다리게 하지는 않는다. 재시도는 하지
#   않는다(max_retries=1) - 재시도하면 그만큼 더 기다리게 할 뿐이고, 실패하면
#   search.py 가 BM25 로 즉시 폴백하는 게 사용자 입장에서 더 빠르다.
QUERY_TIMEOUT_SEC = 3.0


class EmbeddingUnavailableError(Exception):
    """임베딩 검색을 쓸 수 없다(키 없음/인덱스 없음/API 실패/타임아웃 등).

    ★ 호출하는 쪽(search.py)이 이 예외를 잡아 BM25 로 즉시 폴백한다. 여기서
      예외를 삼키고 빈 리스트를 돌려주면 "임베딩이 정말 0건을 찾았다"와
      "임베딩 자체가 고장났다"를 구분할 수 없어 폴백이 불가능해진다.
    """


def match_embedding_docs(text: str, limit: int = 2, min_score: float = EMBEDDING_MIN_SCORE) -> List[tuple]:
    """질의 문장을 임베딩해 코사인 유사도로 가장 가까운 공식 문서를 찾는다.

    BM25 와 동일하게 청크 단위로 검색하고 문서(record_id) 단위로 최고점만 남긴다.
    반환값은 (score, OfficialDoc) 튜플 리스트다. 실패하면 빈 리스트가 아니라
    EmbeddingUnavailableError 를 던진다 - 위 클래스 docstring 참고.
    """
    # ★ 로컬 제공자는 API 키가 필요 없다 - 키 검사를 건너뛴다.
    if EMBEDDING_PROVIDER == "upstage" and not settings.has_embeddings:
        raise EmbeddingUnavailableError("UPSTAGE_API_KEY 가 설정되지 않았다")
    if not _INDEX.ready:
        raise EmbeddingUnavailableError("임베딩 인덱스 파일이 없거나 지금 설정과 맞지 않는다")

    try:
        vectors, _tokens = embed_texts(
            [text], input_type="query", timeout=QUERY_TIMEOUT_SEC, max_retries=1,
        )
        q_vec = vectors[0]
    except EmbeddingUnavailableError:
        raise
    except Exception as e:  # noqa: BLE001 - httpx 타임아웃/네트워크 오류/HTTP 오류 전부 포함
        raise EmbeddingUnavailableError(f"질의 임베딩 실패: {e}") from e

    q = np.array(q_vec, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        raise EmbeddingUnavailableError("질의 임베딩이 영벡터로 돌아왔다")
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
