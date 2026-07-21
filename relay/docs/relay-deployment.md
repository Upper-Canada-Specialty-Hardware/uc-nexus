deploying the relay to a workstation. this covers the two things that turn the hand-run POC into
something that survives a reboot: the relay auto-starts at logon, and its shared secret is DPAPI-encrypted
at rest. the Chrome enterprise LNA pre-grant for the UC Nexus origin and flipping the relay allowlist to a
production company are IT / sign-off steps handled separately (per issue #178), not part of this.

the shape of it
- the relay ships as a single `ucnexus-relay.exe` (PyInstaller, built in CI on a windows runner and
  attached to a GitHub Release - see `.github/workflows/relay-release.yml`). a workstation needs only the
  exe plus a `config.toml` next to it; no Python or Poetry install.
- a per-user scheduled task launches the exe AT LOGON and restarts it on failure. it runs as the logged-in
  domain user, NOT as a service account. that is deliberate: the relay authenticates to GP via Windows
  SSPI as that user (the one in DYNGRP), so it must run in that user's session. a boot-time service under
  LocalSystem would have no GP access - a dedicated service account is a separate DBA conversation.
- the secret in `config.toml` is DPAPI-encrypted with CurrentUser scope, so it is bound to that same
  Windows user on that machine and only that account can decrypt it.

prerequisites on the workstation
- an ODBC driver for SQL Server (17 or 18). this is the one real system prereq; set which one in
  `config.toml` under `[sql] driver`.
- the machine is domain-joined and the logged-in user can reach the GP SQL server and is in DYNGRP. on a
  domain box that's just Windows SSPI - no password stored anywhere.

get the exe
- grab `ucnexus-relay.exe` from the latest GitHub Release (tag `relay-v*`). releases are produced by the
  Relay Release workflow when a `relay-v<version>` tag is pushed.
- to cut a release: `git tag relay-v0.1.0 && git push origin relay-v0.1.0`. the workflow builds on
  windows-latest and uploads the exe to the release for that tag.
- for a local build instead (spec iteration / offline): `poetry install --with dev` then `.\build.ps1`,
  which runs PyInstaller against `ucnexus-relay.spec` and drops the exe in `dist\`.

install (elevated PowerShell, once per workstation)
- registering a scheduled task writes to Task Scheduler, so the install needs admin. the relay itself then
  runs un-elevated.
- `install\install-relay.ps1 -ExePath <path to downloaded ucnexus-relay.exe>`
- what it does:
  - stages the exe into `%LOCALAPPDATA%\UCNexusRelay\` (override with `-InstallDir`)
  - seeds a `config.toml` there from `config.example.toml` if one isn't already present (it never
    overwrites an existing config - that would clobber an enrolled secret)
  - registers the `UC Nexus Relay` scheduled task: at-logon trigger for the current user, runs
    `ucnexus-relay.exe serve` with the install dir as the working directory, restart-on-failure (3 tries,
    1 min apart), no execution time limit

configure config.toml
- edit `%LOCALAPPDATA%\UCNexusRelay\config.toml`:
  - `[sql] server` / `driver` for the site
  - `[gp] default_company` / `allowed_companies` (sandboxes only until prod sign-off; NEVER add UBC/UCSH
    here without it)
  - `[cors] allowed_origins` to the UC Nexus frontend origin
- leave `[auth] shared_secret` for the enroll step below.

enroll - sets the secret, DPAPI-encrypted (the normal path)
- in UC Nexus an admin runs "provision relay install" and gets a one-time enrollment token. then on the
  workstation, from the install dir:
  - `.\ucnexus-relay.exe enroll --token <TOKEN> --backend-url https://<backend-host>/graphql`
- the relay generates its own long-lived secret, registers it with the backend using the one-time token
  (the backend can't reach the relay, but the relay can reach the backend), and writes the secret into
  `config.toml` DPAPI-ENCRYPTED. the backend keeps the plaintext (it's what the frontend presents as the
  Bearer token); the workstation keeps only the encrypted blob. nothing long-lived is ever hand-copied.
- the by-hand alternative: set `[auth] shared_secret = "<your secret>"` as plaintext, then run
  `.\ucnexus-relay.exe protect-secret` to encrypt it in place. this is idempotent - a value that's already
  `enc:dpapi:` is left alone. use `enroll --no-encrypt` only for throwaway dev configs.

start and verify
- `Start-ScheduledTask -TaskName "UC Nexus Relay"` (or just log off and back on)
- `.\ucnexus-relay.exe health` - hits `http://127.0.0.1:7321/health` and prints the status
- for a fuller check (read-only GP identity probe): `curl -H "Authorization: Bearer <secret>"
  http://localhost:7321/info`. the secret there is the plaintext one the frontend uses, not the encrypted
  blob in config.

how the secret is protected, and the one gotcha
- on read, the relay decrypts `[auth] shared_secret` transparently. an `enc:dpapi:<base64>` value is a
  DPAPI blob; a value without that prefix is treated as plaintext (dev) and passed through.
- CurrentUser scope means the blob only decrypts under the SAME Windows user that encrypted it. if the
  workstation's relay user changes, or the config is copied to another machine/account, decryption fails
  with a clear error - just re-run `enroll` (or `protect-secret`) under the account the relay runs as.

updating to a new build
- download the new `ucnexus-relay.exe` and re-run `install-relay.ps1 -ExePath <new exe>`. it re-stages the
  exe and re-registers the task, and leaves the existing `config.toml` (and its encrypted secret) in place.
- or use the desktop app's Updates tab: it checks the public GitHub releases, downloads the exe, and
  applies it in place. The app stages the download, exits, and a detached windowless helper
  (`ucnexus-relay update-apply`) waits for the app to close, force-kills any remaining relay process BY PID
  (never by image name), swaps the exe (rename-aside + drop-in), and relaunches - exactly once. The whole
  sequence is bounded by a ~90s deadline and an attempt cap, so a failed update leaves the relay running on
  the CURRENT build rather than looping or hanging.
- update artifacts in the install dir (`%LOCALAPPDATA%\UCNexusRelay`):
  - `update.log` - the helper's step-by-step log (wait -> kill -> swap -> relaunch); read this first if an
    update misbehaves.
  - `update-state.json` - the attempt ledger the Updates tab surfaces ("installed build N" / "update to
    build N failed: <reason>"). status is one of staging/applying/success/failed/cancelled.
  - `ucnexus-relay.exe.new` (in-flight download) and `ucnexus-relay.exe.old*` (the swapped-out exe, cleaned
    up after a successful swap) are transient.

uninstall
- `install\uninstall-relay.ps1` removes the scheduled task and leaves the install dir. add `-RemoveFiles`
  to also delete the exe and config.
