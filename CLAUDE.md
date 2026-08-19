# 곁눈 — 새 세션 온보딩

이 저장소에서 작업을 시작하기 전에 읽는다. 자세한 규칙은
[`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) 에 있다.

## 이 서비스가 하지 않는 것

**진위를 판정하지 않는다.** "가짜입니다"·"사기입니다"를 쓰지 않고, 스스로 확인할 질문을
하나씩 준다. 판정 억제는 `services/prompt_chain.py` 의 2단 안전장치(시스템 프롬프트 +
`validate_question`)가 지킨다. 이 원칙을 무르는 변경은 하지 않는다.

## ★ 로컬 우회 금지

실험·벤치 파일에서 **본체(`services/`·`routers/`)의 결함을 우회했다면, 우회 코드만
남기지 않는다.** [`docs/evaluation/본체결함_발견대장.md`](docs/evaluation/본체결함_발견대장.md)
에 항목을 올리고 우회 주석에 링크한다.

> 2026-08-05 에 한 실험 파일이 `count_sentences()` 의 결함을 정확히 진단하고 그 파일에서만
> 우회했다. 12일 뒤 그 결함이 라이브 사고가 됐다 — 사칭 문자에 가장 좋은 질문이 전부
> 차단되고, 폴백의 거짓 전제가 어르신을 안심시키는 방향으로 작동했다.
> **우회는 발견을 소비해 버린다.**

## ★ 운영 DB 는 절대 직접 지우지 않는다

`api/tools/delete_rows.py` 로만 지운다. **백업 → 복원 리허설 → `--expect` → 삭제**,
행 수와 무관하게 예외 없다. 자세한 이유와 절차는
[`deploy/README.md`](deploy/README.md) "운영 DB 삭제 규칙".

> "17행만 지우면 된다"로 시작해 262행을 지웠고 복구하지 못했다.
> **확인을 '출력'하는 것과 '차단'하는 것은 다르다.**

## ★ 실험은 운영 DB 에 쓰지 않는다

`experiments/`·`tools/bench_*` 는 `import _guard` 를 **`services`/`models` 보다 먼저**
넣는다. 빠뜨리면 `tests/test_experiment_db_guard.py` 가 잡는다.

## 배포

- 프론트: `deploy/publish.sh` (백업 → 복사 → HTTP 200 확인 → 실패 시 자동 복구)
- 백엔드: `deploy/verify_restart_race.sh` — `docker compose restart api` 를 **직접 치지 않는다.**
  재시작 직후 경합 검사가 배포 절차의 필수 단계다.

## 측정과 보고

- **측정하지 않은 것을 측정한 것처럼 쓰지 않는다.** "확인 못 함"이 추측보다 낫다.
- 판정에 영향을 주는 변경은 `tools/render_verdict.mjs` 142건 전수 대조로 확인한다.
- 임계값(0.6155 · 0.6790 등)은 임의로 만지지 않는다.
- 보고 내용은 `docs/reports/YYYY-MM-DD_주제.txt` 평문으로도 남긴다.
- ★ **게이트는 실패해 본 적이 있어야 한다.** 실패를 본 적 없는 초록불은 의미가 없다.

## 저장소 취급

- `git add -A` 를 쓰지 않는다. 경로를 지정한다(다른 세션과 폴더를 공유한다).
- 브랜치를 옮기지 않는다. force-push·rebase·`reset --hard` 를 쓰지 않는다.
- `.env` 는 읽지도 출력하지도 않는다.
