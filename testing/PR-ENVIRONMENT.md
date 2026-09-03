# The PR test environment

What a UC Nexus PR environment is, what it can and cannot show you, and how to read it when it does
not come up. Read this **before** a testing session; the module-by-module knowledge you need *during*
one is in [CLAUDE.md](CLAUDE.md) alongside it.

Separate from that file on purpose: this is a procedure invalidated by infrastructure changes, and it
went stale silently once already - it claimed for months that adding a relay channel needed a restart,
which stopped being true at #456 and cost a session. Anything here that describes relay behaviour
should cite the code it came from so a reader can check rather than trust.

## There is nothing to set up

**Every open, non-draft PR gets a built environment, a copy of production's database, and a sign-in
link.** Open the PR, wait for the `preview-env` check, and read its sticky comment. Draft PRs and bot
PRs get nothing, by design - there would be nothing to sign into.

The comment carries four things:

- the sign-in link, `<backend>/testing/session?key=<K>`. Navigate it once and you land on `/app` as the
  dedicated e2e account (Admin/Manager). It mints a fresh Clerk ticket every visit, so it never goes
  stale and survives a DevAction reset.
- the agent protocol, verbatim (below). It is the procedure, not a summary of one.
- one relay line: `relay: connected, companies TUBC`, or `relay: DOWN` and what to do about it.
- the two URLs: `https://frontend-uc-nexus-pr-<N>.up.railway.app` and
  `https://backend-uc-nexus-pr-<N>.up.railway.app`.

The environment is named `uc-nexus-pr-<N>`, NOT `pr-<N>` - the Railway CLI answers `Environment
"pr-511" not found` for the latter, which reads like the environment is missing.

**`.github/workflows/preview-env.yml` owns every build in it.** It forks the environment from
production, deletes the environment's deployment triggers so Railway can never push-deploy it (and so
never posts a "Deployment cancelled" commit status for a build the workflow superseded), sets the
testing variables, and then deploys each of the three services for that PR head commit and waits on
the deployment id it created. Railway is not asked to decide what to build, and the workflow reads no deployment it did not
start. What follows is what the environment can show you, and how to read it when the check goes red -
not a checklist to run per PR.

## The agent protocol

Printed verbatim in every sticky comment, and the whole procedure for an agent handed an environment:

```
agent protocol
1. the preview-env check and this comment are the only source of truth for this environment. do not query railway and do not read the workflow to diagnose it
2. red check: re-run it once (gh run rerun <run id>). still red: report the gate this comment names to the user and stop
3. relay DOWN: tell the user the workstation relay must be up, then poll <backend>/health every two minutes. do not test GP-dependent flows meanwhile. do not install, configure, or look for a relay anywhere, on any machine
4. never merge the PR under test. the environment is deleted on close
5. reset is the DevAction: reset data button. it re-clones production into this PR's copy and touches nothing else
```

## There is one relay, and the comment's relay line is the truth

The workstation relay dials every preview on its own. The preview announces itself to production's
registry (`app/services/preview_announce.py`, `X-Preview-Registry-Secret`); production holds the
announcements (`app/services/preview_registry.py`) and pushes the channel list down the socket the
relay already holds, and the relay is dialling within a couple of minutes. There is nothing to set per
PR and nothing to hand over - the old per-environment relay variable and the throwaway relay service
that went with it are both gone.

So read its state off the comment and believe it:

- `relay: connected, companies TUBC` - the GP-gated half of the app is reachable, against real GP.
- `relay: DOWN` - the workstation, or the relay service on it, is off. **Wait, and tell the user.** Do
  not test GP-dependent flows meanwhile, and do not go looking for a relay anywhere (below). Poll
  `<backend>/health` every two minutes; `relay_connected` turning true is the all-clear.

**Relay state is reported, never gated.** A green `preview-env` check with `relay: DOWN` under it is
correct and means exactly what it says: the environment is up, the office machine is not. The same
pair is on `GET <backend>/health` (`relay_connected`, `relay_companies`), and in the app as

```
{ relayStatus { connected company build } }
```

**GP testing is TUBC, and only ever TUBC.** It is the shared test company in GP; the workstation is
enrolled for it. Never point a testing session at another company.

The relay-down half of the app is worth testing on purpose whenever the line says DOWN - disabled
controls, "not connected" copy, held values still displaying, the queued-write outbox - and it is
awkward to reach on production without stopping the relay for everyone.

## The database is a clone of production

**A preview's Postgres is not empty.** The backend clones production's Nexus database into it on first
boot, over a read-only role production creates from `PREVIEW_CLONE_PASSWORD`, so an environment starts
with production's projects, POs, inventory and settings rather than nothing to click on.

- **GP is never cloned.** GP is a live SQL server the relay talks to; the copy holds UC Nexus rows
  only. TUBC in GP is the shared test company, and reads and writes against it are real.
- **The copy carries production's UBC and UCSH rows, and in a preview those are relay-dark.** They
  display, and anything on them that needs GP fails the way a relay error fails, not the way missing
  data does. Test on TUBC.
- **`DevAction: reset data` re-clones production into this PR's copy** and touches nothing else. It is
  the reset; there is no schema-drop button any more.
- **A branch behind master's migrations does not boot.** The clone carries production's alembic
  revision, so a branch that does not have that revision cannot run against it: the backend prints
  `production's schema is at <rev> and this branch does not have it: merge master into the branch` and
  exits, and `preview-env` names that line as the failing gate. Merge master into the branch and push.

**Inheritance is a copy taken when the environment is forked, not a live link** (#431). A variable
added to production afterwards never reaches an environment that already exists; set it on that
environment's own backend service too and let it redeploy.

## The relay is on another machine. Never stand one up locally

**The workstation relay does not run on the machine your session runs on, and you must never install,
start, or configure one there.** It is a packaged Windows service on a separate GP-credentialed
workstation and it is already enrolled. **`relay: DOWN` is not a task assigned to you** - it is a
machine in the office that is off, or whose service has stopped. Tell the user, poll
`<backend>/health`, and leave GP-dependent flows until it is back. Nothing you can do from here helps,
and everything that looks like it would makes it worse.

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

`connected: false` is a state on that workstation. There is no second relay left to blame it on:
report it and ask.

## A red preview-env check

Re-run it once - `gh run rerun <run id>`, the id is in the comment's protocol block. The retry is
idempotent: it resolves the environment it already made, reuses the session key out of its own
comment, and reuses a deployment that already carries this commit rather than building it again.

**Still red after that one re-run: report the gate the comment names and stop.** Do not open Railway
and do not read the workflow to work out what it meant - the comment names the failing gate (backend,
frontend, graphql, sign-in) or the exact backend line that blocked the boot, and that line is the
report.

Three failures worth recognising in the comment, because each has a different answer:

- **The backend will not boot on this branch.** The comment carries `production's schema is at <rev>
  and this branch does not have it: merge master into the branch`. Nothing about the environment is
  wrong; merge master and push.
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
- **`PREVIEW_REGISTRY_SECRET` on the production backend.** Preview discovery depends on it: blank on
  either side closes the announce route with a 401 and the relay keeps dialling production alone. It
  belongs on production only, for the same reason the old `RAILWAY_API_TOKEN` did: a preview
  environment must not be able to speak for the whole project.
- **`PREVIEW_CLONE_PASSWORD` on the production backend**, inherited by every fork. Production creates
  the read-only `preview_clone` role from it, and that role is what a preview's first boot reads
  production's database through. Missing, a preview comes up with an empty database.
- **Delete `RAILWAY_API_TOKEN` from the production backend.** It powered `GET /relay-channels`, the
  discovery route the workstation relay polled to find preview environments and dial them on its own.
  The announce/push pair above replaces it, so a write-capable Railway token no longer has to sit on a
  public-facing service. Discovery was fragile in its own right: the poll carried a second copy of the
  relay credential that could drift from the one the live socket had already proven, which is how #654
  left every fresh preview relay-dark while the socket itself was healthy - and a token that stopped
  working returned an empty list, indistinguishable from "every PR closed".
- **Switch Railway's own PR-environments toggle (`prDeploys`) off**, once this is on master. The
  workflow forks every environment itself and `preview-env-cleanup.yml` deletes it on close (Railway
  only tears down environments it created). Leaving the toggle on is not destructive - the workflow
  resolves an environment Railway made instead of forking one, and deletes its triggers just the same -
  but it means two systems create environments while only one owns the builds, and Railway's own
  first deploy of that environment is the one build the workflow adopts rather than starts.

## What a PR environment still cannot show

**A relay op that does not exist in the packaged build.** The workstation runs a published release, so
a PR that adds to `_OPS` answers `unknown_op` -> `RELAY_OP_UNSUPPORTED` there, just as it does on
production before the relay is rebuilt (its own distinct UI state, worth checking on purpose during
the deploy-before-rebuild window). The preview does not change that - it is the same workstation relay
on the other end, whatever the PR branch adds to `relay/`.

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
  this cannot be changed right now." Those assertions still hold, and a `relay: DOWN` line is now when
  to check them.
- **Verified full GP click-through, pr-511, 2026-08-05**: PO0000095 against ALLEGION, from
  Create-GP-Job through to the back-order grid, entirely by clicking, with the workstation relay. That
  is the bar a preview reaches when the relay line reads connected.
