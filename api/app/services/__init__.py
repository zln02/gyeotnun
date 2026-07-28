"""
곁눈(Gyeotnun) 서비스 계층.

각 모듈은 담당자가 내부 구현을 채웁니다.
**함수 시그니처는 변경하지 마세요.** 라우터와 프론트가 이 계약에 의존합니다.

    ocr.py          extract_text(image_bytes)      담당: 박진
    masking.py      mask_pii(text)                 담당: 박진 (보안) - 실구현 완료
    search.py       cross_check(query)             담당: 김유리
    prompt_chain.py generate_questions(...)        담당: 김태희
    tagger.py       tag_error_type(dialogue_log)   담당: 장지석
    training.py     get_today_card(...)            담당: 장지석
"""
