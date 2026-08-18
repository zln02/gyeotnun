"""기관 도메인 대조 - 전수 발동 측정 (2026-08-16)
실행: docker compose exec api python3 experiments/exp_org_domain_measure.py

★ 재는 것은 딱 둘이다.
    1) 노린 유형(S03·S08)에 발동하는가
    2) **정상 문자에 단 1건이라도 발동하는가**  ← 이게 0 이 아니면 채택할 수 없다

★ 네트워크를 타지 않는다. expanded=None 으로 대조한다 - 즉 **본문의 주소만으로**
  재는, 가장 발동이 넓은(= 가장 불리한) 조건이다. 펼치기가 붙으면 침묵만 늘어난다.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)
from services import org_domain  # noqa: E402

CORPUS = Path("/corpus")
SETS = [
    ("확대 평가셋 112건", CORPUS / "곁눈_평가세트_120건.csv", "평가용_제시문구", True),
    ("홀드아웃 30건", Path("/app/tests/fixtures/holdout/holdout_30.csv"), "평가용_제시문구", True),
    ("실사용 11건", CORPUS / "real_sms_normal_11.csv", "평가용_제시문구", False),
]

print(f"매핑표: 발동 대상 {len(org_domain.ORGS)}곳 / "
      f"알려진 공식 도메인 {len(org_domain.KNOWN_DOMAINS)}개\n")

for title, path, col, drop_voice in SETS:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    if drop_voice:
        rows = [r for r in rows if r.get("입력채널") != "음성"]
    fired: list[tuple[str, str, str]] = []
    per_label = Counter()
    mention_no_url = 0
    for r in rows:
        text = r[col]
        cid = r["case_id"]
        label = r.get("유형", "?")
        sig = org_domain.build_signal(text, None)
        if sig:
            fired.append((cid, label, sig["label"]))
            per_label[label] += 1
        elif org_domain.find_org(text) and not org_domain.extract_domains(text):
            mention_no_url += 1

    print(f"■ {title} (n={len(rows)})")
    print(f"  발동 {len(fired)}건" + (f"  {dict(per_label)}" if per_label else ""))
    print(f"  ★ 기관명은 있는데 주소가 없어 발동 안 함: {mention_no_url}건")
    for cid, label, msg in fired:
        print(f"    {cid:<5} [{label}] {msg}")
    normal = [f for f in fired if f[1] in ("정상",)]
    print(f"  ★★ 정상 문자 발동: {len(normal)}건"
          + ("  ← 0 이 아니면 채택 불가" if normal else "  (통과)"))
    print()
