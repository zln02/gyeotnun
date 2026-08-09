#!/usr/bin/env python3
"""로컬 OCR 평가용 카카오톡 화면 데이터셋 생성기.

⚠️ 한계 — 반드시 읽을 것
   여기서 만드는 이미지는 합성이다. 실제 스마트폰으로 찍은 캡처보다 깨끗하다.
   따라서 이 데이터셋의 정확도는 실사용 정확도의 상한에 가깝다.
   실제 폰 캡처로도 반드시 교차 확인해야 한다.

   대신 아래는 확보된다:
   - 조건 다양성 (라이트/다크 · 글자 크기 · 말풍선 잘림 · 화질 저하)
   - 정답 텍스트 (생성 시점에 알고 있으므로 100% 정확)

개인정보: 등장하는 이름·전화번호·계좌번호는 전부 가공값이다.
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import glob, json, os, random, io
from collections import Counter

random.seed(20260803)

OUT = "images"
os.makedirs(OUT, exist_ok=True)

def _font(*pats):
    for pat in pats:
        hits = glob.glob(pat, recursive=True)
        if hits:
            return hits[0]
    raise SystemExit(
        "한글 폰트를 찾지 못했습니다. 아래로 설치하세요:\n"
        "  sudo apt-get update && sudo apt-get install -y fonts-noto-cjk\n"
        "설치 후 다시 실행하면 됩니다.")


_B = _font("/usr/share/fonts/**/NotoSansCJK*Bold*",
           "/usr/share/fonts/**/NotoSansKR*Bold*",
           "/usr/share/fonts/**/NanumGothicBold*")
_R = _font("/usr/share/fonts/**/NotoSansCJK*Regular*",
           "/usr/share/fonts/**/NotoSansKR*Regular*",
           "/usr/share/fonts/**/NanumGothic.ttf")

THEMES = {
    "light": dict(
        bg=(0xB2, 0xC7, 0xDA), header=(0x9B, 0xB2, 0xC8),
        bubble=(0xFF, 0xFF, 0xFF), mine=(0xFE, 0xE5, 0x00),
        ink=(0x1A, 0x1A, 0x1A), sub=(0x55, 0x60, 0x6B),
        time=(0x6B, 0x77, 0x84), inputbar=(0xFF, 0xFF, 0xFF),
        inputbox=(0xF1, 0xF3, 0xF5), placeholder=(0x9A, 0xA3, 0xAD),
        datepill=(0x8F, 0xA6, 0xBB), status=(0x22, 0x2A, 0x33),
    ),
    "dark": dict(
        bg=(0x1B, 0x1D, 0x1F), header=(0x24, 0x26, 0x29),
        bubble=(0x33, 0x36, 0x3A), mine=(0xFE, 0xE5, 0x00),
        ink=(0xE9, 0xEA, 0xEB), sub=(0x9A, 0x9E, 0xA3),
        time=(0x7A, 0x7F, 0x86), inputbar=(0x24, 0x26, 0x29),
        inputbox=(0x33, 0x36, 0x3A), placeholder=(0x76, 0x7A, 0x80),
        datepill=(0x3A, 0x3E, 0x43), status=(0xD6, 0xD8, 0xDA),
    ),
}

AVATAR_COLORS = [(0xE8, 0x8C, 0x7A), (0x7A, 0xA8, 0xE8), (0x8C, 0xC0, 0x8A),
                 (0xC8, 0x9B, 0xD8), (0xE8, 0xC0, 0x7A)]

SCENARIOS = [
    dict(id="s01", label="사칭", room="행복한 동창 모임",
         msgs=[("김영자", ["이거 우리도 받을 수 있대요!"]),
               ("김영자", ["[정부지원] 어르신 생활안정 지원금 안내",
                          "2026년 미신청자 대상 최대 300만원",
                          "신청기한 : 오늘까지 (선착순 마감)",
                          "신청문의 010-4821-7365",
                          "접수계좌 국민 612301-04-238877",
                          "신청링크 bit.ly/2n9xqAa"]),
               ("나", ["진짜인가요?"])]),
    dict(id="s02", label="사칭", room="택배 알림",
         msgs=[("배송센터", ["[택배] 주소 불일치로 배송이 보류되었습니다.",
                            "아래에서 주소를 다시 입력해 주세요.",
                            "hxxp://kr-parcel-check.net/rq"])]),
    dict(id="s03", label="경계", room="카드 안내",
         msgs=[("카드사", ["해외 결제 승인 안내",
                          "승인금액 89,000원",
                          "본인이 아닐 경우 아래로 확인해 주시기 바랍니다.",
                          "hxxp://card-secure-kr.com/chk"])]),
    dict(id="s04", label="정상", room="건강보험 안내",
         msgs=[("건강보험공단", ["2026년 일반건강검진 대상자 안내",
                                "올해 검진 대상이십니다.",
                                "가까운 검진기관에서 12월 31일까지 받으실 수 있습니다.",
                                "문의는 공단 대표번호로 연락해 주세요."])]),
    dict(id="s05", label="정상", room="국민연금 안내",
         msgs=[("국민연금공단", ["연금 수급 관련 안내문을 우편으로 발송하였습니다.",
                                "내용 확인 후 문의사항은 공단 대표번호로 연락 주시기 바랍니다."])]),
    dict(id="s06", label="경계", room="우리 아파트 주민방",
         msgs=[("박순희", ["시청에서 이런 게 왔는데 진짜일까요?"]),
               ("박순희", ["[○○시청] 어르신 생활안정 지원금 신청 안내",
                          "대상자에 한해 신청을 받고 있습니다.",
                          "자세한 내용은 아래에서 확인하세요.",
                          "hxxp://city-support-kr.info"]),
               ("최명자", ["저도 어제 받았어요"])]),
    dict(id="s07", label="사칭", room="010-2938-4471",
         msgs=[("모르는 번호", ["엄마 나야 폰이 고장나서 컴퓨터로 보내",
                               "지금 급하게 결제할 게 있는데",
                               "잠깐만 도와줄 수 있어?"])]),
    dict(id="s08", label="사칭", room="건강정보 나눔",
         msgs=[("이순자", ["이거 드시고 당뇨 나았대요"]),
               ("이순자", ["관절 통증 3일 만에 사라지는 비법",
                          "병원에서도 못 고친 통증이 사라집니다",
                          "지금 주문하면 50% 할인",
                          "상담 070-8412-9930"])]),
    dict(id="s09", label="사칭", room="금융 안내",
         msgs=[("○○캐피탈", ["정부지원 저금리 대환대출 안내",
                             "최대 5,000만원 한도 연 2.9%",
                             "무직자 주부 가능",
                             "상담신청 hxxp://loan-help-kr.co/apply"])]),
    dict(id="s10", label="정상", room="보건소 안내",
         msgs=[("보건소", ["어르신 독감 예방접종 안내",
                          "10월 15일부터 무료로 접종하실 수 있습니다.",
                          "신분증을 지참해 가까운 보건소나 지정 의료기관을 방문해 주세요."])]),
    dict(id="s11", label="사칭", room="한국전력",
         msgs=[("전력공사", ["전기요금 미납 안내",
                            "미납금 87,400원이 확인되었습니다.",
                            "오늘까지 미납 시 공급이 중단됩니다.",
                            "납부확인 hxxp://kepco-pay.net"])]),
    dict(id="s12", label="정상", room="가족방",
         msgs=[("딸", ["엄마 이번 주말에 갈게요"]),
               ("나", ["그래 조심히 와"]),
               ("딸", ["뭐 사갈까요?"])]),
]

VARIANTS = [
    dict(theme="light", scale=1.0,  degrade=False, crop=False),
    dict(theme="dark",  scale=1.0,  degrade=False, crop=False),
    dict(theme="light", scale=1.35, degrade=False, crop=False),
    dict(theme="light", scale=1.0,  degrade=True,  crop=False),
    dict(theme="dark",  scale=1.35, degrade=False, crop=False),
    dict(theme="light", scale=1.0,  degrade=False, crop=True),
    dict(theme="dark",  scale=1.0,  degrade=True,  crop=False),
    dict(theme="light", scale=1.35, degrade=True,  crop=False),
]


def F(p, s):
    return ImageFont.truetype(p, int(s))


def wrap(d, text, font, maxw):
    out, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=font) > maxw and cur:
            out.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def render(scn, theme, scale, degrade, crop):
    T = THEMES[theme]
    W, S = 900, scale
    fr = F(_R, 26 * S)
    f_name = F(_B, 23 * S)

    img = Image.new("RGB", (W, 2600), T["bg"])
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W, 52], fill=T["header"])
    d.text((26, 14), "9:41", font=F(_B, 23), fill=T["status"])
    d.text((W - 165, 14), "LTE  ▮▮▮  83%", font=F(_R, 20), fill=T["status"])

    d.rectangle([0, 52, W, 136], fill=T["header"])
    d.text((28, 76), "‹", font=F(_B, 38), fill=T["status"])
    d.text((70, 82), scn["room"], font=F(_B, 29), fill=T["ink"])
    d.text((W - 84, 82), "☰", font=F(_B, 28), fill=T["status"])

    y = 166
    d.rounded_rectangle([W // 2 - 120, y, W // 2 + 120, y + 40], radius=20, fill=T["datepill"])
    d.text((W // 2 - 98, y + 7), "2026년 8월 1일 금요일", font=F(_R, 19),
           fill=(0xFF, 0xFF, 0xFF) if theme == "light" else T["ink"])
    y += 72

    gt, ci = [], 0
    for sender, lines in scn["msgs"]:
        mine = sender == "나"
        maxw = int(560 * min(S, 1.15))
        pad, lh = int(24 * S), int(38 * S)

        wrapped = []
        for ln in lines:
            wrapped.extend(wrap(d, ln, fr, maxw - pad * 2))
        gt.extend(lines)

        bw = max(int(d.textlength(w, font=fr)) for w in wrapped) + pad * 2
        bw = min(max(bw, 220), maxw)
        bh = pad * 2 + lh * len(wrapped)

        if mine:
            bx = W - 26 - bw
            d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=16, fill=T["mine"])
            for i, w in enumerate(wrapped):
                d.text((bx + pad, y + pad + i * lh), w, font=fr, fill=(0x1A, 0x1A, 0x1A))
            d.text((bx - 78, y + bh - int(30 * S)), "오후 2:14", font=F(_R, 18), fill=T["time"])
        else:
            col = AVATAR_COLORS[ci % len(AVATAR_COLORS)]
            d.rounded_rectangle([26, y, 98, y + 72], radius=24, fill=col)
            d.text((50, y + 18), sender[0], font=F(_B, 32), fill=(0xFF, 0xFF, 0xFF))
            d.text((116, y - 4), sender, font=f_name, fill=T["sub"])
            bx, by = 116, y + 28
            d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=16, fill=T["bubble"])
            for i, w in enumerate(wrapped):
                d.text((bx + pad, by + pad + i * lh), w, font=fr, fill=T["ink"])
            d.text((bx + bw + 12, by + bh - int(30 * S)), "오후 2:14", font=F(_R, 18), fill=T["time"])
            y += 28
            ci += 1
        y += bh + int(26 * S)

    bottom = y + 40
    d.rectangle([0, bottom, W, bottom + 108], fill=T["inputbar"])
    d.text((32, bottom + 30), "＋", font=F(_R, 36), fill=T["placeholder"])
    d.rounded_rectangle([88, bottom + 20, W - 116, bottom + 84], radius=32, fill=T["inputbox"])
    d.text((116, bottom + 34), "메시지 입력", font=F(_R, 25), fill=T["placeholder"])

    img = img.crop((0, 0, W, bottom + 108))

    if crop:
        img = img.crop((0, 300, W, img.height))
        if len(gt) > 1:
            gt = gt[1:]

    if degrade:
        img = img.rotate(random.uniform(-0.6, 0.6), resample=Image.BICUBIC,
                         fillcolor=T["bg"], expand=False)
        img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=random.randint(58, 72))
        buf.seek(0)
        img = Image.open(buf).convert("RGB")

    return img, gt


manifest, n = [], 0
for i, scn in enumerate(SCENARIOS):
    for v in (VARIANTS[i % len(VARIANTS)], VARIANTS[(i + 3) % len(VARIANTS)]):
        n += 1
        name = f"{n:02d}_{scn['id']}_{v['theme']}"
        if v["scale"] != 1.0:
            name += "_big"
        if v["degrade"]:
            name += "_low"
        if v["crop"]:
            name += "_crop"

        img, gt = render(scn, v["theme"], v["scale"], v["degrade"], v["crop"])
        img.save(f"{OUT}/{name}.png")
        open(f"{OUT}/{name}.txt", "w", encoding="utf-8").write("\n".join(gt))

        manifest.append(dict(image=f"{name}.png", truth=f"{name}.txt",
                             scenario=scn["id"], label=scn["label"], room=scn["room"],
                             theme=v["theme"], font_scale=v["scale"],
                             degraded=v["degrade"], cropped=v["crop"],
                             size=list(img.size), lines=len(gt)))

json.dump(dict(note="합성 데이터셋. 실제 폰 캡처보다 깨끗하므로 정확도의 상한으로 해석할 것. "
                    "등장 인물·번호·계좌는 모두 가공값.",
               count=len(manifest), items=manifest),
          open(f"{OUT}/manifest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print(f"생성 {len(manifest)}장")
for k in ("theme", "label", "degraded", "cropped"):
    print(" ", k, dict(Counter(str(m[k]) for m in manifest)))
