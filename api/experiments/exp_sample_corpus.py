"""샘플 코퍼스 조사 — 라이선스가 확인된 문서만으로 검색이 도는가 (2026-08-22)

실행: docker compose exec -T api python3 experiments/exp_sample_corpus.py

★ 조사만 한다. 운영 인덱스도 corpus 도 건드리지 않는다.
  임시 인덱스는 /tmp 에만 쓰고 끝나면 지운다.

■ 무엇을 고르나
  records_merged.jsonl 의 `license` 필드가 **"이용허락범위 제한 없음"** 인 것만.
  ★ "확인 필요" 는 한 건도 넣지 않는다(지시).
  ★ 홀드아웃 30건의 정답 근거 URL 과 겹치는 문서는 뺀다 — 넣으면 홀드아웃이
    검색 코퍼스에 들어가는 것과 같아진다.

■ 무엇을 재나
  (1) 문서 수 · 청크 수 · 원본 크기
  (2) 로컬 임베딩 색인 생성 시간
  (3) 색인 파일 크기
  (4) 확대 112건 중 몇 건이 근거를 찾는가 (전체 코퍼스일 때와 나란히)
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

import numpy as np  # noqa: E402

from services import corpus_index as ci  # noqa: E402
from services import embeddings as emb  # noqa: E402
from services import search  # noqa: E402
from services.masking import mask_text  # noqa: E402

RECORDS = Path("/corpus/public_data/gyeotnun_data/records_merged.jsonl")
EVAL = Path("/corpus/곁눈_평가세트_120건.csv")
HOLD = Path("/app/tests/fixtures/holdout/holdout_30.csv")
CLEAR = "이용허락범위 제한 없음"
TMP_INDEX = Path("/tmp/sample_corpus_index.npz")


def gold_url(row: dict) -> str:
    return (row.get("정답근거_URL") or row.get("출처_URL") or "").strip()


def main() -> None:
    records = [json.loads(l) for l in RECORDS.open(encoding="utf-8") if l.strip()]
    hold_urls = {gold_url(r) for r in csv.DictReader(HOLD.open(encoding="utf-8-sig"))}
    hold_urls.discard("")

    clear = [r for r in records if r.get("license") == CLEAR]
    sample = [r for r in clear if (r.get("source_url") or "").strip() not in hold_urls]
    dropped = len(clear) - len(sample)

    print(f"전체 코퍼스        {len(records)}건")
    print(f"라이선스 명확       {len(clear)}건  ('{CLEAR}')")
    print(f"홀드아웃 겹침 제외   -{dropped}건")
    print(f"★ 샘플 코퍼스       {len(sample)}건")
    raw = sum(len(json.dumps(r, ensure_ascii=False)) for r in sample)
    print(f"   원본 JSONL 크기   {raw/1024:.0f} KB")
    print()

    # ── 샘플만으로 OFFICIAL_DOCS 재구성
    ids = {r["id"] for r in sample}
    sub_docs = [d for d in ci.OFFICIAL_DOCS if d.id in ids]
    sub_chunks = ci._rechunk_official_docs(sub_docs)
    print(f"   문서 {len(sub_docs)}건 → 청크 {len(sub_chunks)}개 "
          f"(전체는 {len(ci.OFFICIAL_DOCS)}건 / {len(ci._OFFICIAL_CHUNKS)}개)")
    print()

    # ── 색인 생성 시간
    print("■ 로컬 임베딩 색인 생성")
    t0 = time.perf_counter()
    vecs, _ = emb.embed_texts([c.text for c in sub_chunks], "passage")
    arr = np.asarray(vecs, dtype=np.float32)
    build_sec = time.perf_counter() - t0
    # ★ 메타데이터를 저장 규약대로 넣는다. 안 넣으면 EmbeddingIndex 의 3중 검증이
    #   거부하고 BM25 로 조용히 폴백해, 재는 대상이 바뀐다(첫 시도에서 실제로 그랬다).
    mp, mm = emb._index_metadata()
    np.savez_compressed(
        TMP_INDEX, vectors=arr,
        chunk_ids=np.array([c.chunk_id for c in sub_chunks]),
        record_ids=np.array([c.record_id for c in sub_chunks]),
        provider=np.array([mp]), model=np.array([mm]),
        dimensions=np.array([arr.shape[1]]),
    )
    size_kb = TMP_INDEX.stat().st_size / 1024
    print(f"   생성 {build_sec:.1f}초  ({len(sub_chunks)}청크 · {arr.shape[1]}차원)")
    print(f"   색인 파일 {size_kb:.0f} KB")
    print()

    # ── 검색 성공률 (전체 vs 샘플)
    rows = [r for r in csv.DictReader(EVAL.open(encoding="utf-8-sig"))
            if r["입력채널"] != "음성"]

    def measure(label: str) -> None:
        """★ '근거를 붙였다' 만으로는 부족하다. **확신 상태의 오답 근거**가
        0건으로 유지되는지가 채택 조건이다 - 코퍼스가 작아지면 어중간하게
        비슷한 문서가 top-1 으로 올라와 확신 임계를 넘을 수 있다."""
        found, fell_back, confident_wrong = 0, 0, 0
        wrong_cases: list = []
        for r in rows:
            t = mask_text(r["평가용_제시문구"]).text
            try:
                emb.match_embedding_docs(t, limit=1)
            except emb.EmbeddingUnavailableError:
                fell_back += 1
            ev = search.collect_evidence(t)
            if ev.references:
                found += 1
            # 확신(needs_check)인데 정답 URL 이 참조에 없으면 오답 근거
            gold = gold_url(r)
            if ev.verdict_hint == "needs_check" and ev.references and gold:
                urls = {(x.get("url") or "").strip() for x in ev.references}
                if gold not in urls:
                    confident_wrong += 1
                    wrong_cases.append((r["case_id"], r["유형"],
                                        [x.get("title","")[:34] for x in ev.references]))
        flag = "  ★ 임베딩 폴백 %d건 - 측정 무효" % fell_back if fell_back else ""
        print(f"   {label:<12} 근거를 붙인 건 {found}/{len(rows)}"
              f"   ★ 확신 오답 근거 {confident_wrong}건{flag}")
        for cid, typ, titles in wrong_cases:
            print(f"        ★ {cid} [{typ}] → {titles}")

    print("■ 확대 112건 — 근거를 찾는가")
    measure("전체 코퍼스")

    # 샘플만 남기고 재측정 (프로세스 안에서만 교체, 파일은 안 건드린다)
    keep_docs, keep_chunks = ci.OFFICIAL_DOCS, ci._OFFICIAL_CHUNKS
    keep_idx = emb._INDEX
    try:
        ci.OFFICIAL_DOCS, ci._OFFICIAL_CHUNKS = sub_docs, sub_chunks
        ci._rebuild_bm25() if hasattr(ci, "_rebuild_bm25") else None
        emb._INDEX = emb.EmbeddingIndex(TMP_INDEX)
        measure("샘플 코퍼스")
    finally:
        ci.OFFICIAL_DOCS, ci._OFFICIAL_CHUNKS = keep_docs, keep_chunks
        emb._INDEX = keep_idx
        os.remove(TMP_INDEX)
        print("\n   ★ 임시 색인 삭제 · 운영 인덱스/코퍼스 무변경")


if __name__ == "__main__":
    main()
