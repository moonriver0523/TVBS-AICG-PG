FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# 中文字型：base image 是 Debian slim，一個 CJK 字型都沒有，
# compose.py 疊字（播出鏡面浮水印、合成版封面）會直接 ComposeError。
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev
RUN chmod +x entrypoint.sh

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8080

CMD ["./entrypoint.sh"]
