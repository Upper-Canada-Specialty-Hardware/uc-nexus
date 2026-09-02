# The relay as a Linux container, for fixture mode ONLY. It answers every GP op out of the checked-in
# snapshot (src/ucnexus_relay/fixture_ops.py) and dials a UC Nexus backend over the outbound channel, so
# a Railway preview environment can exercise relay-dependent paths with no workstation and no GP.
#
# The workstation relay is not built from this - that is the PyInstaller onedir bundle (build.ps1 /
# ucnexus-relay.spec) and it is unaffected by anything here.
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false

# --only main leaves out pyinstaller (a dev dependency that builds the Windows exe and has no business
# here). pywebview and pythonnet carry sys_platform == 'win32' markers, so they resolve to nothing on
# Linux; pystray and pillow do install but are imported lazily by the desktop app, which serve never
# touches. pyodbc installs from its manylinux wheel and is never imported in fixture mode - and if the
# ODBC runtime it links against is missing, the guarded imports in db.py / channel.py / main.py handle it.
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-interaction --no-ansi

COPY src ./src
COPY fixtures ./fixtures

# config.py resolves the bundled snapshot relative to the package, which puts it at /app/fixtures here.
# There is no config.toml in the image on purpose: everything comes from the environment.
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    UCNEXUS_RELAY_MODE=fixture \
    UCNEXUS_RELAY_LOG_FILE=-

# Set per environment, and the container has nothing to do without them:
#   UCNEXUS_RELAY_BACKEND_URL   the wss://.../relay-link to dial
#   UCNEXUS_RELAY_SHARED_SECRET the secret that backend's RELAY_SEED_SECRET_HASH was seeded from
# Optional:
#   UCNEXUS_RELAY_BUILD         what the hello frame reports as this build, e.g. relay-stub.<sha7>.
#                               Without it a container reports "dev" and no reader of relayStatus or
#                               relay_events can tell one preview build from another.
CMD ["python", "-m", "ucnexus_relay", "serve"]
