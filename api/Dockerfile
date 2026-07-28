# 곁눈(Gyeotnun) API 이미지
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성 레이어 캐시
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# ★ .env 는 이미지에 포함하지 않는다. docker-compose 의 env_file 로 주입한다.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
