# OFbot 2 runtime image
# 多架构构建：docker buildx build --platform linux/amd64,linux/arm64 -t ofbot2:latest .
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p logs data plugins

# 非 root 运行
RUN useradd --create-home --uid 10001 ofbot && chown -R ofbot:ofbot /app
USER ofbot

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4)"

CMD ["python", "main.py"]
