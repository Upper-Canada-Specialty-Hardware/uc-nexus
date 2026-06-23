uc nexus local runtime

self-contained way to run the whole app on your own machine and point simulated user testing at it, instead of waiting on a railway deploy per branch. windows + powershell, no docker, no admin install.

what it runs
- portable postgres 16 under .localdev/ (no install, no admin, no docker, no service)
- backend: fastapi + graphql on http://localhost:8000
- frontend: vite dev server on http://localhost:5173 (proxies /graphql + /admin to the backend)

prerequisites
- node + npm (frontend)
- python 3.11 + poetry (backend)
- a shared clerk DEV-instance publishable key + secret key
- the postgres binaries zip (one-time manual download, see setup step 4)

one-time setup
1. backend deps:   cd backend; poetry install
2. frontend deps:  cd frontend; npm ci
3. env files:
   - copy backend\.env.example to backend\.env, then paste CLERK_SECRET_KEY (sk_test_...)
   - copy frontend\.env.local.example to frontend\.env.local, then paste VITE_CLERK_PUBLISHABLE_KEY (pk_test_...)
4. postgres binaries (manual, once):
   - open https://www.enterprisedb.com/download-postgresql-binaries
   - pick PostgreSQL 16.x / Windows x86-64 / "zip archive" (the binaries-only build, NOT the installer)
   - drop the downloaded postgresql-16.x-windows-x64-binaries.zip into the .localdev\ folder at the repo root
   - start-db.ps1 extracts it on first run. if .localdev\ doesn't exist yet, run .\localdev\start-db.ps1 once - it creates the folder and prints exactly where to put the zip

daily use
- everything at once:  .\localdev\start-all.ps1
  brings up postgres (extract + init + migrate on first run), then opens backend and frontend each in its own window. then open http://localhost:5173
- piece by piece:
  - .\localdev\start-db.ps1        ensure postgres is up and the schema is migrated
  - .\localdev\start-backend.ps1   uvicorn, foreground
  - .\localdev\start-frontend.ps1  vite, foreground
- stop postgres:  .\localdev\stop-db.ps1
- wipe + rebuild the local cluster:  .\localdev\reset-db.ps1

resetting test data
- during a session, use the in-app "DevAction: drop and rebuild schema" button (app bar) for a clean schema
- reset-db.ps1 is the heavier hammer: it deletes the whole postgres cluster, then re-inits and re-migrates

simulated user testing against local
- sign-in uses a clerk one-time ticket. from the browser (e.g. an evaluate_script), fetch a token from the local backend and navigate with it:

      (async () => {
        const r = await fetch('http://localhost:8000/testing/clerk-sign-in');
        const { token } = await r.json();
        window.location.href = 'http://localhost:5173/?__clerk_ticket=' + token;
        return 'navigating with sign-in token...';
      })()

- needs TESTING_ENABLED=true and CLERK_SECRET_KEY in backend\.env. clerk dev instances already allow localhost, so no extra clerk config
- seed data by importing a TITAN hardware-schedule xml through the Import wizard

ports
- postgres defaults to 5432. if it's taken, set UC_PG_PORT first, e.g.  $env:UC_PG_PORT='5544'; .\localdev\start-all.ps1

known limitation
- PO/vendor document attachments need the railway S3 bucket. with BUCKET_* left blank in backend\.env, attaching/downloading those files won't work locally - everything else does, including the Import module's XML upload (it's client-side, never touches S3)

what stays out of git
- .localdev\ (binaries, cluster data, logs, the downloaded zip) is gitignored
- backend\.env and frontend\.env.local are gitignored; only the .example files are tracked

troubleshooting
- "Postgres binaries missing" - you haven't dropped the zip into .localdev\ yet (setup step 4)
- "did not become ready" / startup errors - check .localdev\postgres.log
- port 5432 already in use - another postgres is running; stop it or set UC_PG_PORT
- backend can't reach the DB - confirm .\localdev\start-db.ps1 finished without errors and that backend\.env exists
- frontend throws "Missing VITE_CLERK_PUBLISHABLE_KEY" - you haven't created frontend\.env.local from the example
