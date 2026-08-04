"""
로컬 임베딩 실험 모듈 (2026-08, 8/2 멘토 지적 대응)
담당: 조희진(실험)

★ 이 모듈은 services/embeddings.py(Upstage, 상용 API) 를 대체하지 않는다.
  나란히 추가된 실험 경로다. 인덱스 파일도 완전히 분리한다
  (api/data/local_embeddings/ - 기존 api/data/embeddings/ 와 절대 안 섞는다.
  provider/model 이름이 다르면 벡터 차원도 달라 섞이면 조용히 깨진다).

★ "완전 폐쇄형"에 가장 가까운 조합: HuggingFace 모델을 최초 1회 내려받아
  로컬 디스크에 캐시해 두면, 이후 임베딩 계산은 프로세스 안에서 전부
  끝난다 - 질의든 색인이든 텍스트가 프로세스 밖으로 나가지 않는다
  (Upstage 는 질의마다 외부 API 호출이 필요하다는 점과 대조적이다).

후보 선정 기준: 한국어 성능 · 메모리. 두 개로 좁혔다.
  - multilingual-e5-small (intfloat) : 다국어 소형 모델(118M 파라미터,
    fp32 약 470MB), 한국어 포함 100+ 언어 지원. query/passage 프리픽스를
    붙여야 성능이 제대로 나온다(공식 권고) - services/embeddings.py 가
    Upstage 의 query/passage 모델을 분리해 쓴 것과 같은 이유로, 여기서도
    embed_query()/embed_passage() 를 분리했다.
  - ko-sroberta-multitask (jhgan)   : 한국어 전용 SBERT(약 443MB), 한국어
    커뮤니티에서 널리 쓰이는 베이스라인. 프리픽스 규약 없음.

두 후보 모두 requirements-local-experiment.txt 에만 있다 - 프로덕션에는
설치하지 않는다.
"""
from __future__ import annotations

import os
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import numpy as np

log = logging.getLogger("gyeotnun.local_embeddings")

Provider = Literal["e5-small", "ko-sroberta", "bge-m3", "bge-m3-ko", "e5-large", "koe5"]

_MODEL_NAMES = {
    "e5-small": "intfloat/multilingual-e5-small",
    "ko-sroberta": "jhgan/ko-sroberta-multitask",
    # ---- 2026-08-03 추가 후보 (서버 여유 12GB 확인 후, 모델 크기로 배제하지 않음)
    "bge-m3": "BAAI/bge-m3",                 # MIT, 한국어 검색 벤치마크 상위. dense 만 쓴다
    "bge-m3-ko": "dragonkue/BGE-m3-ko",      # 위를 한국어 파인튜닝(같은 아키텍처)
    "e5-large": "intfloat/multilingual-e5-large",
    "koe5": "nlpai-lab/KoE5",                # e5 계열 → 접두어 필수
}

# ★ e5 계열은 "query: "/"passage: " 접두어가 필수다(모델 카드 공식 권고).
#   안 붙이면 성능이 크게 떨어져서 "e5 가 별로다"라는 잘못된 결론이 난다.
#   bge-m3 계열은 반대로 접두어를 쓰지 않는다(붙이면 오히려 노이즈).
_NEEDS_E5_PREFIX = {"e5-small", "e5-large", "koe5"}

LOCAL_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "local_embeddings"

_models: dict[str, object] = {}


def _get_model(provider: Provider):
    if provider not in _models:
        import torch
        from sentence_transformers import SentenceTransformer

        # ★ CPU 스레드를 명시적으로 잡는다(2026-08-03 실측): 기본값으로 두면
        #   bge-m3 인덱싱 중 컨테이너에 3코어를 줬는데도 162% 밖에 안 쓰고
        #   배치당 104초가 걸렸다. torch 가 컨테이너의 cpu 제한을 못 읽고
        #   스레드를 적게 잡는 것이 원인이라, 가용 코어 수로 직접 지정한다.
        threads = int(os.getenv("EMBED_THREADS") or os.cpu_count() or 1)
        torch.set_num_threads(threads)
        log.info("[local_embeddings] torch CPU 스레드 %d 개로 설정", threads)

        # ★ 실행 장치 선택(2026-08-04): Linux 서버(CPU)와 Apple Silicon Mac(MPS)
        #   양쪽에서 같은 코드를 돌리기 위해 자동 감지한다. M 시리즈 Mac 에서는
        #   MPS(GPU)가 CPU 보다 수 배 빠르므로, 청크 크기 실험처럼 재인덱싱을
        #   반복하는 작업은 Mac 에서 돌리는 편이 훨씬 유리하다.
        #   EMBED_DEVICE 로 강제 지정할 수 있다(cpu/mps/cuda) - 결과 비교 시
        #   장치를 고정하고 싶을 때 쓴다.
        device = os.getenv("EMBED_DEVICE")
        if not device:
            if torch.backends.mps.is_available():
                device = "mps"
            elif torch.cuda.is_available():
                device = "cuda"
            else:
                device = "cpu"
        log.info("[local_embeddings] 실행 장치: %s", device)

        name = _MODEL_NAMES[provider]
        log.info("[local_embeddings] %s 모델 로드 중(최초 1회)...", name)
        model = SentenceTransformer(name, device=device)

        # ★ 청크 실측 토큰 길이는 최대 577(99%가 536 이하)이다. bge-m3 기본값
        #   8192 를 그대로 두면 불필요하게 긴 시퀀스를 가정하게 되므로 640 으로
        #   낮춘다 - 잘리는 청크가 하나도 없으면서 낭비를 줄이는 값이다.
        if getattr(model, "max_seq_length", 0) > 640:
            model.max_seq_length = 640
        _models[provider] = model
    return _models[provider]


def _prefix(provider: Provider, text: str, kind: Literal["query", "passage"]) -> str:
    """e5 계열에만 접두어를 붙인다(위 _NEEDS_E5_PREFIX 주석 참고).
    ko-sroberta·bge-m3 계열은 접두어 규약이 없으므로 원문 그대로 쓴다."""
    if provider in _NEEDS_E5_PREFIX:
        return f"{kind}: {text}"
    return text


def embed_query(text: str, provider: Provider = "e5-small") -> np.ndarray:
    model = _get_model(provider)
    vec = model.encode(_prefix(provider, text, "query"), normalize_embeddings=True)
    return np.asarray(vec, dtype=np.float32)


def embed_passages(texts: list[str], provider: Provider = "e5-small", batch_size: int = 32) -> np.ndarray:
    model = _get_model(provider)
    inputs = [_prefix(provider, t, "passage") for t in texts]
    vecs = model.encode(inputs, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=True)
    return np.asarray(vecs, dtype=np.float32)


def index_path(provider: Provider) -> Path:
    return LOCAL_DATA_DIR / f"local_index_{provider}.npz"


def build_index(chunks, provider: Provider = "e5-small") -> Path:
    """chunks: services.corpus_index._OFFICIAL_CHUNKS(OfficialChunk 객체 리스트)를
    그대로 받는다 - chunk_id/record_id/text 속성만 읽는다(같은 원본 코퍼스를
    쓰되, 결과 인덱스 파일은 완전히 분리한다)."""
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    texts = [c.text for c in chunks]
    t0 = time.perf_counter()
    vectors = embed_passages(texts, provider=provider)
    elapsed = time.perf_counter() - t0
    path = index_path(provider)
    np.savez_compressed(
        path,
        vectors=vectors,
        chunk_ids=np.array([c.chunk_id for c in chunks]),
        record_ids=np.array([c.record_id for c in chunks]),
        provider=provider,
        model=_MODEL_NAMES[provider],
        dimensions=vectors.shape[1],
    )
    log.info("[local_embeddings] 색인 완료: %d개 청크, %.1f초, %s", len(chunks), elapsed, path)
    return path


@dataclass
class LocalIndex:
    provider: Provider
    ready: bool = False
    vectors: Optional[np.ndarray] = None
    chunk_ids: Optional[np.ndarray] = None
    record_ids: Optional[np.ndarray] = None

    @classmethod
    def load(cls, provider: Provider) -> "LocalIndex":
        path = index_path(provider)
        if not path.exists():
            log.warning("[local_embeddings] 인덱스 파일 없음: %s (build_index() 먼저 실행)", path)
            return cls(provider=provider, ready=False)
        data = np.load(path, allow_pickle=False)
        # ★ provider 뿐 아니라 모델명·차원수까지 확인한다. 모델이 다르면 벡터 공간이
        #   달라서, 섞이면 검색이 조용히 망가진다(에러 없이 엉뚱한 결과가 나온다).
        if str(data["provider"]) != provider:
            log.warning("[local_embeddings] provider 불일치 - 인덱스 사용 안 함")
            return cls(provider=provider, ready=False)
        if str(data["model"]) != _MODEL_NAMES[provider]:
            log.warning("[local_embeddings] 모델명 불일치(%s != %s) - 인덱스 사용 안 함",
                        data["model"], _MODEL_NAMES[provider])
            return cls(provider=provider, ready=False)
        if int(data["dimensions"]) != data["vectors"].shape[1]:
            log.warning("[local_embeddings] 차원수 메타와 실제 벡터가 불일치 - 인덱스 사용 안 함")
            return cls(provider=provider, ready=False)
        return cls(
            provider=provider, ready=True,
            vectors=data["vectors"], chunk_ids=data["chunk_ids"], record_ids=data["record_ids"],
        )

    def search_docs(self, query_vec: np.ndarray, limit: int = 2, min_score: float = 0.0) -> list[tuple[float, str]]:
        """[(유사도, record_id), ...] 문서 단위 상위 limit개, 유사도 내림차순.

        ★ services/embeddings.py match_embedding_docs() 와 같은 방식이어야 비교가
          공정하다: 전체 청크에 대해 유사도를 구한 뒤 문서(record_id)별 최고점만
          남기고, 그 다음에 문서 단위로 정렬·절단한다. (상위 K개 청크를 먼저
          자르고 문서로 묶으면, 최고 청크가 K위 밖인 문서를 놓친다.)
        ★ min_score 는 '이 정도도 안 되면 근거로 보여주지 않는다'는 잡음 바닥이다 -
          이게 없으면 어떤 입력에도 최근접 문서가 항상 나와서 "근거를 찾았다"가
          무의미해진다.
        """
        if not self.ready:
            return []
        sims = self.vectors @ query_vec
        best_per_doc: dict[str, float] = {}
        for record_id, sim in zip(self.record_ids, sims):
            rid = str(record_id)
            s = float(sim)
            if s <= 0:
                continue
            if rid not in best_per_doc or s > best_per_doc[rid]:
                best_per_doc[rid] = s
        scored = [(s, rid) for rid, s in best_per_doc.items() if s >= min_score]
        scored.sort(key=lambda x: -x[0])
        return scored[:limit]
