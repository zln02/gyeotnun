"""
공식 문서(OFFICIAL_CHUNKS) 임베딩 인덱스 배치 빌드 (Upstage Solar Embedding)

실행:
  cd api && python3 tools/build_embedding_index.py --sample 20   # 먼저 소량으로 검증
  cd api && python3 tools/build_embedding_index.py               # 전체 인덱싱

★ 이 스크립트만 임베딩 API 를 호출해 실제로 벡터를 만든다. 서버(main.py) 기동
  경로에는 이 로직이 없다 - 매번 재임베딩하면 비용·시간 낭비이기 때문에 사람이
  필요할 때만 명시적으로 돌린다(코퍼스가 바뀌었을 때 등).
★ --sample N 은 실제 인덱스 파일을 저장하지 않는다(전체 인덱스와 섞이면 안 되므로
  별도 위치에 저장한다) - 응답 형식·차원수·에러 처리와 실제 토큰 사용량만 확인하는
  용도다. 소량 테스트가 끝나면 --sample 없이 다시 돌려 전체를 인덱싱한다.

사전 조건: .env 에 UPSTAGE_API_KEY 설정. 코퍼스(corpus/public_data/gyeotnun_data/
records_merged.jsonl)가 로컬에 있어야 한다(corpus_index.py 가 이걸 읽어
OFFICIAL_CHUNKS 를 만든다).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # api/ 를 import 경로에 추가
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from config import settings  # noqa: E402
from services import corpus_index, embeddings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample", type=int, default=0,
        help="이 개수만큼만 청크를 뽑아 시험 인덱싱한다(파일 저장 안 함, 검증용).",
    )
    args = parser.parse_args()

    if not settings.has_embeddings:
        print("UPSTAGE_API_KEY 가 없습니다. .env 에 설정한 뒤 다시 실행하세요.")
        sys.exit(1)

    all_chunks = corpus_index._OFFICIAL_CHUNKS
    if not all_chunks:
        print("OFFICIAL_CHUNKS 가 0건입니다 - 공식 문서 코퍼스가 로컬에 있는지 확인하세요.")
        sys.exit(1)

    if args.sample > 0:
        chunks = all_chunks[: args.sample]
        print(f"[소량 테스트 모드] {len(chunks)}건만 임베딩합니다 (전체 {len(all_chunks)}건 중).")
        print("이 모드는 인덱스 파일을 저장하지 않습니다 - 응답 형식/차원수/토큰 사용량만 확인합니다.\n")

        texts = [c.text for c in chunks]
        t0 = time.time()
        vectors, tokens = embeddings.embed_texts(texts, input_type="document")
        dt = time.time() - t0

        print(f"\n결과: {len(vectors)}개 벡터, 차원={len(vectors[0]) if vectors else 0}, "
              f"사용 토큰={tokens:,}, 소요 시간={dt:.1f}초")
        if vectors:
            avg_tokens_per_chunk = tokens / len(vectors)
            total_chars = sum(len(c.text) for c in all_chunks)
            sample_chars = sum(len(c.text) for c in chunks)
            est_ratio = tokens / sample_chars if sample_chars else 0
            est_total_tokens = int(total_chars * est_ratio)
            est_cost = est_total_tokens / 1_000_000 * 0.10
            print(f"청크당 평균 토큰: {avg_tokens_per_chunk:.1f}")
            print(f"실측 비율(토큰/글자): {est_ratio:.3f}")
            print(f"→ 전체 {len(all_chunks)}건({total_chars:,}자) 재추산: "
                  f"약 {est_total_tokens:,} 토큰, 약 ${est_cost:.3f}")
        return

    total_chars = sum(len(c.text) for c in all_chunks)
    print(f"청크 {len(all_chunks)}건, 총 {total_chars:,}자를 "
          f"{embeddings.EMBEDDING_PROVIDER}/{embeddings.EMBEDDING_MODEL_DOCUMENT} 로 임베딩합니다.")
    print(f"저장 위치: {embeddings.EMBEDDING_INDEX_PATH}")
    print("(전체 인덱싱 - 완료까지 몇 분 정도 걸릴 수 있습니다)\n")

    t0 = time.time()
    embeddings.build_index()
    dt = time.time() - t0
    print(f"\n완료. 소요 시간: {dt:.1f}초")


if __name__ == "__main__":
    main()
