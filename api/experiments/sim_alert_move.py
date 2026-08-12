"""경보문 이설 시뮬레이션 — 메모리에서만. 파일·인덱스 무변경."""
import sys,csv,json,glob,collections,importlib; sys.path.insert(0,'/app')
from services import corpus_index as ci
from services import search, embeddings as emb
from services.masking import mask_text
from urllib.parse import urlparse

recs={}
for p in glob.glob('/corpus/public_data/gyeotnun_data/records_*.jsonl'):
    for l in open(p,encoding='utf-8'):
        r=json.loads(l); recs[r['id']]=r

# ---- 현황
warn=[d for d in ci.OFFICIAL_DOCS if recs.get(d.id,{}).get('data_type')=='warning_case']
pres=[d for d in ci.OFFICIAL_DOCS if recs.get(d.id,{}).get('data_type')=='press_release']
lens=[len(recs[d.id].get('content','') or '') for d in warn]
lens.sort()
print(f"현재 SCAM_CASES {len(ci.SCAM_CASES)}건 / OFFICIAL_DOCS {len(ci.OFFICIAL_DOCS)}건")
print(f"이설 대상 warning_case {len(warn)}건 (press_release {len(pres)}건은 제외)")
print(f"  → SCAM_CASES {len(ci.SCAM_CASES)} + {len(warn)} = {len(ci.SCAM_CASES)+len(warn)}건 "
      f"({(len(ci.SCAM_CASES)+len(warn))/len(ci.SCAM_CASES):.1f}배)")
print(f"  → OFFICIAL_DOCS {len(ci.OFFICIAL_DOCS)} - {len(warn)} = {len(ci.OFFICIAL_DOCS)-len(warn)}건")
print(f"  이설 대상 길이: 최소 {lens[0]} 중앙 {lens[len(lens)//2]} 평균 {sum(lens)//len(lens)} 최대 {lens[-1]}자")
print(f"  현 SCAM_CASES 길이: 평균 {sum(len(c.text) for c in ci.SCAM_CASES)//len(ci.SCAM_CASES)}자")

# ---- 이설 상태 구성 (메모리)
from services.corpus_index import ScamCase
def blob(r):
    return f"{r.get('title','')} {r.get('content','')}"
new_cases=[]
for d in warn:
    r=recs[d.id]
    sc=ScamCase(id=d.id, text=(r.get('content') or r.get('title',''))[:4000],
                source_label=r.get('source_agency',''), url=r.get('source_url',''),
                published_at=r.get('published_at'), risk_clues=r.get('risk_types') or [],
                error_types=[], questions=[], rationale='', origin='public_data_warning',
                _blob=blob(r))
    new_cases.append(sc)

ORIG_SCAM=list(ci.SCAM_CASES); ORIG_OFF=list(ci.OFFICIAL_DOCS)
MOVED_IDS={d.id for d in warn}

ORIG_BYID = dict(ci._OFFICIAL_DOCS_BY_ID)

def apply_move(on):
    if on:
        ci.SCAM_CASES[:] = ORIG_SCAM + new_cases
        ci.OFFICIAL_DOCS[:] = [d for d in ORIG_OFF if d.id not in MOVED_IDS]
        # ★ 임베딩 경로가 쓰는 id->doc 사전도 함께 비워야 실제 이설과 같아진다.
        #   (이걸 빼먹으면 match_embedding_docs 가 옮긴 문서를 그대로 돌려준다)
        ci._OFFICIAL_DOCS_BY_ID.clear()
        ci._OFFICIAL_DOCS_BY_ID.update({k: v for k, v in ORIG_BYID.items() if k not in MOVED_IDS})
    else:
        ci.SCAM_CASES[:] = ORIG_SCAM
        ci.OFFICIAL_DOCS[:] = ORIG_OFF
        ci._OFFICIAL_DOCS_BY_ID.clear()
        ci._OFFICIAL_DOCS_BY_ID.update(ORIG_BYID)
    # 문서빈도 재계산 (match_scam_cases 가 쓰는 IDF)
    ci._SCAM_DOC_FREQ.clear()
    ci._SCAM_DOC_FREQ.update(ci._doc_freq([c._blob for c in ci.SCAM_CASES]))
    ci._SCAM_N_DOCS = len(ci.SCAM_CASES)

FRONT={'similar_scam_case','urgency_pressure','condition_omitted'}
RISK={'계좌이체','앱설치','인증번호','개인정보요구'}
RE={r['case_id']:r for r in csv.DictReader(open('/corpus/사칭_정답근거_재라벨_2026-08-12.csv',encoding='utf-8-sig'))}
def ukey(u):
    p=urlparse((u or '').strip())
    if not p.netloc: return ''
    b=(p.netloc.lower().replace('www.','')+p.path.rstrip('/')).lower()
    return f'{b}?{p.query}' if p.query else b
def build_keys():
    DK={}
    for d in ci.OFFICIAL_DOCS:
        k=ukey(d.source_url)
        if k: DK.setdefault(k,[]).append(d)
    return DK
def gold(row,DK):
    cid=row['case_id']
    if row['유형']=='사칭' and cid in RE:
        du=(RE[cid].get('정답doc_URL') or '').strip()
        if du:
            ids={d.id for d in DK.get(ukey(du),[])}
            if ids: return 'doc',ids
        return 'scam_only',set()
    u=(row.get('출처_URL') or '').strip()
    if not u: return 'no_ref',set()
    p=urlparse(u)
    if p.netloc and p.path.rstrip('/')=='' and not p.query: return 'none',set()
    k=ukey(u)
    if k in DK: return 'doc',{d.id for d in DK[k]}
    return 'scam',set()
def load(p):
    return [r for r in csv.DictReader(open(p,encoding='utf-8-sig')) if r['입력채널']!='음성']

def run(rows):
    DK=build_keys(); out=[]
    for r in rows:
        t=r['평가용_제시문구']
        res=search.collect_evidence(t)
        ms=ci.match_scam_cases(t)
        m=mask_text(t); it=[i.get('type') for i in (getattr(m,'items',None) or [])]
        tier=('danger' if ('account' in it or 'card' in it)
              else 'warn' if any(s.get('severity')=='attention' and s['key'] in FRONT for s in res.signals)
              else 'hold' if res.verdict_hint!='needs_check' else 'ok')
        kind,g=gold(r,DK)
        try: ids=[d.id for _,d in emb.match_embedding_docs(t,limit=5)]
        except Exception: ids=[]
        out.append({'id':r['case_id'],'유형':r['유형'],'기대판단':r['기대판단'],
                    '위험행동':r.get('위험행동','없음'),'kind':kind,'tier':tier,
                    'hint':res.verdict_hint,'nscam':len(ms),
                    'found':bool(ids),'hit':bool(g&set(ids))})
    return out

def summary(o):
    doc=[c for c in o if c['kind']=='doc']
    nor=[c for c in o if c['기대판단']=='정상']
    w=lambda c:c['tier'] in ('danger','warn')
    ry=[c for c in o if c['위험행동'] in RISK]; rn=[c for c in o if c['위험행동']=='없음']
    return {'정상오판':(sum(w(c) for c in nor),len(nor)),
            '사칭경고':(sum(w(c) for c in o if c['유형']=='사칭'),sum(1 for c in o if c['유형']=='사칭')),
            '검색성공':(sum(c['found'] for c in doc),len(doc)),
            'Top5':(sum(c['hit'] for c in doc),len(doc)),
            '축2있음':(sum(w(c) for c in ry),len(ry)),
            '축2없음':(sum(w(c) for c in rn),len(rn)),
            'tier':dict(collections.Counter(c['tier'] for c in o)),
            '사기매칭건':sum(1 for c in o if c['nscam']),
            '정상사기매칭':sum(1 for c in nor if c['nscam'])}
def pc(t): a,b=t; return f'{a}/{b}' + (f' ({a/b*100:.1f}%)' if b else '')

for name,path in (('확대 112건','/corpus/곁눈_평가세트_120건.csv'),
                  ('홀드아웃 30건','/app/tests/fixtures/holdout/holdout_30.csv')):
    rows=load(path)
    apply_move(False); before=run(rows); sb=summary(before)
    apply_move(True);  after=run(rows);  sa=summary(after)
    apply_move(False)
    print(f"\n{'='*72}\n[{name}]\n{'='*72}")
    print(f"  {'지표':16}{'현재':>20}{'이설 후':>20}")
    for k in ('정상오판','사칭경고','검색성공','Top5','축2있음','축2없음'):
        print(f"  {k:16}{pc(sb[k]):>20}{pc(sa[k]):>20}")
    print(f"  {'사기사례 매칭건':16}{sb['사기매칭건']:>20}{sa['사기매칭건']:>20}")
    print(f"  {'★정상에 사기매칭':16}{sb['정상사기매칭']:>20}{sa['정상사기매칭']:>20}")
    print(f"  tier 현재 {sb['tier']}\n  tier 이설 {sa['tier']}")
    ch=[(b['id'],b['tier'],a['tier']) for b,a in zip(before,after) if b['tier']!=a['tier']]
    print(f"  ★ tier 변경 {len(ch)}건: {ch}")
    for tgt in ('S22','S12','S18','S28','H23','H27'):
        b=next((x for x in before if x['id']==tgt),None); a=next((x for x in after if x['id']==tgt),None)
        if b: print(f"    {tgt}: {b['tier']}({b['hint']}) -> {a['tier']}({a['hint']})  scam매칭 {b['nscam']}->{a['nscam']}")
