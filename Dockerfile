FROM python:3.14.8-slim

WORKDIR /app

# Copy requirements first (so pip install can be cached)
COPY requirements.txt .

# Python library requirements
RUN pip install --no-cache-dir -r requirements.txt

# Brick Work
COPY . .

# One admin command, including for non-root container users
ENV PATH="/app/bin:${PATH}"

# The code is owned by root and only readable by the app; the app writes only to /app/data (#65).
RUN chmod -R a+rX,go-w /app \
    && chmod +x entrypoint.sh \
    && groupadd --gid 1000 brickwork \
    && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /app --shell /usr/sbin/nologin brickwork \
    && mkdir -p /app/data \
    && chown 1000:1000 /app/data

USER 1000:1000

# The API health route answers without a token; the slim image has no curl.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('BW_PORT', '3333') + '/api/v1/health', timeout=4)"

ENTRYPOINT ["./entrypoint.sh"]
