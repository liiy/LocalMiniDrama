FROM python:3.12-slim

WORKDIR /app

# 安装 ffmpeg、libsndfile 以及基础构建工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 先复制安装所需源码，使 setuptools 能根据 pyproject.toml 安装应用及其依赖。
COPY pyproject.toml ./
COPY app ./app
COPY tools ./tools
RUN pip install --no-cache-dir .

COPY configs ./configs
RUN mkdir -p /app/data/storage

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 5679

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5679"]
