uc nexus local runtime

self-contained way to run the whole app on your own machine and point simulated user testing at it, instead of waiting on a railway deploy per branch. windows + powershell, no docker, no admin install. built for many git worktrees running side by side: one shared postgres server, but each worktree gets its own branch-scoped database and its own app ports, so multiple worktrees implement + test concurrently without colliding.

the model
- one machine-level postgres server, shared by every checkout/worktree, living outside any repo at %LOCALAPPDATA%\uc-nexus\ (override with UC_LOCALDEV_HOME). holds the binaries, the single cluster, and secrets.env (the shared dev keys you paste once).
- per branch: its own database uc_nexus_<branch> on that server (master = uc_nexus), its own alembic head, its own seeded test data, and its own backend+frontend ports.
- per Claude instance: its own isolated Chrome (config is device-level, see "concurrent testing" below).

what it runs (per worktree)
- backend: fastapi + graphql on http://localhost:<backend-port>
- frontend: vite dev server on http://localhost:<frontend-port> (proxies /graphql + /admin to that worktree's backend)
- master uses 8000 / 5173; other branches get a stable assigned pair (see ports)

prerequisites
- node + npm (frontend)
- python 3.11 + poetry (backend)
- a shared clerk DEV-instance publishable key + secret key
- the postgres binaries zip (one-time manual download, see machine setup)

one-time machine setup (once per device)
1. run:  .\localdev\bootstrap-machine.ps1
   - creates %LOCALAPPDATA%\uc-nexus\, migrates any existing in-repo .localdev\ into it, and seeds secrets.env (carrying over keys from an existing backend\.env / frontend\.env.local if present).
2. postgres binaries (only if you've never set them up):
   - open https://www.enterprisedb.com/download-postgresql-binaries
   - pick PostgreSQL 16.x / Windows x86-64 / "zip archive" (the binaries-only build, NOT the installer)
   - drop the downloaded postgresql-16.x-windows-x64-binaries.zip into %LOCALAPPDATA%\uc-nexus\localdev\
   - it's extracted on first db start.
3. fill in keys: edit %LOCALAPPDATA%\uc-nexus\secrets.env and paste the real CLERK_SECRET_KEY (sk_test_...) and VITE_CLERK_PUBLISHABLE_KEY (pk_test_...) if bootstrap left placeholders.

per-worktree setup (once in each new worktree)
- run:  .\localdev\bootstrap-worktree.ps1
  reserves this branch's ports, generates backend\.env + frontend\.env.local from secrets.env, runs poetry install + npm ci, then creates + migrates this branch's database. after it finishes the worktree is ready.

daily use
- everything at once:  .\localdev\start-all.ps1
  ensures this branch's db is up + migrated, then opens backend and frontend each in its own window. it prints the app url (http://localhost:<frontend-port>).
- piece by piece:
  - .\localdev\start-db.ps1        ensure the shared server is up and this branch's schema is migrated
  - .\localdev\start-backend.ps1   uvicorn, foreground, on this branch's backend port
  - .\localdev\start-frontend.ps1  vite, foreground, on this branch's frontend port
- stop the shared server (affects ALL worktrees):  .\localdev\stop-db.ps1
- reset just this branch's data:  .\localdev\reset-db.ps1
- after merge/abandon, clean up this branch:  .\localdev\teardown-worktree.ps1  (drops the branch db, frees its ports)

resetting test data
- during a session, use the in-app "DevAction: drop and rebuild schema" button (app bar) for a clean schema
- reset-db.ps1 drops + rebuilds only the current branch's database; other branches are untouched

ports
- master: backend 8000, frontend 5173. other branches: a stable pair assigned by bootstrap-worktree and recorded in %LOCALAPPDATA%\uc-nexus\ports.json, bumped past any collision so concurrent worktrees never clash.
- override per worktree by setting UC_BACKEND_PORT / UC_FRONTEND_PORT before running.
- postgres defaults to 5432; override with UC_PG_PORT if taken.

concurrent simulated user testing (multiple worktrees at once)
- sign-in uses a clerk one-time ticket. from the browser, fetch a token from THIS worktree's backend and navigate with it (substitute this worktree's ports):

      (async () => {
        const r = await fetch('http://localhost:<backend-port>/testing/clerk-sign-in');
        const { token } = await r.json();
        window.location.href = 'http://localhost:<frontend-port>/?__clerk_ticket=' + token;
        return 'navigating with sign-in token...';
      })()

- needs TESTING_ENABLED=true and CLERK_SECRET_KEY in backend\.env (bootstrap-worktree sets both). clerk dev instances already allow localhost.
- seed data by importing a TITAN hardware-schedule xml through the Import wizard. each branch's data is its own (separate database).
- each Claude Code instance launches its own isolated Chrome automatically: the device-level chrome-devtools MCP runs with --isolated and no --browserUrl, so N worktree instances drive N separate browsers with no shared profile or port. (configured in ~/.claude/settings.json.)

known limitation
- PO/vendor document attachments need the railway S3 bucket. with BUCKET_* left blank in secrets.env, attaching/downloading those files won't work locally - everything else does, including the Import module's XML upload (it's client-side, never touches S3)

what stays out of git
- the machine home %LOCALAPPDATA%\uc-nexus\ (binaries, cluster, logs, zip, secrets.env, ports.json) lives outside every repo
- backend\.env and frontend\.env.local are gitignored and regenerated per worktree by bootstrap-worktree; only the .example files are tracked

troubleshooting
- "secrets.env not found" - run .\localdev\bootstrap-machine.ps1 first
- "Postgres binaries missing" - drop the zip into %LOCALAPPDATA%\uc-nexus\localdev\ (machine setup step 2)
- "did not become ready" / startup errors - check %LOCALAPPDATA%\uc-nexus\localdev\postgres.log
- port 5432 already in use - another postgres is running; stop it or set UC_PG_PORT
- backend can't reach the DB - confirm .\localdev\start-db.ps1 finished without errors and that backend\.env exists (run bootstrap-worktree)
- frontend throws "Missing VITE_CLERK_PUBLISHABLE_KEY" - run bootstrap-worktree (it generates frontend\.env.local from secrets.env)
- dropdb / reset fails with "database is being accessed by other users" - stop this worktree's backend window first
