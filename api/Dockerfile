# The ledger API image. Build context is the repo root (see docker-compose.yml);
# api/Dockerfile.dockerignore keeps everything but finance/, db/, api/ and the lock files
# out of the context, so .env and data/ can never be copied in.
FROM python:3.13-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir poetry poetry-plugin-export
COPY pyproject.toml poetry.lock ./
# Runtime deps only: main (psycopg), api (FastAPI, uvicorn, PyJWT, pool), sync (temporalio).
RUN poetry export --only main,api,sync --format requirements.txt -o requirements.txt \
 && python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.txt

FROM python:3.13-slim
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin api
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY finance ./finance
COPY db ./db
COPY api ./api
USER api
EXPOSE 8787
CMD ["uvicorn", "--factory", "api.app:create_app", "--host", "0.0.0.0", "--port", "8787", "--no-server-header"]
