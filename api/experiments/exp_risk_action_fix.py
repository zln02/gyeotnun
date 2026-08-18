"""위험행동 탐지기 유형 정확도 수정안 측정 (2026-08-13)

실행: docker compose exec api python3 experiments/exp_risk_action_fix.py

★ services/ 를 고치지 않는다. 메모리에서만 바꿔 재고, 결과만 보고한다.

■ 왜 고치는가
  detect_risk_action 은 지금까지 urgency_pressure 강등 여부를 가르는 **이진 게이트**
  로만 쓰였다. 그래서 유형이 틀려도 무해했다. 그런데 화면이 유형을 말하기 시작하면
  **유형 오류가 곧 거짓말이 된다.**

    N17 (정상) "응급안전안심 장비를 설치해 드리는 서비스" → 앱설치로 검출
               화면에 "앱을 설치하라는 문자예요" 가 나가면 거짓이다
    B25/H40    "통장 사본을 보내 주세요"                  → 계좌이체로 검출
               화면에 "돈을 보내라는 내용이 있어요" 가 나가면 거짓이다

■ 수정 두 가지 — 둘 다 유형 정의에서 나온다. 평가셋 맞춤이 아니다.
  (가) 최장 매칭 우선
       dict 순서에 기대던 것을 없앤다. 겹치면 **더 구체적인(긴) 어휘**가 이긴다.
       "통장 사본"(5자) > "보내 주"(4자) → 개인정보요구.
       근거: 유형 정의상 '통장 사본을 보내라'는 개인정보 요구이지 자금 이체가 아니다.
  (나) 문맥 조건
       계좌이체 : "보내 주"류 일반 동사는 **금전 문맥**이 함께 있어야 한다.
                  ("입금·송금·이체" 처럼 그 자체가 금전 어휘인 것은 단독으로 인정)
       앱설치   : "설치하시/설치해" 류는 **소프트웨어 문맥**이 함께 있어야 한다.
                  ("앱 설치·다운로드" 처럼 자체로 소프트웨어인 것은 단독 인정)
       근거: 유형 이름이 '앱 설치'다. 장비 설치는 앱 설치가 아니다.

■ 채택 기준 (사람이 먼저 정해 둔 것)
  1) 정상(라벨 '없음') 케이스에서 유형 오검출 **0**
  2) 검출률과 유형일치율의 격차가 **홀드아웃에서도** 해소
  미달이면 화면에 유형을 명시하지 않고 매칭 구절 인용으로 간다.
"""
from __future__ import annotations

import csv
import sys

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import search  # noqa: E402

RISK = {"계좌이체", "앱설치", "인증번호", "개인정보요구"}
SETS = [("확대112", "/corpus/곁눈_평가세트_120건.csv"),
        ("홀드30", "/app/tests/fixtures/holdout/holdout_30.csv")]

# ── (나) 문맥 조건에 쓰는 어휘. 유형 정의에서 나온 것이지 평가셋에서 뽑지 않았다.
MONEY_CONTEXT = ["돈", "원을", "원 을", "만원", "만 원", "금액", "대금", "요금", "비용",
                 "계좌", "입금", "송금", "이체", "결제", "수수료", "보증금", "공탁금",
                 "합의금", "예치금", "선입금", "지급"]
SOFTWARE_CONTEXT = ["앱", "어플", "애플리케이션", "app", "APP", "앱스토어", "플레이스토어",
                    "다운로드", "프로그램", "apk", "APK", "파일", "링크"]

# 단독으로도 그 유형이 확실한 어휘 (문맥 조건 면제)
SELF_EVIDENT = {
    "계좌이체": {"입금", "송금", "이체", "선결제", "예치", "상환", "납부", "계좌로", "결제해"},
    "앱설치": {"앱을 설치", "앱 설치", "다운로드", "파일을 설치"},
}
CONTEXT_REQUIRED = {"계좌이체": MONEY_CONTEXT, "앱설치": SOFTWARE_CONTEXT}


def detect_fixed(text: str) -> tuple[str | None, str]:
    """수정안. (유형, 근거가 된 매칭 구절) 을 돌려준다.

    ★ 매칭 구절을 함께 돌려주는 것이 핵심이다 - 화면에 원문 구절을 그대로 인용해
      "유형 라벨이 어긋나도 사용자는 실제 구절을 본다"를 만들기 위해서다.
    """
    t = text or ""
    best_label, best_kw = None, ""
    for label, keywords in search.RISK_ACTION_KEYWORDS.items():
        for k in keywords:
            if k not in t:
                continue
            # ── (나) 문맥 조건
            if label in CONTEXT_REQUIRED and k not in SELF_EVIDENT.get(label, set()):
                if not any(c in t for c in CONTEXT_REQUIRED[label]):
                    continue
            # ── (가) 최장 매칭 우선
            if len(k) > len(best_kw):
                best_label, best_kw = label, k
    return best_label, best_kw


def load(p: str) -> list[dict]:
    return [r for r in csv.DictReader(open(p, encoding="utf-8-sig"))
            if r["입력채널"] != "음성"]


def main() -> None:
    print("=" * 78)
    print("유형 정확도 — 현재 vs 수정안")
    print("=" * 78)
    print(f"  {'':10}{'검출(있다/없다)':>22}{'유형까지 일치':>20}{'정상 과검출':>14}")
    agg = {"cur": [0, 0, 0], "fix": [0, 0, 0]}
    detail = []
    for name, path in SETS:
        rows = load(path)
        lab = [r for r in rows if r.get("위험행동") in RISK]
        norm = [r for r in rows if r["기대판단"] == "정상"]

        def stat(fn):
            hit = sum(1 for r in lab if fn(r["평가용_제시문구"])[0])
            exact = sum(1 for r in lab if fn(r["평가용_제시문구"])[0] == r["위험행동"])
            # ★ 채택 기준 1 - 정상인데 라벨이 '없음'인 건에서 유형이 잡히면 과검출
            over = [r["case_id"] for r in norm
                    if r.get("위험행동") == "없음" and fn(r["평가용_제시문구"])[0]]
            return hit, exact, over

        cur = stat(lambda t: (search.detect_risk_action(t), ""))
        fix = stat(detect_fixed)
        for k, v in (("cur", cur), ("fix", fix)):
            agg[k][0] += v[0]; agg[k][1] += v[1]; agg[k][2] += len(v[2])
        n = len(lab)
        print(f"  [{name}] 라벨 {n}건")
        print(f"    {'현재':10}{f'{cur[0]}/{n} ({cur[0]/n*100:.1f}%)':>22}"
              f"{f'{cur[1]}/{n} ({cur[1]/n*100:.1f}%)':>20}{f'{len(cur[2])}건 {cur[2]}':>14}")
        print(f"    {'수정안':10}{f'{fix[0]}/{n} ({fix[0]/n*100:.1f}%)':>22}"
              f"{f'{fix[1]}/{n} ({fix[1]/n*100:.1f}%)':>20}{f'{len(fix[2])}건 {fix[2]}':>14}")
        for r in lab + [x for x in norm if x.get("위험행동") == "없음"]:
            a = search.detect_risk_action(r["평가용_제시문구"])
            b, kw = detect_fixed(r["평가용_제시문구"])
            if a != b:
                detail.append((name, r["case_id"], r["유형"], r["기대판단"],
                               r.get("위험행동"), a, b, kw, r["평가용_제시문구"][:56]))

    tot = sum(len([r for r in load(p) if r.get("위험행동") in RISK]) for _, p in SETS)
    print(f"\n  [합계] 라벨 {tot}건")
    print(f"    현재   검출 {agg['cur'][0]}/{tot} ({agg['cur'][0]/tot*100:.1f}%) · "
          f"유형일치 {agg['cur'][1]}/{tot} ({agg['cur'][1]/tot*100:.1f}%) · "
          f"정상 과검출 {agg['cur'][2]}건")
    print(f"    수정안 검출 {agg['fix'][0]}/{tot} ({agg['fix'][0]/tot*100:.1f}%) · "
          f"유형일치 {agg['fix'][1]}/{tot} ({agg['fix'][1]/tot*100:.1f}%) · "
          f"정상 과검출 {agg['fix'][2]}건")

    print()
    print("=" * 78)
    print("바뀐 건 전수 (현재 → 수정안)")
    print("=" * 78)
    for name, cid, typ, exp, lab, a, b, kw, txt in detail:
        print(f"  [{name}] {cid} ({typ}/{exp}/라벨={lab})  {a} → {b}"
              f"{f'  근거구절={kw!r}' if kw else ''}")
        print(f"        {txt}")
    if not detail:
        print("  없음")

    print()
    print("=" * 78)
    print("채택 기준 대조")
    print("=" * 78)
    print(f"  1) 정상 유형 오검출 0        → 수정안 {agg['fix'][2]}건 "
          f"{'✅ 충족' if agg['fix'][2] == 0 else '❌ 미달'}")
    gap_ok = True
    for name, path in SETS:
        lab = [r for r in load(path) if r.get("위험행동") in RISK]
        h = sum(1 for r in lab if detect_fixed(r["평가용_제시문구"])[0])
        e = sum(1 for r in lab if detect_fixed(r["평가용_제시문구"])[0] == r["위험행동"])
        print(f"  2) [{name}] 검출 {h}/{len(lab)} vs 유형일치 {e}/{len(lab)} "
              f"→ 격차 {h - e}건 {'✅' if h == e else '❌'}")
        gap_ok = gap_ok and (h == e)
    print(f"\n  → 유형 명시 조건 {'충족' if agg['fix'][2] == 0 and gap_ok else '미달'}")
    print("\n※ 측정만 했다. services/ 를 고치지 않았다. 채택은 사람이 정한다.")


if __name__ == "__main__":
    main()
