# The PR test environment

What a UC Nexus PR environment is, what it can and cannot show you, and how to read it when it does
not come up. Read this **before** a testing session; the module-by-module knowledge you need *during*
one is in [CLAUDE.md](CLAUDE.md) alongside it.

Separate from that file on purpose: this is a procedure invalidated by infrastructure changes, and it
went stale silently once already - it claimed for months that adding a relay channel needed a restart,
which stopped being true at #456 and cost a session. Anything here that describes relay behaviour
should cite the code it came from so a reader can check rather than trust.

## There is nothing to set up

**Every open, non-draft PR gets a built environment with a connected relay and a sign-in link.** Open
the PR, wait for the `preview-env` check, and read its sticky comment. Draft PRs and bot PRs get
nothing, by design - there would be nothing to sign into.

The comment carries four things:

- the sign-in link, `<backend>/testing/session?key=<K>`. Navigate it once and you land on `/app` as the
  dedicated e2e account (Admin/Manager). It mints a fresh Clerk ticket every visit, so it never goes
  stale and survives a DevAction schema reset.
- one relay line, normally `relay: stub connected, companies TUBC, TUCSH`.
- one line on handing the environment to the real workstation relay (below).
- the two URLs: `https://frontend-uc-nexus-pr-<N>.up.railway.app` and
  `https://backend-uc-nexus-pr-<N>.up.railway.app`.

The environment is named `uc-nexus-pr-<N>`, NOT `pr-<N>` - the Railway CLI answers `Environment
"pr-511" not found` for the latter, which reads like the environment is missing.

**`.github/workflows/preview-env.yml` owns every build in it.** It forks the environment from
production, repoints the forked deployment triggers at the PR branch, creates the relay stub service,
sets the testing variables, and then deploys each of the four services for that PR head commit and
waits on the deployment id it created. Railway is not asked to decide what to build, and the workflow
reads no deployment it did not start. What follows is what the environment can show you, and how to
read it when the check goes red - not a checklist to run per PR.

## The relay is a fixture stub by default

Each environment gets its own relay: a service named `relay-stub-pr-<N>`, built from `relay/` in this
repo and running with `UCNEXUS_RELAY_MODE=fixture`. It dials the environment's own
`/relay-link` and answers GP ops out of fixtures instead of a GP SQL connection, for **TUBC** and
**TUCSH**. It has no public domain and nothing outside its environment can reach it.

Confirm it the same way you always did:

```
{ relayStatus { connected company build } }
```

and from outside the app, `GET <backend>/health` answers `relay_connected` and `relay_companies` -
that pair is the workflow's own readiness gate, so a green `preview-env` check already means the relay
was connected when the comment was posted.

What that buys you: the GP-connected half of the app is reachable by clicking. What it does not buy
you is GP. **A fixture answer is not an eConnect write.** Anything whose point is that GP really holds
the row - a PO number GP minted, a vendor stamped from PM00200, a receipt posted against a live
purchase order - proves nothing against the stub. For those, hand the environment to the real relay.

The stub is an ordinary service in the environment, so **the relay-down half of the app is still
reachable**: remove `relay-stub-pr-<N>` from the environment in the Railway dashboard and the backend
goes back to reporting `relay_connected: false`, until the next `preview-env` run rebuilds it. That
half is worth testing on purpose - disabled controls, "not connected" copy, held values still
displaying, the queued-write outbox - and it is awkward to reach on production without stopping the
relay for everyone.

## Handing an environment to the real relay

Set `PREVIEW_REAL_RELAY=1` on that environment's **backend** service and redeploy. The workstation
relay dials in within a couple of minutes. The next `preview-env` run deletes the stub service rather
than rebuilding it - a stub left dialling a backend that now seeds the workstation relay's hash would
403 every ~30s forever, which is the exact cadence you would otherwise diagnose a real relay fault
by.

```powershell
railway variables --set "PREVIEW_REAL_RELAY=1" --environment uc-nexus-pr-<N> --service backend
```

The set prints nothing on success (verify with a `--json` read) and redeploys the backend, ~2 min.
Then poll the same gate the workflow uses:

```powershell
Invoke-RestMethod "https://backend-uc-nexus-pr-<N>.up.railway.app/health"
```

`relay_connected: true` with the companies the workstation is enrolled for means you are through. To
go back to the stub, remove the variable and re-run `preview-env` on the PR.

Two things this path still depends on, both inherited from production at fork time and neither
something to set per PR:

- `PREVIEW_REGISTRY_SECRET` on the production backend. A preview with `PREVIEW_REAL_RELAY` on
  announces itself to production's `/preview-channels` with that secret in an
  `X-Preview-Registry-Secret` header (`app/services/preview_announce.py`); production holds the
  announcements (`app/services/preview_registry.py`) and pushes the channel list down the socket the
  relay already holds. Blank on either side closes the route with a 401 and the relay keeps dialling
  production alone.
- `RELAY_SEED_SECRET_HASH` on the production backend (#414). Relay installs live in Postgres and a PR
  environment boots a fresh empty one, so the real relay's handshake would be refused 4403 without a
  trusted install seeded at backend startup. Production itself refuses to seed and logs the refusal at
  INFO, which is the intended steady state. `PREVIEW_REAL_RELAY` is what switches the seeded
  credential from the stub's hash to this one, and the seeded install is pinned to
  `RELAY_SEED_COMPANIES` (TUBC by default) - narrower than the stub's list on purpose, because this
  one is a credential the production workstation relay also answers to.

**Inheritance is a copy taken when the environment is forked, not a live link** (#431). A variable
added to production afterwards never reaches an environment that already exists; set it on that
environment's own backend service too and let it redeploy.

## The relay is on another machine. Never stand one up locally

**The workstation relay does not run on the machine your session runs on, and you must never install,
start, or configure one there.** It is a packaged Windows service on a separate GP-credentialed
workstation and it is already enrolled. The stub above is a container in Railway, not a relay on your
box, and the `PREVIEW_REAL_RELAY` handoff is a Railway variable, not a visit to that workstation.

What that rules out, because each of these has burned a session:

- Do not look for `%LOCALAPPDATA%\UCNexusRelay` here. Its absence is the expected state, not a missing
  dependency.
- Do not read "nothing listening on `127.0.0.1:7321`" as a fault. That port is only ever open on the
  relay workstation.
- Do not install a relay to "unblock testing". One without GP credentials connects and then fails
  every op, which is strictly worse than being honestly disconnected. This dev box is not
  domain-joined and cannot authenticate to GP SQL at all.
- Do not edit a `config.toml` you had to create. Editing `[channel] extra_backend_urls` on the
  workstation is no longer how a preview gets a relay, and `backend_url` is never touched by anybody:
  production's URL comes from the relay's baked default, and retyping it with one character wrong
  silently demotes the production channel to the TUBC sandbox pin (see the safety note in #414).

`connected: false` on an environment you did not hand to the real relay is a workflow or a stub
problem, not somebody else's machine - read the run log. `connected: false` on one you DID hand over
is a state on that workstation: report it and ask.

## A red preview-env check

Every deployment in the environment was created by the workflow and waited on by id, so a red check
means a build or a boot failed - there is no "Railway skipped a service" shape left, and no CLI
redeploy dance to run. The comment names which gate failed (backend, relay, frontend, graphql,
sign-in) and the run log names the deployment id it was waiting on; open that deployment in Railway
and read its build and runtime logs.

Re-running the workflow is the retry. It is idempotent: it resolves the environment it already made,
reuses the session key out of its own comment, reuses the stub secret when the backend already carries
its hash, and reuses a deployment that already carries this commit rather than building it again.

Two failures worth naming, because they have their own handling and their own log lines:

- **A forked environment comes up with no Postgres volume.** Railway's environment duplication copies
  services and variables but drops the volume stanzas, so Postgres crash-loops on `Railway volume not
  mounted` while its deployment still reads SUCCESS. The workflow detects that line in the
  deployment's runtime logs, creates the volume, and redeploys. If even a fresh fork cannot be healed
  it posts "stranded by Railway provisioning" and fails; re-run to retry.
- **The sign-in link never reaches 302.** `/testing/session` answers 302 only when the key hash is
  live on the *running* backend and the Clerk mint works, so it is the probe that proves the
  handed-out link rather than `/health`. `E2E_CLERK_USER_ID` unset on the environment is the usual
  cause; the human `/testing/clerk-sign-in` fallback is in the Getting Started section of
  [CLAUDE.md](CLAUDE.md).

**Never merge the PR whose environment you are testing in** - `preview-env-cleanup.yml` deletes the
environment on close, mid-session, and every fetch then fails for a reason that looks like a network
fault.

## One-time ops, outside any PR

None of this is created by a PR and none of it is per-PR work. It is recorded here because each piece
fails silently when it is missing.

- **Repo secret `RAILWAY_WORKSPACE_TOKEN` and repo variable `RAILWAY_PROJECT_ID`.** Make the token a
  **workspace** token, at [railway.com/account/tokens](https://railway.com/account/tokens) with the
  workspace picked in the dropdown. A **project token cannot be used here at all** - it authenticates
  with a `Project-Access-Token` header rather than `Authorization: Bearer` and is scoped to one
  environment, so it could neither authenticate the call nor see the siblings this whole workflow is
  about. Railway has no read-only scope on any token type.

  Verify a token before setting it, because a bad one fails into an empty list rather than an error.
  PowerShell, since that is the shell on the machines this gets run from - **not** the curl one-liner
  you may reach for first. Single-quoted JSON does not survive PowerShell's native-command argument
  parsing, and Railway answers `invalid JSON, only supports object and array`, which reads like a bad
  token rather than a mangled body:

  ```powershell
  $body = @{
    query     = 'query($id:String!){ environments(projectId:$id){ edges{ node{ name } } } }'
    variables = @{ id = '<PROJECT_ID>' }
  } | ConvertTo-Json -Depth 5

  Invoke-RestMethod -Uri 'https://backboard.railway.com/graphql/v2' -Method Post `
    -ContentType 'application/json' -Headers @{ Authorization = 'Bearer <TOKEN>' } `
    -Body $body | ConvertTo-Json -Depth 8
  ```

  It should list `production` alongside every `uc-nexus-pr-<N>`. An `errors` array instead means the
  token type is wrong or the project id is.
- **`E2E_CLERK_USER_ID` on the production backend**, so every fork inherits it. It names the dedicated
  e2e account the sign-in link mints - not a person, Admin/Manager, and refused on production
  (`app/auth._reject_e2e_account_in_production`), which is what makes the link safe to sit in a public
  PR comment.
- **`PREVIEW_TESTING_SIGN_IN_SECRET_HASH` on the production backend**, inherited by every fork, for the
  human `/testing/clerk-sign-in` fallback. `TESTING_SIGN_IN_SECRET_HASH` stays unset on production on
  purpose: production resolves to no digest however many of these it holds, which is what makes
  storing the inherited one there safe.
- **`PREVIEW_REGISTRY_SECRET` on the production backend.** The `PREVIEW_REAL_RELAY` handoff above
  depends on it. It belongs on production only, for the same reason the old `RAILWAY_API_TOKEN` did: a
  preview environment must not be able to speak for the whole project.
- **Delete `RAILWAY_API_TOKEN` from the production backend.** It powered `GET /relay-channels`, the
  discovery route the workstation relay polled to find preview environments and dial them on its own.
  The stub replaces that for the default case and the announce/push pair above replaces it for the
  real-relay case, so a write-capable Railway token no longer has to sit on a public-facing service.
  Discovery was fragile in its own right: the poll carried a second copy of the relay credential that
  could drift from the one the live socket had already proven, which is how #654 left every fresh
  preview relay-dark while the socket itself was healthy - and a token that stopped working returned
  an empty list, indistinguishable from "every PR closed".
- **Switch Railway's own PR-environments toggle (`prDeploys`) off**, once this is on master. The
  workflow forks every environment itself and `preview-env-cleanup.yml` deletes it on close (Railway
  only tears down environments it created). Leaving the toggle on is not destructive - the workflow
  resolves an environment Railway made instead of forking one, and repoints its triggers at the PR
  branch - but it means two systems create environments while only one owns the builds.

## What a PR environment still cannot show

**A relay op that does not exist in the packaged build.** This applies to the real-relay path: the
workstation runs a published release, so a PR that adds to `_OPS` answers `unknown_op` ->
`RELAY_OP_UNSUPPORTED` there, just as it does on production before the relay is rebuilt (its own
distinct UI state, worth checking on purpose during the deploy-before-rebuild window). The stub is
built from the PR branch, so it has the new op - which means the stub is the right place to exercise
op *plumbing*, and the workstation is still the only place to prove the op against GP.

To put a branch build on the workstation for a session: `gh workflow run relay-release.yml --ref
<branch>` uploads a zip as a workflow artifact and publishes nothing. The full procedure, including
how the release build gets restored afterwards, is the "testing a PR that adds a new op" section of
`relay/README.md`. It is a manual install by design.

Note also that pushes to master auto-publish the relay as a **prerelease**
(`.github/workflows/relay-release.yml`), and the workstation follows stable releases - so a merge does
not move it. Promoting a build is deliberate: `gh release edit <tag> --prerelease=false`.

## Still-true notes from earlier sessions

- **The e2e account is real.** Every environment inherits production Clerk keys, so the identities in
  a PR environment are real staff accounts even though the Postgres data is disposable. Sign in as the
  account you were given; do not mint tokens for colleagues' accounts to test role behaviour.
- **A GP buyer must be assigned to the project you test on**, or Register in GP refuses with "Buyer X
  is not assigned to this project" (#216). Admin -> Buyers -> Add Buyer.
- **Verified relay-down assertions, PR #412** (issue #409's buyer dropdown): the field rendered
  `role="combobox"`, disabled, still showing the stored `mira`, with "The GP relay is not connected, so
  this cannot be changed right now." That was the default state then; it is the deliberate state now
  (remove the stub service), and the assertions still hold.
- **Verified full GP click-through, pr-511, 2026-08-05**: PO0000095 against ALLEGION, from
  Create-GP-Job through to the back-order grid, entirely by clicking, with the real relay. That is the
  bar the `PREVIEW_REAL_RELAY` path exists to reach.
- **Seeded install labels take `RAILWAY_ENVIRONMENT_NAME` verbatim**, which on a preview is
  `uc-nexus-pr-<N>` rather than `pr-<N>` (verified on PR #421).
