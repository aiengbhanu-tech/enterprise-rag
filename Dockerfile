FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/models
WORKDIR /app
RUN groupadd --gid 10001 rag && useradd --uid 10001 --gid rag --create-home rag
COPY pyproject.toml README.md ./
COPY rag ./rag
ARG EXTRAS=models
RUN pip install --no-cache-dir ".[${EXTRAS}]"
RUN mkdir -p /data /models && chown -R rag:rag /data /models /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"
CMD ["python", "-m", "uvicorn", "rag.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
