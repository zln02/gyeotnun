"""A안 시뮬레이션 — 경보문이 근거로 매칭되면 attention 신호를 붙인다.
   OFFICIAL_DOCS 는 그대로. data_type 만 본다. 검색 대상 불변 → IDF 문제 없음."""
import sys,csv,collections; sys.path.insert(0,'/app')
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)
from services import corpus_index as ci, embeddings as emb, search
from services.masking import mask_text
ALERT_TYPES={'warning_case','press_release'}
FRONT={'similar_scam_case','urgency_pressure','condition_omitted'}
NEWKEY='alert_doc_matched'
RISK={'계좌이체','앱설치','인증번호','개인정보요구'}

def evaluate(text, plan_a, front_has_new):
    res=search.collect_evidence(text)
    signals=list(res.signals)
    if plan_a:
        # 근거로 붙은 공식문서 중 경보문이 있으면 attention 추가
        docs,_mode,_top = search.match_official_docs_safe(text)
        if any(getattr(d,'data_type','') in ALERT_TYPES for d in docs):
            signals.append({'key':NEWKEY,'severity':'attention',
                            'label':'이 글과 비슷한 수법을 경고하는 자료가 있습니다.'})
    risky=any(s['severity']=='attention' for s in signals)
    # verdict_hint 재계산 (collect_evidence 와 같은 순서)
    if not res.references: hint='no_source_found'
    elif risky: hint='partially_matched'
    else: hint=res.verdict_hint
    m=mask_text(text); it=[i.get('type') for i in (getattr(m,'items',None) or [])]
    keys=FRONT|({NEWKEY} if front_has_new else set())
    if 'account' in it or 'card' in it: tier='danger'
    elif any(s['severity']=='attention' and s['key'] in keys for s in signals): tier='warn'
    elif hint!='needs_check': tier='hold'
    else: tier='ok'
    return tier,hint

def load(p):
    return [r for r in csv.DictReader(open(p,encoding='utf-8-sig')) if r['입력채널']!='음성']

for name,path in (('확대 112건','/corpus/곁눈_평가세트_120건.csv'),
                  ('홀드아웃 30건','/app/tests/fixtures/holdout/holdout_30.csv')):
    rows=load(path)
    base=[evaluate(r['평가용_제시문구'],False,False) for r in rows]
    a_no=[evaluate(r['평가용_제시문구'],True,False) for r in rows]   # verdict.js 미수정
    a_yes=[evaluate(r['평가용_제시문구'],True,True) for r in rows]   # verdict.js 에 키 추가
    def stat(res):
        nor=[(r,x) for r,x in zip(rows,res) if r['기대판단']=='정상']
        sc=[(r,x) for r,x in zip(rows,res) if r['유형']=='사칭']
        ry=[(r,x) for r,x in zip(rows,res) if r.get('위험행동') in RISK]
        rn=[(r,x) for r,x in zip(rows,res) if r.get('위험행동')=='없음']
        w=lambda x:x[0] in ('danger','warn')
        return (sum(w(x) for _,x in nor),len(nor),sum(w(x) for _,x in sc),len(sc),
                sum(w(x) for _,x in ry),len(ry),sum(w(x) for _,x in rn),len(rn),
                dict(collections.Counter(x[0] for x in res)))
    print(f"\n{'='*74}\n[{name}]\n{'='*74}")
    print(f"  {'':28}{'현재':>16}{'A안(verdict.js 미수정)':>26}{'A안(키 추가)':>18}")
    labels=['정상 오판','사칭 경고','축2 있음','축2 없음']
    S=[stat(base),stat(a_no),stat(a_yes)]
    for i,lab in enumerate(labels):
        vals=[f"{s[i*2]}/{s[i*2+1]}" for s in S]
        print(f"  {lab:28}{vals[0]:>16}{vals[1]:>26}{vals[2]:>18}")
    for j,lab in enumerate(('현재','A안 미수정','A안 키추가')):
        print(f"  tier {lab:12}{S[j][8]}")
    for j,(lab,res) in enumerate((('A안 미수정',a_no),('A안 키추가',a_yes))):
        ch=[(r['case_id'],b[0],x[0]) for r,b,x in zip(rows,base,res) if b[0]!=x[0]]
        print(f"  ★ tier 변경({lab}) {len(ch)}건: {ch}")
    for tgt in ('S22','S12','S18','S28','H23','H27'):
        idx=[i for i,r in enumerate(rows) if r['case_id']==tgt]
        if idx:
            i=idx[0]
            print(f"    {tgt}: 현재 {base[i][0]}({base[i][1]}) → 미수정 {a_no[i][0]} → 키추가 {a_yes[i][0]}")
