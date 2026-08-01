"""
임베딩 검색 응답시간 분해 실측 (API 왕복 vs 로컬 코사인 검색 vs BM25 비교).
실행: docker compose cp tests/timing_breakdown.py gyeotnun-api:/app/timing_breakdown.py
      && docker compose exec api python /app/timing_breakdown.py
결과는 docs/evaluation/hybrid_search_report.md §0-1 에 반영돼 있다.
"""
import sys, time, statistics
sys.path.insert(0, '/app')
from services import embeddings, corpus_index as ci

text = '농어가목돈마련저축 저축장려금 지급 안내입니다.'

# 1) 임베딩 API 왕복 시간만 (embed_texts 호출 자체)
api_times = []
for _ in range(10):
    t0 = time.perf_counter()
    vectors, tokens = embeddings.embed_texts([text], input_type='query')
    api_times.append((time.perf_counter() - t0) * 1000)

# 2) 로컬 벡터 검색(코사인 유사도 계산)만 - 이미 임베딩된 벡터로
import numpy as np
q = np.array(vectors[0], dtype=np.float32)
q = q / np.linalg.norm(q)
local_times = []
for _ in range(10):
    t0 = time.perf_counter()
    sims = embeddings._INDEX.vectors @ q
    local_times.append((time.perf_counter() - t0) * 1000)

# 3) match_embedding_docs() 전체(=API 왕복 + 로컬 검색) - 실제 함수 그대로
full_times = []
for _ in range(10):
    t0 = time.perf_counter()
    embeddings.match_embedding_docs(text)
    full_times.append((time.perf_counter() - t0) * 1000)

print(f"[임베딩 API 왕복만] 평균 {statistics.mean(api_times):.1f}ms, 중앙값 {statistics.median(api_times):.1f}ms, 최소 {min(api_times):.1f}ms, 최대 {max(api_times):.1f}ms")
print(f"[로컬 코사인유사도 검색만] 평균 {statistics.mean(local_times):.3f}ms")
print(f"[match_embedding_docs() 전체] 평균 {statistics.mean(full_times):.1f}ms, 중앙값 {statistics.median(full_times):.1f}ms, 최소 {min(full_times):.1f}ms, 최대 {max(full_times):.1f}ms")

# 4) BM25 로컬 검색 시간 (비교용)
bm25_times = []
for _ in range(10):
    t0 = time.perf_counter()
    ci.match_official_docs(text)
    bm25_times.append((time.perf_counter() - t0) * 1000)
print(f"[BM25 검색 전체] 평균 {statistics.mean(bm25_times):.2f}ms")
