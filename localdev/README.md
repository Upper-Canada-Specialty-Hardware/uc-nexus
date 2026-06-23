uc nexus local runtime

this repo uses the shared worktree-localdev engine (the "worktree based workflow with localized
simulated user testing" setup). the logic lives in that engine; this folder only carries the thin
loader (wt.ps1) and this project's config (config.psd1).

engine: https://github.com/Xilous/worktree-localdev  (clone to ~\Documents\worktree-localdev, or set
$env:WT_LOCALDEV_DIR to wherever you cloned it). full docs - new-workstation setup, the config
reference, concurrent chrome - live in that repo's README.

first time on a machine
- clone the engine (above), then:  .\localdev\wt.ps1 bootstrap-machine
- it sets up the shared postgres and seeds %LOCALAPPDATA%\worktree-localdev\secrets\uc_nexus.env -
  paste the real CLERK_SECRET_KEY (sk_test_...), VITE_CLERK_PUBLISHABLE_KEY (pk_test_...), and the
  BUCKET_* values there.

per worktree
- .\localdev\wt.ps1 bootstrap-worktree   reserve ports, gen env, install deps, create + migrate this
                                         branch's DB (uc_nexus on master, uc_nexus_<branch> otherwise)
- .\localdev\wt.ps1 start-all            launch backend + frontend in their own windows
- .\localdev\wt.ps1 reset-db             reset only this branch's DB
- .\localdev\wt.ps1 teardown             after merge: drop this branch's DB + free its ports

what this project declares (config.psd1)
- postgres; backend = poetry/uvicorn/alembic; frontend = npm/vite (vite.config.ts reads
  UC_BACKEND_PORT / UC_FRONTEND_PORT, which the engine sets per worktree).
- secrets: Clerk dev keys + the railway S3 bucket creds (bucket optional locally; document uploads
  won't work without it, everything else does).

seed test data by importing a TITAN hardware-schedule xml (testing/fixtures/contracterp-74.xml)
through the Import wizard. needs TESTING_ENABLED=true (set in the generated backend\.env) so the
/testing/clerk-sign-in ticket flow works.
