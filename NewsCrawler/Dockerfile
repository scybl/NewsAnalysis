FROM python:3.11-slim

ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app

RUN sed -i \
        -e 's|http://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g' \
        -e 's|http://deb.debian.org/debian-security|https://mirrors.aliyun.com/debian-security|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY contracts ./contracts
RUN python -m pip install --retries 8 --timeout 120 --upgrade pip setuptools wheel \
    && python -m pip install --retries 8 --timeout 120 --no-build-isolation .

ENTRYPOINT ["news-crawler"]
CMD ["crawl", "--source", "all", "--latest"]
