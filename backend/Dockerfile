FROM python:3.11-slim

WORKDIR /app

# pg_dump / pg_restore, for the preview-environment production clone (app/preview_clone.py). From the
# PGDG repository rather than Debian's, because the client must match the server: production's
# Postgres is postgres-ssl:17 and Debian bookworm ships the 15 client, which refuses a 17 dump
# ("unsupported version in file header"). python:3.11-slim IS bookworm, hence bookworm-pgdg.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg && \
    install -d -m 0755 /usr/share/postgresql-common/pgdg && \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc && \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client-17 && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-interaction

COPY . .
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

EXPOSE 8000

CMD ["./entrypoint.sh"]
