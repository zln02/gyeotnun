import sys,csv,json,glob,math,collections; sys.path.insert(0,'/app')
from services import corpus_index as ci, embeddings as emb
from services.corpus_index import ScamCase
recs={}
for p in glob.glob('/corpus/public_data/gyeotnun_data/records_*.jsonl'):
    for l in open(p,encoding='utf-8'):
        r=json.loads(l); recs[r['id']]=r

print("="*74); print("1(b) 임베딩(코사인) — 코퍼스 크기 무관 확인"); print("="*74)
rows=[r for r in csv.DictReader(open('/corpus/곁눈_평가세트_120건.csv',encoding='utf-8-sig')) if r['입력채널']!='음성']
samp=[r for r in rows[:6]]
before={r['case_id']:[(round(s,6),d.id) for s,d in emb.match_embedding_docs(r['평가용_제시문구'],limit=3,min_score=-1)] for r in samp}
ORIG_OFF=list(ci.OFFICIAL_DOCS); ORIG_BYID=dict(ci._OFFICIAL_DOCS_BY_ID)
drop={d.id for d in ci.OFFICIAL_DOCS[:300]}
ci.OFFICIAL_DOCS[:] = [d for d in ORIG_OFF if d.id not in drop]
ci._OFFICIAL_DOCS_BY_ID.clear(); ci._OFFICIAL_DOCS_BY_ID.update({k:v for k,v in ORIG_BYID.items() if k not in drop})
same=0; tot=0
for r in samp:
    aft=[(round(s,6),d.id) for s,d in emb.match_embedding_docs(r['평가용_제시문구'],limit=3,min_score=-1)]
    b=[x for x in before[r['case_id']] if x[1] not in drop]
    for x,y in zip(b,aft):
        tot+=1
        if abs(x[0]-y[0])<1e-9: same+=1
ci.OFFICIAL_DOCS[:]=ORIG_OFF; ci._OFFICIAL_DOCS_BY_ID.clear(); ci._OFFICIAL_DOCS_BY_ID.update(ORIG_BYID)
print(f"  문서 300건 제거 전후, 남은 문서의 코사인 점수 일치: {same}/{tot}")
print("  → 코사인은 질의-문서 쌍마다 독립이라 코퍼스 크기와 무관하다. 안전.")

print(); print("="*74); print("1(a) BM25(공식문서 폴백) — N 의존 확인"); print("="*74)
from rank_bm25 import BM25Okapi
chunks=ci._OFFICIAL_CHUNKS
q=ci._bm25_tokenize("기초연금 신청 대상과 조건을 알려주세요")
for n in (500,1000,len(chunks)):
    bm=BM25Okapi([c.tokens for c in chunks[:n]])
    sc=sorted(bm.get_scores(q),reverse=True)[:3]
    print(f"  청크 {n:5}개 → 상위3 점수 {[round(x,2) for x in sc]}")
print(f"  BM25Okapi idf = log(N-df+0.5) - log(df+0.5)  ← N 의존")
print(f"  _OFFICIAL_MIN_SCORE = {ci._OFFICIAL_MIN_SCORE} (절대값)")
print("  → OFFICIAL_DOCS 수집도 같은 문제가 있다. 단 폴백 경로에서만 쓰인다.")

print(); print("="*74); print("2. 재교정 곡선 — 정상 오판 0 을 유지하는 최소 min_score"); print("="*74)
warn=sorted([d for d in ci.OFFICIAL_DOCS if recs.get(d.id,{}).get('data_type')=='warning_case'], key=lambda d:d.id)
def mk(d): 
    r=recs[d.id]
    return ScamCase(id=d.id,text=(r.get('content') or '')[:4000],source_label=r.get('source_agency',''),
        url=r.get('source_url',''),published_at=r.get('published_at'),risk_clues=[],error_types=[],
        questions=[],rationale='',origin='public_data_warning',_blob=f"{r.get('title','')} {r.get('content','')}")
ORIG_SC=list(ci.SCAM_CASES)
def set_n(n):
    add=[mk(d) for d in warn[:max(0,n-len(ORIG_SC))]]
    ci.SCAM_CASES[:]=ORIG_SC+add
    ci._SCAM_DOC_FREQ.clear(); ci._SCAM_DOC_FREQ.update(ci._doc_freq([c._blob for c in ci.SCAM_CASES]))
    ci._SCAM_N_DOCS=len(ci.SCAM_CASES)
    ci._scam_substring_df.cache_clear(); ci._case_categories.cache_clear()
def norm_rows(path):
    return [r for r in csv.DictReader(open(path,encoding='utf-8-sig'))
            if r['입력채널']!='음성' and r['기대판단']=='정상']
for label,path in (('확대112','/corpus/곁눈_평가세트_120건.csv'),
                   ('홀드30','/app/tests/fixtures/holdout/holdout_30.csv')):
    nr=norm_rows(path)
    print(f"\n  [{label}] 정상 {len(nr)}건")
    print(f"  {'N':>6}{'현 5.0 오판':>12}{'0 유지 최소 min_score':>24}{'log(N+1) 비':>14}")
    for n in (51,80,120,185):
        set_n(n)
        mis0=sum(1 for r in nr if ci.match_scam_cases(r['평가용_제시문구'],min_score=5.0))
        lo=None
        for th in [x/4 for x in range(20,61)]:
            if not any(ci.match_scam_cases(r['평가용_제시문구'],min_score=th) for r in nr):
                lo=th; break
        ratio = (math.log(n+1)/math.log(52)) if lo else 0
        print(f"  {n:>6}{mis0:>12}{(f'{lo:.2f}' if lo else '>15.0'):>24}{ratio:>14.3f}")
ci.SCAM_CASES[:]=ORIG_SC
ci._SCAM_DOC_FREQ.clear(); ci._SCAM_DOC_FREQ.update(ci._doc_freq([c._blob for c in ci.SCAM_CASES]))
ci._SCAM_N_DOCS=len(ci.SCAM_CASES)
