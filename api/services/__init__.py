"""곁눈 도메인 서비스 패키지.

ocr(박진) / masking(박진) / search(김유리) / prompt_chain(김태희) /
tagger(장지석) / rag(장지석)

공통 규칙
- 각 모듈은 키가 없으면 config.MissingKeyError 를 던진다. 라우터가 501로 변환한다.
- 어떤 모듈도 '진짜/가짜' 판정을 반환하지 않는다.
"""
