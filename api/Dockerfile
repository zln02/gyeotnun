# 곁눈(Gyeotnun) API 이미지
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성 레이어 캐시
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ★ 로컬 OCR(PaddleOCR→opencv) 런타임 시스템 라이브러리. pip 레이어 뒤에 두어
#   paddle 재설치 없이 이 레이어만 추가되게 한다(libGL.so.1 등 누락 방지).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY . .

EXPOSE 8000

# ★ .env 는 이미지에 포함하지 않는다. docker-compose 의 env_file 로 주입한다.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
