FROM python:3.11-slim

ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --retries 8 --timeout 120 --upgrade pip setuptools wheel \
    && python -m pip install --retries 8 --timeout 120 --no-build-isolation -r requirements.txt

COPY . .

RUN mkdir -p cache local_data logs reports sessions

EXPOSE 8765

CMD ["python", "-m", "stock_pipeline", "web", "--host", "0.0.0.0", "--port", "8765"]
