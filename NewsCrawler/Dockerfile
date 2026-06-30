FROM python:3.11-slim

ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
ARG NEWS_CRAWLER_INSTALL_BROWSER=0
ARG NEWS_CRAWLER_INSTALL_BLOOMBERG=0

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
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends curl tesseract-ocr tesseract-ocr-chi-sim \
    && if [ "$NEWS_CRAWLER_INSTALL_BROWSER" = "1" ]; then \
        apt-get -o Acquire::Retries=5 install -y --no-install-recommends chromium chromium-driver fonts-liberation; \
    fi \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY contracts ./contracts
RUN python -m pip install --retries 8 --timeout 120 --upgrade pip setuptools wheel \
    && if [ "$NEWS_CRAWLER_INSTALL_BROWSER" = "1" ] && [ "$NEWS_CRAWLER_INSTALL_BLOOMBERG" = "1" ]; then \
        python -m pip install --retries 8 --timeout 120 --no-build-isolation '.[browser,bloomberg]'; \
    elif [ "$NEWS_CRAWLER_INSTALL_BROWSER" = "1" ]; then \
        python -m pip install --retries 8 --timeout 120 --no-build-isolation '.[browser]'; \
    elif [ "$NEWS_CRAWLER_INSTALL_BLOOMBERG" = "1" ]; then \
        python -m pip install --retries 8 --timeout 120 --no-build-isolation '.[bloomberg]'; \
    else \
        python -m pip install --retries 8 --timeout 120 --no-build-isolation .; \
    fi

ENTRYPOINT ["news-crawler"]
CMD ["crawl", "--source", "all", "--latest"]
