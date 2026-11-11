FROM python:3.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY routing.yaml ./
RUN mkdir -p /app/data && chown app /app/data
USER app
VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8000/healthz').status_code==200 else 1)"
CMD ["triage", "serve", "--host", "0.0.0.0", "--port", "8000"]
