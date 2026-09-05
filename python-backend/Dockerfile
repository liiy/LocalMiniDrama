FROM python:3.11-slim

WORKDIR /app

# 安装 ffmpeg、libsndfile 以及基础构建工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 5679

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5679"]
