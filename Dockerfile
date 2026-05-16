FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN pip install kagimcp==1.0.0rc4

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "kagimcp --http --host 0.0.0.0 --port ${PORT}"]
