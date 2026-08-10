# Setting up a PR test environment

How to get a UC Nexus PR environment into a state you can actually click through, and what it can and
cannot show you. Read this **before** a testing session; the module-by-module knowledge you need
*during* one is in [CLAUDE.md](CLAUDE.md) alongside it.

Separate from that file on purpose: this is a procedure invalidated by infrastructure changes, and it
went stale silently once already - it claimed for months that adding a relay channel needed a restart,
which stopped being true at #456 and cost a session. Anything here that describes relay behaviour
should cite the code it came from so a reader can check rather than trust.

**Every open, non-draft PR gets an environment automatically**, cloned from production with a fresh
empty database, at `https://frontend-uc-nexus-pr-<N>.up.railway.app` and
`https://backend-uc-nexus-pr-<N>.up.railway.app`. Draft PRs do not get one.

For signing in (`/testing/clerk-sign-in`, `TESTING_ENABLED`, the `X-Testing-Secret` header) see
the Environment and Getting Started sections of [CLAUDE.md](CLAUDE.md) - the runbook below refers to
them rather than restating them.

## The relay is on another machine. Never stand one up locally

**The relay does not run on the machine your session runs on, and you must never install, start, or
configure one there.** It is a packaged Windows service on a separate GP-credentialed workstation, it
is already enrolled, and it finds new PR environments by itself (see the discovery section below).
Connecting it is not part of an agent's test loop.

Your entire relay responsibility is to **confirm the channel is up and then test through it**:

```
{ relayStatus { connected company build } }
```

`connected: true` with company TUBC means you are done thinking about the relay. `connected: false`
means you report it and ask - it is a state on somebody else's machine, not a task in front of you.

What that rules out, because each of these has burned a session:

- Do not look for `%LOCALAPPDATA%\UCNexusRelay` here. Its absence is the expected state, not a
  missing dependency.
- Do not read "nothing listening on `127.0.0.1:7321`" as a fault. That port is only ever open on the
  relay workstation; the relay binds to localhost *there*, which is the whole reason the WebSocket
  channel to Railway exists.
- Do not install a relay to "unblock testing". One without GP credentials connects and then fails
  every op, which is strictly worse than being honestly disconnected. This dev box is not
  domain-joined and cannot authenticate to GP SQL at all.
- Do not edit a `config.toml` you had to create.

**In a hurry, and only when sitting at the relay workstation:** `testing/scripts/connect-pr-env.ps1
<PR#>` does the hookup and reports whether it worked. It edits a file that exists on that one
machine, so running it anywhere else fails at its channel step by design. The rest of this file is
what it does and how to diagnose it when it does not.

## The relay discovers PR environments on its own

Production answers `GET /relay-channels` with the preview environments that exist right now, read from
the Railway API; the relay asks about once a minute and unions the answer with its config file. So a
new PR environment gets a GP channel without anybody touching the workstation, and a closed one is
retired the same way.

Setup, once, ever: `RAILWAY_API_TOKEN` on the **production** backend service, nowhere else - a preview
environment must not be able to advertise other preview environments, so a backend without the token
answers an empty list, which is the correct answer everywhere but production.

Make it a **workspace** token, at [railway.com/account/tokens](https://railway.com/account/tokens)
with the workspace picked in the dropdown. Railway has three kinds and the other two do not fit: an
account token reaches everything the account can, and a **project token cannot be used here at all** -
it authenticates with a `Project-Access-Token` header rather than `Authorization: Bearer`, and it is
scoped to a single environment, so it could neither authenticate the call nor see the siblings this
whole feature is about. Railway has no read-only scope on any of them; nothing in this path ever
issues a mutation, but the token is write-capable and belongs on production alone.

Verify it before setting it, because a bad token fails silently into an empty list. PowerShell, since
that is the shell on the machines this gets run from - **not** the curl one-liner you may reach for
first. Single-quoted JSON does not survive PowerShell's native-command argument parsing, and Railway
answers `invalid JSON, only supports object and array`, which reads like a bad token rather than a
mangled body:

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

What keeps this safe, given a network answer now decides what a GP-credentialed process dials:

- The relay accepts only `wss://backend-uc-nexus-pr-<N>.up.railway.app/relay-link`, anchored and
  literal apart from the number. No answer can name an arbitrary host.
- A discovered channel is never the primary one. `is_primary_backend_url` decides that by identity
  against the relay's own baked-in production URL, so everything discovered inherits the TUBC sandbox
  pin. The worst a bad entry can do is offer a channel that may only touch the sandbox company.
- Discovery only ADDS. It cannot remove or reorder what `config.toml` names, and it cannot switch
  itself on where the token is absent.
- A backend that cannot be reached leaves the last known list in place, so a blip does not tear down
  live channels. `discover_preview_backends = false` under `[channel]` turns it off entirely.

`extra_backend_urls` is still there and still the right tool for a backend discovery cannot know about
- a local dev backend, or anything outside this Railway project.

## A PR environment is relay-disconnected by default, and that is useful

By default a PR environment always reports `relayStatus.connected: false`, and no amount of waiting
changes it. Two independent reasons, both addressed by #414 but neither automatic:

1. The relay has to be dialling this backend. Since #414 it can hold a LIST, so a PR backend is added
   *alongside* production rather than replacing it; since #456 the list is re-read every
   `CHANNEL_RECONCILE_SECONDS` (see `relay/src/ucnexus_relay/channel.py`) so a change needs no
   restart; and since discovery it does not need a human either - see the section above. This reason
   is therefore mostly historical now, and a preview environment that stays disconnected for more than
   a couple of minutes means discovery is off or failing rather than "nobody has added it yet".
2. Relay installs live in Postgres and a PR environment boots a fresh empty one, so the handshake is
   refused (4403) even if the relay does dial. Since #414 the backend seeds a trusted install on
   startup from `RELAY_SEED_SECRET_HASH` - the SHA-256 already in production's row, copyable from
   Admin -> Relay Installs ("Seed hash" column). Where that variable goes is the part that catches
   people out (#431):
   - It belongs on the **production** backend service and stays there inert. PR environments are cloned
     from production, so that is the only place a new one can inherit it from; production refuses to
     seed and logs the refusal at INFO, which is the intended steady state, not something to tidy up.
   - **Inheritance happens at environment creation only.** Setting it on production does nothing for a
     PR environment that already exists - set it on that environment's own backend service as well.
     Verified 2026-07-30: pr-430 predated the variable and stayed GP-blind until it had its own copy.
   - Seeding runs at backend startup, so the variable only takes effect on that service's next deploy.

Read the default state as a free test fixture rather than a limitation. The relay-down half of any
GP-gated feature - disabled controls, "not connected" copy, held values still displaying, buttons that
must not be clickable - is exactly what a PR environment exercises by construction, and it is the half
that is otherwise awkward to reach on production without stopping the relay for everyone.

**But "by default" is doing real work in that heading.** Disconnected is a state you were handed, not
a property of PR environments, and leaving it that way is a choice with a cost: with no relay there
are no projects (they come from the GP job sync), and with no projects there is no schedule import, no
PO, no receiving, no inventory, no assembly, no shipping. Nearly the whole spine of the app is
unreachable. If you find yourself writing "this surface cannot be tested here", connect the relay
first and check whether that is still true. It usually is not.

A PR environment with a connected relay is pinned to **TUBC** and refuses every other company with
`company_not_allowed_on_channel`, reads and writes alike. Reads and writes both work against TUBC;
that pin is what makes serving writes off a test backend acceptable at all.

## Connect a PR environment for full click-through testing

`testing/scripts/connect-pr-env.ps1 <PR#>` does steps 2-4 and waits for the confirmation in step 5.
Run it rather than doing this by hand; the manual steps are here so a failure is diagnosable, and
because a script that nobody can read is its own kind of stale documentation.

Each step lists **the signal that proves it worked**. Check the signal rather than assuming - every
step here has failed silently at least once.

1. **Find the Railway environment.** It is named `uc-nexus-pr-<N>`, NOT `pr-<N>` - the CLI answers
   `Environment "pr-511" not found` for the latter, which reads like the environment is missing.
   Services inside it are `backend` and `frontend`; the public hostnames are
   `backend-uc-nexus-pr-<N>.up.railway.app`.
   - Signal: `railway environment list --json` lists it, with `meta.prNumber` matching.
2. **Nothing, if `PREVIEW_TESTING_SIGN_IN_SECRET_HASH` is set on production.** A preview inherits that
   digest at creation and resolves it automatically, so the sign-in secret works on a brand new
   environment with nothing set on it. Production itself always resolves to no digest however many of
   these variables it holds, which is what makes storing it there safe - see the Auth bullet in
   [CLAUDE.md](CLAUDE.md)'s Environment section for why that matters.
   - Signal: `GET /testing/clerk-sign-in` with the matching `X-Testing-Secret` answers 200, not 401.
   - Per-environment override, still supported and still wins: set `TESTING_SIGN_IN_SECRET_HASH` on
     that backend. Needed only for an environment that predates the inherited variable, or one you
     deliberately want on its own secret.
3. **`RELAY_SEED_SECRET_HASH` on that same backend**, so the relay's handshake is accepted rather than
   refused 4403. Usually inherited at environment creation; set it by hand if the environment predates
   the variable.
   - Signal: same `railway variables` read shows it set.
4. **Nothing. The relay finds the environment by itself.** It asks production which preview
   environments exist and dials them, re-checking about once a minute, so an environment created after
   the last time anybody touched that workstation is picked up without a visit. This step used to be
   the whole reason a PR environment needed a human, and it is the step that kept getting forgotten.
   - Signal: `relay.log` on the workstation logs `backend channels changed` with your URL under
     `added`, then `channel connected`, within a minute or two of the environment existing. From this
     side, just read `relayStatus`.
   - Requires `RAILWAY_API_TOKEN` on the PRODUCTION backend. That is the one piece of setup, done
     once, ever - see the discovery section below. Without it discovery answers an empty list and
     everything falls back to the manual path below.
   - Discovery only ever ADDS. `extra_backend_urls` still works and still wins nothing away from you,
     so the manual route stays available for a backend discovery cannot know about (a local dev
     backend, an environment outside this Railway project).

   The manual route, performed ON THE RELAY WORKSTATION and not on the machine you are reading this
   from. In that machine's `%LOCALAPPDATA%\UCNexusRelay\config.toml`, under `[channel]`:
   ```toml
   extra_backend_urls = ["wss://backend-uc-nexus-pr-<N>.up.railway.app/relay-link"]
   ```
   **Never touch `backend_url`** - production's URL comes from the baked default, and retyping it with
   one character wrong silently demotes the production channel to the TUBC pin (see the safety note in
   #414). Write the file as UTF-8 **without a BOM**: PowerShell's `Set-Content -Encoding utf8` adds one
   in 5.1, `tomllib` then refuses the file, and the relay crashes at startup.
   - Signal: within ~10s, `%LOCALAPPDATA%\UCNexusRelay\relay.log` logs `backend channels changed` with
     your URL under `added`, then `channel connected` with `restricted_to: ["TUBC"]`.
5. **Confirm the app sees it.** Sign in and open the PO module.
   - Signal: the header reads `RELAY CONNECTED`, not `GP RELAY NOT DETECTED`.
6. **Assign your GP buyer to the project you will test on**, or Register in GP refuses with "Buyer X is
   not assigned to this project" (#216). Admin -> Buyers -> Add Buyer.
   - Signal: the buyer grid lists a row pairing your buyer with that project.
7. **Tear down when the PR closes**: remove the URL from `extra_backend_urls` (or run the script with
   `-Disconnect`). A closed environment otherwise retries forever against a backend that is gone.
   - Signal: `relay.log` logs `backend channels changed` with your URL under `removed`.

With that done the whole chain is click-through: GP job sync populates real TUBC projects, the import
wizard runs against a real schedule, Register in GP writes a real PO to TUBC and stamps the PM00200
vendor onto it, and receiving populates from that. Proven end to end on pr-511 (2026-08-05): PO0000095
against ALLEGION, from Create-GP-Job through to the back-order grid, entirely by clicking.

What a PR environment cannot show out of the box is a NEW op. The workstation runs a packaged build, so
a PR that adds to `_OPS` answers `unknown_op` -> `RELAY_OP_UNSUPPORTED` there just as it does on
production before the relay is rebuilt (its own distinct UI state, worth checking on purpose during the
deploy-before-rebuild window). To exercise the op itself, build the PR's branch with
`gh workflow run relay-release.yml --ref <branch>` and install that zip on the workstation for the
session - the full procedure, including how the release build gets restored afterwards, is the
"testing a PR that adds a new op" section of `relay/README.md`. It is a manual install by design.

Verified on PR #412 (issue #409's buyer dropdown), in the default disconnected state: the field
rendered `role="combobox"`, disabled, still showing the stored `mira`, with "The GP relay is not
connected, so this cannot be changed right now." - all four assertions met without touching production.

Seeding verified live on PR #421 (#414 itself), against that PR's own environment: setting
`RELAY_SEED_SECRET_HASH` produced exactly one install row labelled `seed:uc-nexus-pr-<N>` (company
TUBC, ENROLLED), the Seed hash cell truncated to 8 chars with a copy button carrying the full 64-char
digest, a provisioned-but-unenrolled row showing `—` and no button, and a second full redeploy still
leaving exactly one seeded row. Note the label takes `RAILWAY_ENVIRONMENT_NAME` verbatim, which on a
PR environment is `uc-nexus-pr-<N>` rather than `pr-<N>`.
