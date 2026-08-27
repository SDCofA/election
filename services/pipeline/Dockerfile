FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DAGSTER_HOME=/opt/dagster/dagster_home \
    ELEXION_PACKS_DIR=/app/packs
WORKDIR /app
COPY services/pipeline/pyproject.toml ./
COPY services/pipeline/elexion_pipeline ./elexion_pipeline
COPY services/pipeline/dagster.yaml /opt/dagster/dagster_home/dagster.yaml
COPY services/pipeline/workspace.yaml ./workspace.yaml
COPY services/api/app/packs ./packs
COPY infra/postgres ./postgres
RUN apt-get update && \
    apt-get upgrade --yes && \
    apt-get install --yes --no-install-recommends postgresql-client && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir . && \
    chown -R 65532:65532 /app /opt/dagster
USER 65532:65532
EXPOSE 3001
CMD ["dagster-webserver", "-h", "0.0.0.0", "-p", "3001", "-w", "/app/workspace.yaml"]
