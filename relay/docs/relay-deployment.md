deploying the relay to a workstation. this covers the two things that turn the hand-run POC into
something that survives a reboot: the relay auto-starts at logon, and its shared secret is DPAPI-encrypted
at rest. the Chrome enterprise LNA pre-grant for the UC Nexus origin and flipping the relay allowlist to a
production company are IT / sign-off steps handled separately (per issue #178), not part of this.

the shape of it
- the relay ships as a `ucnexus-relay.zip` PyInstaller ONEDIR bundle (`ucnexus-relay.exe` + an `_internal\`
  folder), built in CI on a windows runner and attached to a GitHub Release - see
  `.github/workflows/relay-release.yml`. a workstation needs only that bundle plus a `config.toml`; no
  Python or Poetry install.
- onedir, not onefile: a onefile exe re-extracts its bundle (including the C-extension `.pyd`) to `%TEMP%`
  on EVERY launch, and on a Windows Defender box a freshly-written exe's extraction is scanned as it loads
  and the relaunched relay crashes (`_multiprocessing` / `PIL._imaging`). onedir keeps the `.pyd` as
  permanent files scanned once at install/update time, so launches load pre-scanned files.
- install layout under `%LOCALAPPDATA%\UCNexusRelay\`: data (`config.toml`, `relay.log`, `relay.pid`,
  `update.log`, `update-state.json`) lives in that dir; each version lives in its own `app-<...>\` folder;
  a `current` directory junction points at the active version. shortcuts + autostart target the stable
  `current\ucnexus-relay.exe` path, so a version update (which only repoints the junction) needs no change
  to them.
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

get the bundle
- grab `ucnexus-relay.zip` from the latest GitHub Release (tag `relay-v*`). releases are produced by the
  Relay Release workflow when a `relay-v<version>` tag is pushed.
- to cut a release: `git tag relay-v0.1.0 && git push origin relay-v0.1.0`. the workflow builds on
  windows-latest and uploads the zip to the release for that tag.
- for a local build instead (spec iteration / offline): `poetry install --with dev` then `.\build.ps1`,
  which runs PyInstaller against `ucnexus-relay.spec` and drops the onedir bundle in `dist\ucnexus-relay\`
  plus a zipped `dist\ucnexus-relay.zip`.

install - no-admin, self-service (the default for a non-admin workstation user)
- `install\install-relay-user.ps1 -ZipPath <path to ucnexus-relay.zip> [-StartNow]`
- what it does: extracts the bundle into `%LOCALAPPDATA%\UCNexusRelay\app-installed\`, points the `current`
  junction at it, seeds `config.toml` (never overwriting an existing one), registers a no-admin HKCU Run
  autostart (`current\ucnexus-relay.exe app --minimized` at logon, into the tray), and creates Desktop +
  Start-menu shortcuts. no elevation needed.

install - admin, scheduled task (IT / fleet alternative)
- registering a scheduled task writes to Task Scheduler, so this needs admin; the relay itself runs
  un-elevated.
- `install\install-relay.ps1 -ZipPath <path to ucnexus-relay.zip>`
- what it does: extracts the bundle + sets the `current` junction as above, seeds `config.toml`, and
  registers the `UC Nexus Relay` scheduled task: at-logon trigger for the current user, runs
  `current\ucnexus-relay.exe serve` with the install dir as the working directory, restart-on-failure (3
  tries, 1 min apart), no execution time limit

configure config.toml
- edit `%LOCALAPPDATA%\UCNexusRelay\config.toml`:
  - `[sql] server` / `driver` for the site
  - `[cors] allowed_origins` to the UC Nexus frontend origin
  - `[update] channel` - `stable` (the default: full releases only) or `latest` (prereleases too). only
    the one workstation that proves a build before it is promoted should be on `latest`.
- leave `[auth] shared_secret` for the enroll step below. enroll writes `config.toml` itself if this
  workstation has none (a hand-copied exe rather than an install), so there is nothing to create by
  hand first.
- there is no company list to set. the relay reads the companies it serves from GP's company master
  (`DYNAMICS..SY01500`, `[sql] system_db`) on every channel connect, so a company added in GP needs no
  edit here. the Setup tab's "Test GP connection" lists what it found; a relay that cannot read the
  master serves nothing and says so on the Status tab.
- there is nothing to configure for Railway PR environments. production pushes the current preview list
  down the relay's own backend socket (a `{"type": "channels", "urls": [...]}` frame, re-sent whenever it
  changes) and the relay dials the difference within about a second, dropping a channel when its PR
  closes. it accepts only `wss://backend-uc-nexus-pr-<N>.up.railway.app/relay-link`, only from the
  production channel, and every such channel is pinned to the sandbox companies. set
  `[channel] accept_pushed_preview_backends = false` to refuse them and dial only what this file names;
  `[channel] extra_backend_urls` still ADDS a backend production cannot know about (a local dev backend).

enroll - sets the secret, DPAPI-encrypted (the normal path)
- in UC Nexus an admin runs "provision relay install" and gets a one-time enrollment token. then on the
  workstation, from the install dir:
  - `.\current\ucnexus-relay.exe enroll --token <TOKEN> --backend-url https://<backend-host>/graphql`
- the relay generates its own long-lived secret, registers it with the backend using the one-time token
  (the backend can't reach the relay, but the relay can reach the backend), and writes the secret into
  `config.toml` DPAPI-ENCRYPTED. the backend keeps the plaintext (it's what the frontend presents as the
  Bearer token); the workstation keeps only the encrypted blob. nothing long-lived is ever hand-copied.
- the by-hand alternative: set `[auth] shared_secret = "<your secret>"` as plaintext, then run
  `.\current\ucnexus-relay.exe protect-secret` to encrypt it in place. this is idempotent - a value that's already
  `enc:dpapi:` is left alone. use `enroll --no-encrypt` only for throwaway dev configs.

start and verify
- `Start-ScheduledTask -TaskName "UC Nexus Relay"` (or just log off and back on)
- `.\current\ucnexus-relay.exe health` - hits `http://127.0.0.1:7321/health` and prints the status
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
- download the new `ucnexus-relay.zip` and re-run the same installer (`install-relay-user.ps1 -ZipPath
  <new zip>` or `install-relay.ps1 -ZipPath <new zip>`). it re-extracts the bundle, repoints `current`, and
  leaves the existing `config.toml` (and its encrypted secret) in place.
- or use the desktop app's Updates tab: it checks the public GitHub releases, downloads the zip, and applies
  it in place. The app extracts the new version into a fresh `app-<build>\` folder, exits, and a detached
  windowless helper (`ucnexus-relay update-apply`) - running from the OLD, already-scanned version - waits
  for the app to close, force-kills any remaining relay process BY PID (never by image name), repoints the
  `current` junction to the new version, and relaunches it, health-gated. Nothing renames or copies a
  running folder, and the new version's `.pyd` were written at extract time (Defender scans them before
  launch). The whole sequence is bounded by a ~90s deadline + an attempt cap; if the new version doesn't
  come up healthy the junction rolls back to the previous one, so a failed update leaves the relay running
  on the CURRENT build rather than looping or hanging. Stale `app-<build>\` folders are cleaned up on the
  next start.
- which releases a workstation takes is `[update] channel`: `stable` (default) skips anything flagged
  PRERELEASE on GitHub, `latest` takes it. that is how a build is proven before the fleet gets it - CI
  publishes the release as a prerelease, the one workstation on `latest` installs and exercises it, and
  `gh release edit <tag> --prerelease=false` promotes it to everyone else. highest build number still
  wins and a downgrade is still never offered.
- the first app start after an update lands verifies it: within five minutes `/health` has to report the
  backend channel CONNECTED. the apply helper only proves the new build binds its HTTP port, which says
  nothing about whether it can still reach UC Nexus. if the channel never comes up and a previous
  `app-<build>\` folder is still there, the `current` junction is repointed back to it, the serve child
  is restarted from that junction, and the ledger records `rolled_back` - the poller then refuses that
  build until a higher one is published. with no previous version on disk the new build stays put (a
  broken channel beats no relay). the check runs once per update, so a later offline boot cannot roll a
  good build back.
- update artifacts in the install dir (`%LOCALAPPDATA%\UCNexusRelay`):
  - `update.log` - the helper's step-by-step log (wait -> kill -> repoint -> relaunch); read this first if
    an update misbehaves.
  - `update-state.json` - the attempt ledger the Updates tab surfaces ("installed build N" / "update to
    build N failed: <reason>"). status is one of staging/applying/success/failed/cancelled/rolled_back,
    plus a `self_check` verdict once the post-update check has run.
  - `ucnexus-relay-download.zip` (the in-flight download) and superseded `app-<build>\` folders are
    transient; the download is deleted after extraction and old versions are cleaned on the next start.

uninstall
- `install\uninstall-relay.ps1` removes the autostart (the HKCU Run entry and/or the scheduled task) and the
  `current` junction, and leaves the install dir. add `-RemoveFiles` to also delete the versioned app
  folders and config. (a scheduled-task removal needs an elevated PowerShell; the Run-entry removal does not.)
