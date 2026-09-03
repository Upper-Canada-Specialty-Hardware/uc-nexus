FROM python:3.11-slim

WORKDIR /app

# pg_dump / pg_restore, for the preview-environment production clone (app/preview_clone.py). From the
# PGDG repository rather than Debian's, because the client must match the server: production's
# Postgres is postgres-ssl:17 and an older client refuses a 17 dump ("unsupported version in file
# header"). The PGDG suite is read off the image's own /etc/os-release rather than hardcoded:
# python:3.11-slim tracks Debian stable (bookworm until 2025, trixie now), and a suite pinned to the
# wrong release fails on unmet libpq5 dependencies.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg && \
    install -d -m 0755 /usr/share/postgresql-common/pgdg && \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc && \
    . /etc/os-release && \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
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
