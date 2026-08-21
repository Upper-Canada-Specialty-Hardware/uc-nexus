# Simulated User Testing Guide

This is a tester's knowledge journal for UC Nexus. It documents how the app works from a front-end user's perspective and how to drive it via Chrome DevTools MCP.

> **Setting an environment up is a different document: [PR-ENVIRONMENT.md](PR-ENVIRONMENT.md).**
> Getting a PR environment into a state you can click through - the relay channel above all, without
> which there are no projects and so almost nothing is reachable - lives there, with a runbook and
> `scripts/connect-pr-env.ps1`. Read it first; this file is what you need *during* a session, not
> what you do to start one.

**Maintain this file:** Update it when you discover new behaviors, gotchas, or workflows during testing. This is a living document that grows with each testing session.

---

## Environment

**A Railway PR environment is the only place end-to-end testing happens** (issue #182 pivot - the localdev runtime was dropped for UC Nexus e2e; zero local setup needed).

> **The `*-production-*` Railway services are off-limits to automated testing sessions.** Never
> point a testing session at them, and never fire mutation probes at them - not to "just check"
> something after a merge, and not because a change is already deployed there. If a thing genuinely
> can only be observed on production, ask a human first.
>
> As of 2026-07-30 production carries no live data yet - UC Nexus is still in a testing state, and
> the production environment is where humans (the user and executives) test. The split is
> deliberate anyway: agents test on Preview Environments to get ahead of the day production holds
> real data. The plan is for today's "production" to become a proper staging environment, with a
> true production created alongside; the agent-side rule does not change at any point in that
> evolution.

- **Railway PR environments, a.k.a. "Preview Environments" (the testing target)** (ENABLED 2026-07-29, `prDeploys` on the project; bot PRs like dependabot deliberately excluded): every non-draft PR gets a full ephemeral replica (frontend + backend + fresh empty Postgres, migrated on boot) named `uc-nexus-pr-<N>`. Do not wait for a Railway bot comment - none was observed; the URLs are derivable: `https://backend-uc-nexus-pr-<N>.up.railway.app` / `https://frontend-uc-nexus-pr-<N>.up.railway.app`. Substitute them into the sign-in flow below; verified live on PR #401 (`/health` 200, `/testing/clerk-sign-in` mints tokens, GraphQL serves the fresh DB). Data starts empty; seed via the import fixture. No PR open for what you need to test? Open a throwaway one - that is cheaper than the alternative. `VITE_GRAPHQL_URL` is a reference variable (`https://${{backend.RAILWAY_PUBLIC_DOMAIN}}/graphql`) so each environment self-wires; `TESTING_ENABLED` and Clerk keys inherit from production. **That inheritance is a copy taken when the environment is created, not a live link** (#431): a variable added to production afterwards never reaches a PR environment that already exists, so set it on that environment's own backend service too and let it redeploy. Found the hard way with `RELAY_SEED_SECRET_HASH` on pr-430 - see the relay section below. **A PR that only touches one service's directory only deploys that service in its environment** (root-directory change filtering - PR #401 was backend-only and the frontend showed `latestDeployment: null`). The missing service shows one `SKIPPED` deployment and its `/health` 404s. **A PR touching NEITHER `backend/` nor `frontend/` - a relay-only or docs-only one - leaves the whole environment unbuilt, Postgres included**, and the backend then dies on `could not translate host name "postgres.railway.internal"`, which reads like a networking fault rather than a service that was never started. **The `preview-env` workflow now guarantees all three services** (`.github/workflows/preview-env.yml`, preview-env autonomy plan): on every non-draft push it force-deploys, over the Railway API, any of Postgres / backend / frontend that has no successful deployment in the environment - Postgres first, the backend only after Postgres is up, then the frontend - and posts the "test environment ready" comment when they answer. So an unbuilt environment is self-correcting, and everything below is the MANUAL FALLBACK for a red `preview-env` check. Check the database first: `railway deployment list --service Postgres` returning nothing at all is the tell. Fix it from the CLI, in this order, no dashboard and no raw API call:

```
railway redeploy --project <id> --environment uc-nexus-pr-<N> --service Postgres --from-source -y
railway redeploy --project <id> --environment uc-nexus-pr-<N> --service backend  --from-source -y
```

`--from-source` matters - a plain `redeploy` re-runs the last deployment, and on a service that never deployed there is nothing to re-run. Database first, and then **wait for Postgres to be accepting connections, not merely deployed**: firing the backend 28 seconds behind it got `connection to server at "postgres.railway.internal" ... Connection timed out`, a different failure from the DNS one and equally misleading, because by then the name resolves fine. Give it a minute, or just redeploy the backend again. Hit on a relay-only PR, 2026-08-10.

Environments auto-delete when the PR closes, **so never merge the PR whose environment you are testing in** - it disappears mid-session and every fetch starts failing for a reason that looks like a network fault.
- **Local (manual fallback)**: frontend `http://localhost:5173`, backend `http://localhost:8000`. Run the backend with `poetry run uvicorn main:app --reload` (from `backend/`) and the frontend with `npm run dev` (from `frontend/`). Needs a local Postgres (not provided; the worktree-localdev adoption was dropped).
- **Auth**: Clerk sign-in, automated via one-time sign-in tokens (no manual password/verification needed).
  - **The agent path is the `/testing/session` link in the PR's "test environment ready" comment**
    (preview-env autonomy plan). `GET /testing/session?key=<K>` mints a ticket for a DEDICATED e2e
    account and 302s you onto the frontend signed in; the per-env key `K` is placed by the preview-env
    workflow and lives only in that comment. Everything below is the human `/testing/clerk-sign-in`
    fallback - reach for it only when the comment link is not working.
  - Backend endpoint `GET /testing/clerk-sign-in` generates the token (requires `TESTING_ENABLED=true`).
  - Since #422 the endpoint also requires a credential: an Admin/Manager `Authorization` bearer, or
    the shared testing secret in an `X-Testing-Secret` header. The secret is the bootstrap path on a
    fresh PR environment, where by definition no session exists yet.
  - **A Preview Environment resolves that secret on its own, with nothing set on it.** Production
    holds `PREVIEW_TESTING_SIGN_IN_SECRET_HASH`, every preview inherits it at creation, and the
    resolver reads it anywhere that is not production. `TESTING_SIGN_IN_SECRET_HASH` still stays
    unset on production on purpose - its secret path must not be mintable there - and production
    resolves to no digest however many of these variables it holds, which is what makes storing the
    inherited one there safe. Setting `TESTING_SIGN_IN_SECRET_HASH` directly on one environment
    still overrides, for an environment that predates the inherited variable or wants its own secret
    (see `backend/.env.example` for the generator one-liner). `TESTING_ENABLED` was re-enabled on
    production 2026-07-30 (humans test there until the staging/production split), so new Preview
    Environments inherit it on again; one created while it was still false needs it set by hand.
  - Navigate to the frontend URL with `?__clerk_ticket=TOKEN` to auto-authenticate.
  - Tokens are one-time use; fetch a fresh one each session. Works on any runtime with the same Clerk dev instance.
  - **Every environment inherits production Clerk keys**, so the accounts in a PR environment are real
    staff accounts and a session minted there is a real session. The Postgres data in a PR environment
    is disposable; the identities are not. Sign in as the account you were given, and do not mint
    tokens for colleagues' accounts to test role behaviour - ask instead. The one exception is the
    dedicated e2e account the `/testing/session` link mints: it is not a person, holds Admin/Manager,
    and is refused on production (`app/auth._reject_e2e_account_in_production`), which is why its
    sign-in link is safe to sit in a public PR comment.
  - The unauthenticated version of this endpoint was itself a vulnerability (#422 / #424), fixed by
    the gates above. Do not treat the endpoint answering on a given host as evidence that the host is
    a test environment - production answered it too, which is exactly what #424 shut off.
- **Test XML file**: `testing/fixtures/contracterp-74.xml` - TITAN hardware schedule export, use for Import wizard testing (upload via `upload_file`)

### Every resolver needs a token now (#415)

Until #415 most resolvers were reachable with no `Authorization` header at all, so an injected
`fetch('/graphql', ...)` helper that forgot the token still returned data and nothing looked wrong.
That is over: every resolver in `app/schemas/` calls `require_user` / `require_admin` / `require_role`
as its first statement, enforced by `backend/tests/test_resolver_gate_completeness.py`. The only
exception is `enrollRelayInstall`, which carries its own enrollment-token auth.

Consequences when driving the app by script:

- Always mint a token first - `await window.Clerk.session.getToken({skipCache: true})` - and send it
  as `Authorization: Bearer <token>`. A helper without one now gets
  `{"data": null, "errors": [{"message": "Authentication required", "extensions": {"code": "UNAUTHENTICATED"}}]}`
  on *every* query, not just the handful that used to be gated.
- Distinguish the three failure shapes: **no header** -> `Authentication required`; **unparseable
  token** -> `Malformed authentication token`; **valid token, wrong role** -> `FORBIDDEN`, e.g.
  `Admin/Manager role required`. Getting `Authentication required` from inside a signed-in page means
  your helper dropped the header, not that the session died.
- Admin-gated reads worth knowing, because a non-admin session gets FORBIDDEN rather than an empty
  list: `users`, `adminStats`, `adminOpeningStatuses`, `adminOpeningDeepDive`, `locationDuplicates`. Their writes too -
  the warehouse CRUD, `overrideInventoryQuantity`, `mergeLocations`.
- `require_admin` costs a Clerk Backend API round-trip per call (`require_user` does not), so a page
  hitting several admin resolvers at once is legitimately slower than the equivalent user page.

### Inventory can only be seeded through the relay - check this first

**Nothing puts new hardware into inventory except `createReceive`, and `createReceive` is
unconditionally GP-first through the on-prem relay.** If the relay is down there is no supported way
to seed stock, and every scenario downstream of "hardware exists" (approve a pull, stage a cart,
assemble a leaf, flag a deficiency, ship) is unrunnable. Do not improvise a workaround - re-scope the
session instead. Establish this in the first minute:

```
{ relayStatus { connected company build } }
{ inventoryRows { inventoryLocation { hardwareCategory quantity } } }
```

**The relay runs on a separate GP-credentialed workstation, already enrolled and already pointed at
the PR environments. Never install, start, or configure one on the machine your session runs on** -
`%LOCALAPPDATA%\UCNexusRelay` being absent and `127.0.0.1:7321` being closed are the expected state
here, not a dependency to satisfy. `connected: false` is a state on somebody else's machine: report
it and ask. Setting one up locally cannot work anyway, because this box is not domain-joined and
cannot authenticate to GP SQL. Full rule in
[PR-ENVIRONMENT.md](PR-ENVIRONMENT.md#the-relay-is-on-another-machine-never-stand-one-up-locally).

`connected: false` plus `inventoryRows: []` is the signature (the old `inventoryHierarchy` probe was
deleted with the accordion queries). Confirm it from the backend side
with `relayInstalls { label enrolled enrolledAt lastSeenAt }` and the Railway backend deploy log:

- A relay that is **running but not trusted** logs `"WebSocket /relay-link" 403` every ~30s forever.
  The workstation is dialling out fine; the backend is refusing the handshake.
- **Not dialling at all reads differently from being refused, and the pair of signals settles it in
  one minute.** A seeded environment always has its install row, so the row existing proves nothing;
  read `lastSeenAt` next to the deploy log. `lastSeenAt: null` on a `seed:uc-nexus-pr-<N>` row means
  no handshake has EVER succeeded there, and if the deploy log also carries **zero** `/relay-link`
  lines - not 403s, none at all - then nothing is dialling this backend and the cause is upstream of
  auth: the URL is not in the relay workstation's `extra_backend_urls`, or the relay is stopped.
  A 403 cadence with the same null `lastSeenAt` would instead mean it is dialling and presenting the
  wrong secret. Observed on pr-554, 2026-08-09: row `seed:uc-nexus-pr-554` (TUBC, enrolled,
  `lastSeenAt: null`), zero `/relay-link` lines across the deployment, `relayStatus.connected: false`,
  `projects: []`. That was the not-dialling signature, and at the time it meant a human had not added
  the URL on the workstation. **Since channel discovery it should not happen at all**: production
  serves the live preview list at `/relay-channels` and the relay picks a new environment up within a
  minute or two. So the same signature now means discovery is off or failing, and the first thing to
  check is whether `RAILWAY_API_TOKEN` is set on the PRODUCTION backend - without it the route
  correctly answers an empty list and every preview environment stays dark.
- **Prove the log records a refusal before you trust its silence.** "No `/relay-link` lines" only
  means "nobody dialled" if a dial would have left a line, and an empty log is equally consistent
  with logging being broken or the edge never routing the upgrade. Settle it in one shot by dialling
  it yourself from the signed-in page - a bogus handshake can only be rejected, so this is read-only:

  ```js
  new WebSocket('wss://backend-uc-nexus-pr-<N>.up.railway.app/relay-link');
  ```

  Then re-read the log. Exactly one new `"WebSocket /relay-link" 403` proves the endpoint is live,
  the edge passes the upgrade through, and refusals are recorded - so the zero lines before it are
  real evidence rather than an artefact. On pr-554 this turned "probably not dialling" into proof.
- **Check the seed hash matches production's before blaming the channel list.** The relay presents the
  secret it enrolled with against production, so a PR environment whose `RELAY_SEED_SECRET_HASH`
  drifted would dial and 403 forever. `railway variables --environment uc-nexus-pr-<N> --service
  backend --json` against the same read on `production`, compared, rules that out in seconds. On
  pr-554 they were byte-identical, which is what makes "not in `extra_backend_urls`" the remaining
  explanation rather than one of two.
- **`lastSeenAt == enrolledAt` is suggestive, NOT proof.** `last_seen_at` is written in two places:
  `enroll_install` (`relay_repository.py:70-71`) and `authenticate_secret` on a successful match
  (`:95`, committed by `main.py:170`). But `authenticate_secret` runs *only on the connect handshake* -
  the liveness heartbeat is an app-level ping/pong that never touches the DB. So a relay that connects
  once and holds the socket open for two days also shows exactly one write. The timestamp alone cannot
  tell "never authenticated" from "authenticated once at enrolment and still connected".
- **The deploy log is what settles it.** A held-open socket silences the ~30s dial cadence for its
  whole duration, so look for a *gap*: an unbroken 403 cadence with no `[accepted]` line means the
  channel never came up. Read it across the whole life of the deployment, not a sample window.
- **A 403 cadence that runs unbroken *through* the enrolment instant means a stale secret.**
  `enroll_install` stores a SHA-256 hash of whatever secret the relay generated, so a successful
  enrolment cannot leave the row wrong about it; if auth still 403s seconds later, the mismatch is in
  the secret the relay is presenting. Usual cause: enrolment rewrote `[auth] shared_secret` in
  `config.toml` while the **already-running relay service kept dialling with its old in-memory
  secret**. It needs a *restart*, not another enrol. The relay's inbound server is bound to
  `127.0.0.1:7321`, so there is no remote restart — **but since #353 PR B there is a remote fix.**
  Admin → Relay Installs → **Adopt next connection** on that install opens a 5-minute, single-use
  window in which the relay's next dial is accepted with whatever secret it is already presenting,
  and the secret is rebound. Watch for `relay adopt: presented secret bound to install` at WARNING,
  then an accepted `/relay-link`. The adoption is stamped on the row as `adoptedAt` / `adoptedBy`.
- The silent-decrypt path is gone (#352 logs the cause; #353 PR C removed the key from the
  authentication path entirely). Since migration `067` the relay secret is a SHA-256 hash, so a
  rotated or missing `RELAY_SECRET_ENC_KEY` can no longer orphan a relay. On a `relay handshake
  rejected` line, read `hash_rows` and `cause`. Since #382 retired the key, `legacy_rows` is always 0
  and `encryption_key_present` always false, so neither of those two distinguishes anything any more -
  a false `encryption_key_present` is the healthy state now, not a config problem to chase.
- `POST /admin/reset-data` **preserves** the `relay_installs` rows across the rebuild (#352), so a
  schema reset no longer orphans the on-prem relay.

### A queued GP write is not a failed one

Since #353 PR E, a `createReceive` or `registerPoInGp` submitted while the relay is unreachable is
**accepted onto a durable outbox** instead of failing. Recognise it before you conclude anything
about GP:

- The receive modal shows an amber *"Queued — the GP relay is offline"* panel, not the green
  "items added to inventory" one, and **nothing is in inventory yet** — the UC Nexus persist is
  deferred along with the GP write.
- A queued-writes chip appears in the app bar. Read the queue with:

```
{ gpOutboxSummary { pending inFlight failed oldestPendingAt lastDrainedAt } }
{ gpOutbox(limit: 20) { label op status attempts failureKind lastError } }
```

- **Bring the relay back and it drains itself** within about a second of `/relay-link` accepting
  (the route wakes the worker). `pending` goes to 0, `lastDrainedAt` advances, and the browser
  refreshes the affected lists on its own. Do not re-submit — the idempotency key belongs to the
  queued row, so a resubmit returns the same entry rather than posting twice.
- A `FAILED` entry is the one that needs a person: Admin → Relay Installs → **GP write queue**.
  `failureKind` says which kind of trouble it is — `gp_rejected` (eConnect said no; fix the input),
  `persist_failed` (GP committed but UC Nexus refused the state change), `exhausted` (retry budget
  gone), and `ambiguous`, which means the job reached the relay and **GP may already hold the
  write** — check GP before retrying, because a retry there can genuinely duplicate a receipt.
- If a scenario needs inventory *now* and the queue is stuck, the blocker is still the relay: seeding
  stock has no non-relay path. Re-scope the session rather than improvising.

Verified in this state on 2026-07-26: install `TAGGING3W10 (re-enroll after schema rebuild)` (company
TUBC), one row, enrolled 7/24 22:54:27.662369Z with `lastSeenAt` byte-identical to `enrolledAt`. The
403 cadence runs unbroken from 22:53:14Z (i.e. *before* enrolment) through 23:12Z and was still going
on 7/26, with no `[accepted]` line anywhere - so the WS channel has never once authenticated, while
the HTTP enrolment plainly succeeded. "The relay was working yesterday" refers to the service being
up and healthy on `127.0.0.1:7321`; that is independent of whether the backend trusts it.

**That outage is over - as of 2026-07-28 the same install authenticates normally** (`connected: true`,
company TUBC, `relay-v0.1.0-build.40`), and a full `registerPoInGp` + `createReceive` round trip
succeeds live with `gpOutboxSummary.pending` never leaving 0. Do not re-derive the 7/26 diagnosis from
this section; re-check `relayStatus` first. Two things worth knowing from that session:

- **The relay can drop mid-session and come back on its own, and the backend cannot tell you why.**
  Observed 2026-07-28: accepted 03:09:25Z, serving GP calls fine at ~03:40Z, `connected: false` by
  03:42Z, re-accepted 03:45:59Z - a ~4-5 minute hole. **Do not blame a redeploy without checking**;
  that was the first guess here and it was wrong. Rule-outs worth repeating:
  - `list-deployments` showed no backend deploy anywhere near the drop (the only one that day
    finished 03:09:22Z - which *caused* the 03:09:25 reconnect, 300ms after the old instance was
    removed, and is a different event from the drop).
  - `build.40` was already the newest relay tag and the relay was already running it, so there was no
    pending self-update to restart the process.
  - **An absent disconnect line means nothing.** `RelayGateway.unregister` logs *nothing*; the only
    relay line uvicorn ever emits is the `"WebSocket /relay-link" [accepted]` access log. A held-open
    socket therefore logs exactly one accept for its whole life, so "one accept and then silence" is
    ambiguous between healthy and dead - only `relayStatus` settles it.
  - What *is* signal: reconnect backoff is 1s doubling to a 30s ceiling, so 4-5 minutes of silence is
    ~8-10 missed dials, not one blip. And a rejected handshake would have logged 403s; there were
    none. So the relay either was not running or could not reach the backend at TCP/DNS level - both
    invisible from Railway, because neither reaches the ASGI app.
  - The answer lives in `relay.log` on the workstation (the file #370 gitignored). `_run_once`'s
    reconnect handler logs every attempt with a `category` - `dropped` / `server_restarting` /
    `unauthorized` / `conflict` - plus the error and current backoff. That log names the cause; the
    backend never can.
  - Reap timing for dating the drop: `HEARTBEAT_INTERVAL_SECONDS` 20s x `HEARTBEAT_MAX_MISSED` 2, so
    an armed connection flips to disconnected ~40s after the relay actually goes quiet.
- A `relay_status` traceback in the deploy log ending `jwt.exceptions.ExpiredSignatureError` /
  `AuthError: Invalid or expired authentication token` is **your own browser token ageing out**, not a
  relay fault. `relayStatus` is `require_user`-gated now, so a stale `getToken()` value in an injected
  fetch helper logs a full stack trace server-side. Re-mint with `getToken({skipCache:true})`.

### Seeding inventory: the PO must come from the wizard, not the Create PO dialog

**A manually-created PO seeds inventory but cannot open the assembly Reconciliation gate.** This costs
an hour if you learn it the hard way. The gate is `computeAvailableQty` in `ReconciliationStep.tsx`,
which for `purpose === 'assembly'` returns `breakdown.get('RECEIVED')` - the *lifecycle status of the
hardware-schedule item*, not live stock. Receiving against a PO built in the **Create PO dialog**
produces real `InventoryLocation` rows (`projectInventoryAvailability` shows them, the allocator would
happily reserve them) while every schedule row stays `Gap Remaining`, so Reconciliation still says
`No items have In Inventory status` and Next stays disabled.

To seed stock that *counts*, run the wizard with purpose **Create Purchase Orders** over the openings
you intend to assemble, then register + receive that PO. Its lines are bound to the schedule items, so
receiving flips them to `In Inventory: N` and the gate opens.

**A wizard-created PO loses that binding if you register it by calling `registerPoInGp` yourself.** The
mutation *replaces* the draft's line items with the set you send (that is its documented job - the
register dialog is allowed to edit them), so hand-built `lineItems` produce lines with no link back to
the schedule rows. The PO registers, GP takes it, the receive posts and inventory appears - and every
schedule item is still `PO_DRAFTED`, so the assembly gate refuses exactly as it does for a
Create-PO-dialog PO. Verified 2026-08-03 on pr-460: two POs (PO0000082, PO0000083) and two receipts
landed in TUBC and `projectInventoryAvailability` showed all four products, while the opening's
hardware still read as unpurchased across the board (`openingHardwareStatus` at the time, which
called it `PO_DRAFTED`; `adminOpeningDeepDive` now reports the same severed binding honestly, as
`notPurchased`). Drive the register
**dialog** when the schedule linkage matters; scripting the mutation is only safe when all you want is
stock in the pool. Keep the GP footprint small by using the
Reconciliation step's own checkboxes (PO purpose only): `Deselect All`, then tick just the one product
you want, and at the PO step check a single manufacturer card. Fill **Order As** on that step - an
import-created draft otherwise blocks the register dialog with per-line `Required` errors.

**The register dialog's Register button is silently inert while validation fails, and the buyer rule
is the one that catches you.** `validate()` in `GpPurchaseOrderDialog.tsx` refuses with
`Buyer <id> is not assigned to this project` when `registerProjectAllowed` is false, and a fresh PR
environment has an EMPTY `buyerAssignments` table - so the very first registration on any new
environment hits it. The button is not disabled and no toast fires; the only signal is the alert
already sitting at the top of the dialog, which reads like a warning rather than a blocker. If a
click produces no network request at all, that is what happened. Fix it properly at Admin -> Buyers
-> Add Buyer (pick the GP buyer your account is linked to, add the project), not by scripting the
mutation.

**A PO whose lines share a GP item number used to fail with eConnect 9191. It is the item numbers,
not the line count** (issue #538, fixed). An earlier revision of this file blamed the line count and
told you to seed inventory one product at a time. That was wrong: TUBC holds relay-created four-line
POs that registered cleanly (`PO0000093`, `PO0000094`), and one of them carries the very product set
recorded here as failing.

```
GP PROC   taPoLine
ERROR STATE 9191
DESCRIPTION Invalid PO Status (POLNESTA), the line item cannot be manually released
```

What actually happened: `create_po_line` called `taPoLine` with no `@I_vORD`, so eConnect resolved
each line by item number. Two lines sharing an `ITEMNMBR` updated each other instead of both landing
- the second silently overwrote the first with `err=0`, and a third raised 9191. Because
`gp_po.py` truncates the item number to GP's 30-character `ITEMNMBR` and hardware part numbers carry
their handing as a suffix, three codes differing only past character 30 collapse into one. The
registrations logged here as "3 lines, short clean codes" were sharing a truncated item number.

The relay now dictates `ORD = idx * 16384`, so this shape registers correctly and you can seed
inventory with a multi-line PO. If you see 9191 again, look at what the four lines truncate to at 30
characters before suspecting anything else.

**A USD-currency GP vendor fails registration with `taMCCurrencyValidate` error state 961.** Hit
2026-08-10 on pr-569 with BANNER SOLUTIONS (currency showed USD, tax detail disabled as
"Not applicable for a foreign-currency PO"): the push died in `taPoHdr` with
`An error occurred in the taMCCurrencyValidate proc` - TUBC has no exchange setup for a
foreign-currency PO. Pick a CAD vendor instead (ALLMAR INC. worked on the same PO seconds later).
The dialog's Currency field tells you before you submit.

**The register dialog's `Buyer (you)` field is the authority on your buyer identity, not the User
Management grid.** On pr-569 the grid's GP BUYER column showed `BCPurchasing` for the signed-in
account while the dialog submitted as `mira` - so the buyer-assignment fix (Admin -> Buyers) must
target the id the DIALOG shows, or the alert stays. Assign the dialog's id to the project and the
alert clears on reopen.

**Receiving is now draft-first with a required packing slip and a manager approval gate.** The
Receive wizard's location step is gone: select POs -> quantities -> ATTACH A PACKING SLIP (any
image/pdf; required, submit stays blocked without it) -> Submit for Approval. Nothing posts to GP or
lands in inventory until a Warehouse Manager approves it at `/app/warehouse/receive-approvals`
(Approve & Post to GP -> confirm). Approval posts the GP receipt and the units land UNLOCATED - they
appear on Put Away for aisle/row/bay assignment. Budget one extra hop when seeding: receive, approve,
then put away.

**A USD-currency GP vendor fails registration with `taMCCurrencyValidate` error state 961.** Hit
2026-08-10 on pr-569 with BANNER SOLUTIONS (currency showed USD, tax detail disabled as
"Not applicable for a foreign-currency PO"): the push died in `taPoHdr` with
`An error occurred in the taMCCurrencyValidate proc` - TUBC has no exchange setup for a
foreign-currency PO. Pick a CAD vendor instead (ALLMAR INC. worked on the same PO seconds later).
The dialog's Currency field tells you before you submit.

**The register dialog's `Buyer (you)` field is the authority on your buyer identity, not the User
Management grid.** On pr-569 the grid's GP BUYER column showed `BCPurchasing` for the signed-in
account while the dialog submitted as `mira` - so the buyer-assignment fix (Admin -> Buyers) must
target the id the DIALOG shows, or the alert stays. Assign the dialog's id to the project and the
alert clears on reopen.

**Receiving is now draft-first with a required packing slip and a manager approval gate.** The
Receive wizard's location step is gone: select POs -> quantities -> ATTACH A PACKING SLIP (any
image/pdf; required, submit stays blocked without it) -> Submit for Approval. Nothing posts to GP or
lands in inventory until a Warehouse Manager approves it at `/app/warehouse/receive-approvals`
(Approve & Post to GP -> confirm). Approval posts the GP receipt and the units land UNLOCATED - they
appear on Put Away for aisle/row/bay assignment. Budget one extra hop when seeding: receive, approve,
then put away.

Two other things worth knowing when GP is refusing outright:

- **There is no way to fake a placed PO, and that is deliberate (#509).** `markPoAsOrdered` used to
  flip a DRAFT straight to `GP_REGISTERED` with no relay involvement, and earlier revisions of this
  file advertised it as the way to exercise on-order quantities and back-order reads without GP. It
  is deleted. Its only guard was the local vendor link - never a GP vendor, just an invented one -
  and it had no frontend caller, so nothing reachable by clicking could ever produce that state. A
  seeding backdoor is not an end-to-end test; if a surface cannot be reached by clicking, the honest
  answer is that it needs a relay-connected run, not a fabricated row.

  `GP_REGISTERED` now comes only from `registerPoInGp` (relay push, real PM00200 vendor) or
  `create_po`'s GP-first branch for a caller already holding a GP result. So on a relay-less PR
  environment there are no placed POs at all, and POs Awaiting Receipt, back-order reads and
  receiving history are legitimately empty there.
- The stock pool is not an escape hatch either: there is no `createStockItem`. Stock only enters
  through a receive, or out of project inventory via `destockInventory`, so it has the same root
  dependency.

**A re-import wipes the classification of every item it does not re-classify.** `finalize_import_session`
re-persists the selected openings' hardware items with whatever the Classification step sent, so a
run whose step only lists the one item needing ordering (the assembly purpose does this) leaves the
rest with `classification = null`. Anything reading Site/Shop - the #451 coverage groups, the
shop-assembly filter - then sees them as unclassified. Re-run the PO purpose over the opening and
classify the whole grid to restore it.

### A stacked PR gets NO CI, and backend tests are the thing you lose

`.github/workflows/ci.yml` triggers on `push`/`pull_request` to **master only**. A PR based on
another feature branch - the shape a stack of dependent PRs takes - therefore runs no Frontend, no
Backend, no Migration Integrity and no Relay job at all. `gh pr checks` on it shows only the two
Railway deploys, both green, which reads exactly like a healthy PR.

That matters most for the backend, because there is no local Postgres: `pytest` skips ~470 of ~600
tests here, so CI is the only thing that ever runs them. A stacked backend change is effectively
unverified until it reaches master.

The cheap fix is a throwaway **draft PR from the top of the stack to master**, which runs the whole
stack's suite in one go; close it once green. Done on the #451 stack (PR #466) and it immediately
caught two failures that all three stacked PRs were reporting as clean:

- migration 083 creating its enum twice, because the column referenced a bare `postgresql.ENUM`,
  which emits its own `CREATE TYPE` during `create_table` on top of the explicit `.create()`. Fresh
  database -> `DuplicateObject` -> Migration Integrity dead AND every backend test dead, since they
  all build the schema. Pass `create_type=False` on the column's reference.
- a delivery-request fixture one field short after `DELIVERY_REQUEST_FIELDS` grew.

## Getting Started (Every Session)

0. **Pick the environment first.** Testing runs against the PR environment for the PR you are working on. Set `PR` once and let both URLs derive from it, so there is no production URL in the snippet to fat-finger:
   ```js
   const PR = 420;  // <- the PR number under test
   const BACKEND  = `https://backend-uc-nexus-pr-${PR}.up.railway.app`;
   const FRONTEND = `https://frontend-uc-nexus-pr-${PR}.up.railway.app`;
   ```
1. **Sign in**: open the **"test environment ready"** comment the preview-env workflow posts on your
   PR and navigate its sign-in link. It is `<BACKEND>/testing/session?key=<K>` and needs nothing from
   you - one navigation lands you on `/app`, signed in as the dedicated e2e account (Admin/Manager),
   with projects already present. The link mints a fresh Clerk ticket on every visit, so it never goes
   stale, survives a DevAction schema reset, and can be navigated again any time.
   ```js
   // straight from the comment - no token fetch, no secret to hold
   window.location.href = '<paste the session link from the PR comment>';
   ```
   - Clerk auto-authenticates — no email, password, or verification code needed.
   - **No comment yet?** The workflow posts it once the environment is green (a couple of minutes after
     a non-draft push). A red `preview-env` check means the environment did not come up - the comment
     it posts says which of backend/frontend/graphql failed, and [PR-ENVIRONMENT.md](PR-ENVIRONMENT.md)
     is the diagnosis.
   - The link is safe to reuse and safe to sit in a public comment: the e2e account it mints is
     **refused on production** (`app/auth._reject_e2e_account_in_production`), so it only ever opens
     this disposable preview.
2. **Reset data** (if needed): Click the "DevAction: drop and rebuild schema" button in the app bar.
   - Since #442 the button mints the Clerk session token off the auth bridge and sends it as an
     `Authorization: Bearer` header - `/admin/reset-data` sits behind `require_admin_request` (#422),
     so the signed-in account must hold **Admin/Manager**. With no session it alerts and skips the
     request instead of firing a doomed unauthenticated POST.
   - A MUI confirm dialog appears first — click "Drop & Rebuild" to confirm.
   - Then a `window.alert()` fires with "Schema dropped and rebuilt..." — use `handle_dialog` with `action: "accept"` to dismiss it.
   - Only then can you `take_snapshot` again (alerts block all MCP interaction).
3. **Post-login**: You land on `/app` — the Module Selector with 6 module cards.

### Human sign-in, and when the comment path is broken

`GET /testing/clerk-sign-in` is the human fallback and nothing else uses it any more. It mints a REAL
staff session for an arbitrary email, gated on an Admin/Manager bearer OR the shared secret in
`X-Testing-Secret`. Reach for it only when the comment's `/testing/session` link will not work - a red
`preview-env` check, or `E2E_CLERK_USER_ID` unset on the environment - because it is the same
impersonation-shaped endpoint #422 gated, not an agent convenience.

   ```js
   (async () => {
     const PR = 420;  // <- the PR number under test
     const SECRET = '...';  // <- preimage of that environment's TESTING_SIGN_IN_SECRET_HASH
     const resp = await fetch(`https://backend-uc-nexus-pr-${PR}.up.railway.app/testing/clerk-sign-in`,
       { headers: { 'X-Testing-Secret': SECRET } });
     const { token } = await resp.json();
     window.location.href = `https://frontend-uc-nexus-pr-${PR}.up.railway.app/?__clerk_ticket=${token}&cb=${Date.now()}`;
     return 'Navigating with sign-in token...';
   })()
   ```
   For the local fallback, use `http://localhost:8000` / `http://localhost:5173`. Do not substitute the
   production hosts here - see the Environment section.

**Don't know the inherited secret's preimage?** It lives only in the scratch of the session that minted
it, so a later session usually cannot recover it. Do not reset production's
`PREVIEW_TESTING_SIGN_IN_SECRET_HASH` for this - an existing environment copied the old digest at
creation and a production reset would not reach it anyway. Instead set a per-environment override,
which always wins: generate a pair (one-liner in `backend/.env.example`), then `railway variables
--set "TESTING_SIGN_IN_SECRET_HASH=<sha256>" --environment uc-nexus-pr-<N> --service backend`. The set
prints nothing on success - verify with a `--json` read - and it redeploys the backend (~2 min).
Verified on pr-575, 2026-08-10.

## Chrome DevTools MCP Patterns

### General Rules
- Always `take_snapshot` after any navigation or click before acting on the page.
- Prefer `fill_form` (batch) over individual `fill` calls — individual fills can bleed values into adjacent fields.
- **`fill` / `fill_form` APPEND to a MUI number input that already holds a value** (a spinbutton
  defaulted to `2` filled with `1` ends up `21`, over max, submit disabled). Seen on every default-
  quantity dialog 2026-08-10. Set such fields via `evaluate_script` with the native value setter +
  an `input` event instead, then re-read the value before submitting.
- **`div[role="dialog"]` selectors hit the WRONG dialog inside the Import wizard.** The fullscreen
  wizard is itself a `role="dialog"`, so when it opens an inner modal (Split line, Finalize confirm,
  over-order warning) `document.querySelector('div[role="dialog"] input...')` matches the wizard's
  FIRST matching input, not the modal's. On 2026-08-10 that silently wrote a split quantity into the
  first draft card's unit-cost spinbutton (persisted to the PO; caught only by re-reading the line
  later). Always scope to the LAST dialog in document order
  (`[...document.querySelectorAll('[role="dialog"]')].pop()`) and re-read the value you set before
  submitting.
- **The native-setter + `input` event trick can fail to reach React state** (the DOM shows the value,
  React re-renders it away - the split dialog's qty field did this while the button label still read
  "Move 1"). When it does, drive the field with real keystrokes instead: `click` it, `press_key
  Control+A`, then `press_key` the digits, and confirm on a state-derived readout (a button label,
  a total) rather than the input's DOM value.
- Use `take_screenshot` when you need to verify visual rendering (layout, colors, spacing).

### MUI Select Dropdowns
- MUI `<Select>` renders its dropdown in a **portal** (`<div role="presentation">`), not inside the Select element.
- After clicking a Select, call `take_snapshot` again to see the portal-mounted `<MenuItem>` elements.
- Click the desired `<MenuItem>` to select it.

### MUI Dialogs
- MUI `<Dialog>` also renders in a portal overlay.
- After triggering a dialog, `take_snapshot` to see dialog content.
- Confirm/cancel buttons may use `data-testid="confirm-dialog-confirm"` / `data-testid="confirm-dialog-cancel"`.

### MUI DataGrid
- DataGrid virtualizes rows — only visible rows appear in the DOM.
- Off-screen rows won't appear in snapshots; use `evaluate_script` to query grid data as fallback.
- Column headers are in `role="columnheader"` elements.
- Click a row's `gridcell` to trigger row click handlers (e.g., open detail modal).

### window.alert()
- Reset data and some actions trigger `window.alert()`.
- **These block all MCP interaction** — `take_snapshot` will hang until the alert is dismissed.
- Use `handle_dialog` with `action: "accept"` to dismiss.

---

## App Navigation Map

```
/                          -> Clerk Sign-In
/app                       -> Module Selector (6 module cards)
/app/import                -> Start a Request (project landing -> hardware schedule wizard). NOT in the
                              sidebar since #471 - reached from the "Start a Request" button in the Shop
                              Assembly and Shipping headers, which append ?purpose=assembly|shipping
                              (Shipping also passes ?projectId=, so its button opens the wizard directly).
                              In the PO module since #480 there is no separate Start a Request button:
                              "Create a PO" opens a chooser, and "From hardware schedule" navigates here
                              with ?purpose=po
/app/po                    -> Purchase Orders (project landing -> PO list)
/app/warehouse             -> Warehouse landing (stat cards + Go-to cards for sub-routes)
/app/warehouse/inventory   -> Inventory (hardware items by project)
/app/warehouse/locations   -> Locations (master-detail bin browser)
/app/warehouse/receiving   -> Receiving wizard
/app/warehouse/put-away    -> Put Away (unlocated items queue)
/app/warehouse/pull-requests -> Pull Requests
/app/warehouse/stock-pool  -> Stock Pool (non-project stock items)
/app/warehouse/deficient-items -> Deficient Items Review
/app/warehouse/shipments   -> Shipments (global packing slip list + return dialog)
/app/shop-assembly         -> Shop Assembly landing (stat cards + one Go-to card)
/app/shop-assembly/requests  -> Requests: accept / reject / reopen, with the stage each has reached
/app/shipping              -> Shipping Out (ship-ready items, packing slips)
/app/admin                 -> Admin (reports, vendors, projects, users, cleanup)
```

---

## The request lifecycle, end to end

The module guides below are organised by *screen*, which is the wrong shape for a first read: one
request's journey crosses three of them. This is that journey once, with the screen that owns each
step. Everything in it is exercisable against Railway.

**v1 does not manage doors.** The opening is a label - demand attribution before receiving, a text
tag on a line after it - and hardware exits the system when a pull completes. There is no assembled
unit, no bench tracking and no per-leaf anything downstream of the schedule, so "which doors can we
build / ship / are complete" is not a question this version answers.

| # | What happens | Where you do it | What changes underneath |
| --- | --- | --- | --- |
| 1 | **Compose** a request | Shop Assembly or Shipping -> Start a Request | The composer offers `owed - sent - claimed` per opening; you assign what is free to each line. A PENDING request, and the hardware is **reserved** on the spot (#342) |
| 2 | **Accept** it | Shop Assembly -> Requests, or Shipping -> Requests | A PENDING warehouse pull carrying one line per allocated request line. A pure human gate - nothing is re-checked, nothing is spent. Rejecting instead is what releases the claim |
| 3a | **Start the pick** | Warehouse -> Pull Requests -> Start pick | The pull is claimed and opened. **Nothing moves**, and there is no sufficiency gate - a pull with an empty shelf still opens (#367) |
| 3b | **Confirm the pick** | The pick page, `/pull-requests/:id/pick` | The picker dictates a quantity per location; confirming deducts *those rows* and consumes the claim, atomically. This is the only moment inventory moves |
| 4 | **Hand it over** | Warehouse -> Pull Requests -> Mark as Pulled | The pull completes. **This is a terminal exit** - for shop assembly the cart goes to the bench and the system stops looking; for shipping out the hardware joins the staged pool |
| 5 | **Ship** (shipping out only) | Shipping Out -> Staging / Ship | A packing slip against what the completed pull staged, then SCHEDULED -> PICKED_UP -> DELIVERED |
| - | **Undo the pull** while it is being picked | Warehouse -> Pull Requests -> Cancel Pull | Stock restocked to the rows it came off, request back to Pending with its claim re-created (#343). Refused on a completed pull - the hardware has been handed over |
| - | **See where every request is** | Shop Assembly -> Requests | The stage chip: Requested -> Accepted -> Pulling -> Done, with Rejected off the ladder |

Three things a fresh reader gets wrong every time:

- **Reserved is not deducted.** Between steps 1 and 3b the hardware is claimed but still on the shelf,
  so the Warehouse inventory number and the Start-a-Request availability number legitimately disagree.
- **Started is not picked either (#367).** A pull sits IN_PROGRESS from the moment somebody presses
  Start pick, which is *before* any stock has moved. `Status` alone can no longer tell you whether
  the hardware has left - the queue's **Phase** column and `pickedAt` are what answer that.
- **The composer does not re-offer what has gone out.** An opening whose hinges left on a completed
  pull reads zero next time, even though the schedule still says it needs them. That is the `sent`
  term working, not a bug. Two requests for one opening are both allowed; the second one is simply
  offered nothing.

---

## Module Guides

### Purchase Orders Module

**Entry**: `/app/po` -> Project landing page (select a project or "All Projects")

**PO List Page**:
- Header: back to projects button, title, **"Create PO" button** (opens manual PO creation dialog)
- **Stat cards** (display-only since PR #142): Total, Draft, Ordered, Vendor Confirmed, Partially Received, Closed, Cancelled. No longer clickable — they're a dashboard, not a filter.
- The Tabs row that used to sit below the cards was removed in PR #142. Status filtering now lives in the column filter row instead.
- **Expand all / Collapse all** buttons above the table — open or close every row currently visible under the active filters/sort
- Collapsible MUI Table: leftmost chevron column + PO/Request #, Status, Vendor, Order Date, Items
- **Sortable column headers** (PR #142): every header is a `TableSortLabel` button — click to sort asc, click again to flip to desc. Nulls (Drafts without orderedAt or vendor) always sort last regardless of direction.
- **Filter row** below headers (PR #142): PO# text search · Status multi-select chip dropdown · Vendor text search · Order Date from/to date inputs · Items numeric ≥ input. All filtering is client-side; the GraphQL query no longer takes a `status` variable.
- Chevron toggles an inline line-item mini-table (Product Code, Order As, Hardware Category, Ordered Qty, optional Received Qty, Unit Cost, Line Total)
- Clicking a data cell (not the chevron) opens the PO detail modal — same modal as before
- **Expand all** targets only the currently-visible (filtered + sorted) rows — not the raw fetch.
- The Status multi-select uses underlying enum values (DRAFT, PARTIALLY_RECEIVED, etc.) but displays formatted labels. When driving via JS, the option's a11y `value` attribute reflects the display label, but the actual MUI state holds the enum value — so test by observing filtered rows, not by reading the option's a11y value.

**Create PO Dialog** (manual PO creation, issue #256 - draft-first, NO relay needed):
- Title "Create PO Request (Draft)"; the Create PO button works with the relay offline
- Project selector (optional, all projects — buyer assignments only gate the register step)
- Preferred delivery date. There is NO vendor field (#509): GP owns vendors, and the GP one is picked
  at register time
- Shipping costs / Tariffs (optional), Notes
- Line items grid: Hardware Category, Product Code, Qty, Unit Cost, Order As (REQUIRED per line; no Classification column - the PM sets site/shop at import)
- "Add Item" button to add rows, delete button per row (minimum 1 item)
- Submit ("Create Draft") creates a DRAFT PO with auto-generated request number (PO-REQ-XXX); no GP push. Registering into GP is the separate "Register in GP" action on the draft (relay + buyer identity required there)

**PO Detail Modal**:
- Shows: status chip, PO number, vendor (the GP `vendorNameSnapshot`, blank on an unregistered
  draft), quote #, dates, "No Project" label if project-less
- Line items grid: product code, hardware category, Order As, classification, ordered/received qty, unit cost, line total
- "Openings on this PO" section (#302), between Line Items and Documents - one row per (opening, leaf)
  the PO's hardware was bought for: opening number, a `Leaf N` chip, the hardware ordered against it
  (`2x E90600IC 626`), and a `building / floor / location` caption on the right. See below for which
  POs have one at all.
- Documents section with upload capability
- Receiving history
- Actions: Edit (header fields + line item Order As/costs), Register in GP, Cancel PO. There is no
  "Mark as Ordered" button and there has not been one for some time - the mutation behind it was
  deleted outright in #509

**Only a wizard-created PO has an "Openings on this PO" section**, and its absence is not a bug. The
link is `HardwareItem.po_line_item_id`, which only the Import wizard's Create-Purchase-Orders path
stamps; a PO built in the Create PO dialog, a stock PO, or one seeded straight into GP has no hardware
schedule behind it, so `poOpenings` returns `[]` and the whole section (its rule included) renders
nothing rather than an empty heading. Check `{ poOpenings(poId: "...") { openingNumber leaf } }` before
concluding the resolver is broken.

To produce one cheaply - the whole run is a couple of minutes and touches nothing else:

1. Purchase Orders -> **Start a Request** -> project card -> **Use last uploaded schedule** -> Purpose **Create Purchase Orders** (already preselected by the button).
2. Select Openings: tick 2 openings via `document.querySelector('.MuiDataGrid-row[data-id="0501-EX"] input[type=checkbox]').click()`. Prefer openings whose Hand column shows a pair (`RHRA/LHR`) so the section has more than one leaf to show.
3. Reconciliation: **Deselect All**, then tick exactly one product row (`data-id` is `"<category>|<productCode>"`). That is what keeps the PO to one line and one manufacturer group.
4. Classification: click By UCH + Shop on each row (both counters must fill).
5. Purchase Orders: tick the single manufacturer card's checkbox. The card carries only a preferred date and notes - there is no vendor field to fill (#509).
6. Finalize -> Finish Import Session -> Finalize -> **View Purchase Orders**, then the `Open <PO-REQ-NNN> details` button.

The per-leaf quantities in the section sum to the line item's Ordered Qty - that is the cheapest
correctness check on the join (e.g. `1x` on 0442-EX leaf 1 plus `2x`/`1x` on 0501-EX leaves 1 and 2
against an ordered qty of 4).

**PO Lifecycle**:
```
DRAFT -> ORDERED -> VENDOR_CONFIRMED -> PARTIALLY_RECEIVED -> CLOSED
                                    \-> PARTIALLY_RECEIVED -> CLOSED
  \-> CANCELLED (from DRAFT, ORDERED, or VENDOR_CONFIRMED)
```
- **DRAFT -> GP_REGISTERED** happens only by registering the PO in GP (`registerPoInGp`, relay
  required), or via `create_po`'s GP-first branch for a caller already holding a GP result. Both
  carry a real PM00200 vendor. #509 deleted `markPoAsOrdered`, which used to fake this transition
  with no relay and no GP vendor
- **VENDOR_CONFIRMED** auto-triggers when ORDERED PO has both vendor quote number and vendor acknowledgement document; auto-reverts if either is removed
- **Receiving** a PO without a project will show error: "PO must be associated with a project before receiving"

**A cancelled PO disappears from the list entirely, and the CANCELLED stat card is always 0.**
`cancel_po` (`po_repository.py`) sets `status = CANCELLED` *and* `deleted_at` in the same write, while
`get_purchase_orders` filters `deleted_at IS NULL`. So the cancelled PO is gone from the grid, gone
from the TOTAL, and the CANCELLED card it should be counted in can never be non-zero. Observed live
2026-07-29 with a cancelled PO definitely present in the database.

Two consequences when testing:

- **A PO count that drops between two measurements is a cancel, not data loss.** This costs real time
  if you meet it cold - the PO simply vanishes with nothing in the audit log to say so (PO cancels are
  not audit-logged). `deleted_at` has exactly one writer in the whole backend, `cancel_po`, reachable
  only through the user-triggered `cancelPo` mutation, so a vanished PO always means somebody
  cancelled one.
- **Record PO ids, not just counts**, when you need a before/after. Aggregating by status tells you
  something changed but not which row, and you cannot query a soft-deleted PO back through GraphQL to
  find out afterwards.

**Generate PO Document** (issue #230): button on the PO detail modal action bar, shown for any non-cancelled PO. Opens a dialog that builds the finished supplier PO as a client-side PDF (`@react-pdf/renderer`), replacing the old hand-edit-GP's-doc workflow. No relay involved.
- Dialog fields pre-fill from the PO, its saved `PODocumentData`, and `poDocumentSettings`: vendor mailing address, buyer (from `buyerId`), currency (CAD `$` / USD `$US`), ship-to (warehouse dropdown | "Use project site" button | custom text - the resolved block is stored verbatim), shipping method, quote # (stored as `quotation_number`), required-by (defaults to `expectedDeliveryDate`), freight/misc/tax + tax label, and three conditional toggles (wood-door FSC, USA tariff, international customs).
- **Generate & preview** opens the PDF in a new tab (`window.open` blob). **Save to PO documents** persists `PODocumentData` + uploads the PDF as a `GENERATED_PO` document (appears in the Documents list, label "Generated PO", downloadable via presigned URL). Both first call `savePoDocumentData`, so re-opening the dialog pre-fills.
- Doc math: each line ext = ordered x unitCost; Subtotal = sum of ext; Order Total = Subtotal + Freight + Miscellaneous + Tax. The item column shows `hardwareCategory` (main line) + `orderAs` (Reference line). Boilerplate (tax numbers, mandatory bullets, signature, footer) always prints; the FSC / USA-tariff / customs blocks print only when their toggle is on.
- Company-wide boilerplate lives at the PO module's Document Settings page (`/app/po/document-settings`, "Document Settings" button in the PO list header - it moved out of Admin); the per-PO gaps are captured in this dialog.

### Import Module (Start a Request)

**Entry**: the **Start a Request** button in the PO, Shop Assembly or Shipping header (#471 - it has
no sidebar entry of its own). That lands on `/app/import`, a project picker; choosing a project opens
the wizard (full-screen dialog) with the originating module's purpose already selected on step 2. A
bare `/app/import` still works if typed, it just asks for the purpose like it always did.

**Wizard Steps**:
1. Upload File — drag/drop or browse for XML file from TITAN
2. Purpose — choose: Create Purchase Orders, Shop Assembly Request, or Shipping Out
3. Select Openings/Hardware — pick which openings and hardware items to include
4. Reconciliation — shows what's already been imported (for re-imports)
5. (Conditional) Classification, Purchase Orders, Shop Assembly, or Shipping PRs step
6. Finalize — review and submit

**Result**: Creates a project (or updates existing), openings, hardware items, and the selected output (POs, SAR, shipping PRs).

**You almost never need to upload the XML.** Step 1 offers two cards: "Upload new TITAN XML" and
**"Use last uploaded hardware schedule"**, the second captioned with what is already persisted
("1998 openings, 29126 hardware items"). It rebuilds the wizard's working set from
`projectHardwareSchedule` - the openings and hardware items already in the DB - so every later step
behaves identically without a multi-megabyte parse. Take it unless the thing under test *is* the
parser. "Choose Different Source" on the loaded panel gets you back to the two cards.

**Step count depends on the purpose**, and the stepper is the quickest way to tell which flow you are in:

| Purpose | Steps |
| --- | --- |
| Create Purchase Orders | Upload File -> Purpose -> Select Openings -> Reconciliation -> Classification -> Purchase Orders -> Finalize (7) |
| Pull Request for Shop Assembly | Upload File -> Purpose -> Select Openings -> Reconciliation -> Shop Assembly -> Finalize (6) |
| Pull Request for Shipping Out | Upload File -> Purpose -> Select Openings -> Reconciliation -> Shipping PRs -> Finalize (6) |

Since #492 the assembly flow has no Classification step: Site/Shop is read off the persisted
schedule (the values a PO request wrote). Items never classified are named in an info banner on the
Shop Assembly step and left out of the request.

**Reconciliation is a hard gate on the assembly flow, and it fires before the Shop Assembly step.**
With nothing in inventory it shows a red alert - `No items have In Inventory status. There is nothing
available to assemble.` - and **Next is disabled**, so the wizard stops at step 4. The per-combo detail
is in the table underneath (Hardware Category / Product Code / Qty Needed / Qty Available / Lifecycle
Breakdown, each short line chipped `Gap Remaining: N`), not in the alert text. Worth knowing because
the slice-4 shortfall alert everyone quotes (`<CATEGORY> <CODE>: need N, M available (R reserved by
other requests) - short S`) lives on the **Shop Assembly** step, which you cannot reach at all when
availability is zero across the board. To exercise *that* message you need stock on the shelf and a
competing reservation; a bare empty warehouse only ever gets you the Reconciliation gate.

The same step on the **shipping** flow is advisory, not a gate: `Items that are In Inventory or Built
onto Opening can be included in shipping pull requests. Items with zero availability are excluded. You
may proceed with partial quantities if needed.` Next stays enabled. The gate for shipping is one step
later - with nothing shippable, the Shipping PRs step shows `Nothing on the selected openings is in a
shippable state. Assembled leaves already on another shipping request are not listed.`, an added
"Shipping PR #1" card lists `Select items (0 selected):` with no rows, and Next is disabled.

**Creating a request RESERVES inventory (#342).** This is the single biggest behavioural change to
the wizard, and it changes what "it worked" looks like at every downstream step.

- The Shop Assembly and Shipping PRs steps both read `projectInventoryAvailability`, where
  `availableQuantity = onHandQuantity - deficientQuantity - reservedQuantity`. **Next is disabled**
  while the selection asks for more than that, and a red alert lists every short combo as
  `<CATEGORY> <CODE>: need N, M available (R reserved by other requests) - short S`.
- The Shop Assembly step now also renders a "Hardware this request would reserve" table (Needed /
  Available / Reserved elsewhere per product), and refuses to proceed at all when no item was
  classified as Shop Hardware.
- The Shipping PRs step shows "<n> available" under each **loose** line only. Assembled door leaves
  never show one and are never gated - their hardware left fungible inventory at assembly.
- Next is also disabled while the availability lookup is in flight or has failed. An unknown count is
  not treated as "fine", so a mocked/blocked GraphQL call reads as a blocked wizard, not a bug.
- Driving `finalizeImportSession` directly past the UI gate gets an `INSUFFICIENT_INVENTORY` error
  naming every short combo, and **nothing at all is created** - no request, no reservations, no
  openings. Useful for exercising the gate without walking the wizard.
- To make a shortfall on demand: create one request that claims most of a product, then start a
  second request for the same product through Start a Request. The second one is short *even though the shelf count is
  unchanged* - that is the reservation working, and `reserved by other requests` in the message is
  how to tell it from genuinely absent stock.
- Other creation-time refusals (all `VALIDATION_ERROR`): a request with zero openings; an opening
  with zero items; a shipping request with zero lines; a leaf already inside a live shop-assembly
  request; a leaf already on a live shipping-out request; a leaf claimed by the *other* request type.
- **Re-upload with `replaceSchedule: true`** is never blocked. Live PENDING requests are rewritten to
  the openings that survived (their reservations rebuilt from what is left), a request that loses
  everything is auto-REJECTED by "Hardware Schedule Import", accepted requests are left alone, and
  every live request gets an `integrityNote` that shows as an amber alert on the accept screen.

### Warehouse Module

**Two different "available" numbers, and they are supposed to differ (#342).** The Inventory view's
availability is `on-hand - deficient`: what is physically unspoken-for in the building. The Start a
Task wizard's is `on-hand - deficient - reservations`: what may still be *claimed*. A product can
read 10 available in the warehouse and 0 available in the wizard; that is not a bug, it means live
requests are holding it.

**Confirming a pick consumes its source request's reservation (#367 moved this off approve).** A pull
whose request reserved exactly what it needs still picks fine - the check excludes the request's own
claim (self-coverage). **Every claim has a request behind it** - no pull holds one directly, so a
pull whose source request was rejected after the accept simply competes with everyone else and
consumes nothing.


**Entry**: `/app/warehouse` -> Warehouse landing page with stat cards and "Go to" card buttons for: Inventory, Locations, Receiving, Put Away, Pull Requests, Stock Pool, Deficient Items, Shipments. (No longer "three tabs" - this has evolved to a full landing page.) Since PR #395 the Deficient Items card shows `deficientCount` (deficient units across project inventory + stock pool - the same rows the review page lists, amber edge when non-zero). The card count matching its destination page is the thing to assert.

**There is no Deliveries page any more (#416).** It was a read-only lens over active POs, and its "Upcoming Deliveries" accordion asked `expectedDeliveries` for the exact PO population `openPOs` already drew the Receiving page's awaiting-receipt table from - the same three statuses, not soft-deleted - so on one page it would have been the same list twice. Only the back-order grid survived the merge, as a **Back-Ordered Items** section of Receiving; the accordion's urgency chip moved onto the awaiting-receipt table's Expected Delivery column. `expectedDeliveries` is gone from the schema entirely (querying it errors `Cannot query field`), `backOrderedPoCount` (the count of active POs still owed anything, not a unit sum) now rides the **Receiving** card as "N POs back-ordered", and `/app/warehouse/deliveries` redirects to `/app/warehouse/receiving`. Anything in an older session note about a Deliveries card, its project landing, or its "All Projects" toggle (PR #397) describes a page that no longer exists.

**Inventory tab default**: Navigating directly to `/app/warehouse/inventory` defaults to "All Projects" view — shows the "Projects" back button, "All Projects" heading, and the Hardware Items grid immediately. There is no Opening Items tab any more: nothing assembled is tracked. The ProjectLandingPage is NOT shown on initial load. Clicking "Projects" brings up the ProjectLandingPage where you can filter to a specific project or click "All Projects" to return to the all-projects view.

**Receiving** (wizard):
1. Select POs to receive (shows ORDERED/VENDOR_CONFIRMED/PARTIALLY_RECEIVED POs)
2. Enter quantities received per line item — line items grid shows: Product Code, Ordered As, Hardware Category, Ordered Qty, Already Received, Pending, Receive Now
3. Assign storage locations (aisle/bay/bin)
- Receiving auto-transitions PO status (ORDERED -> PARTIALLY_RECEIVED -> CLOSED)

**Receive/History toggle since #447** (PR #450): the page header carries a two-button toggle. The
Receive side is everything below; the History side is the Receiving History view - every PO that
reached GP including CLOSED ones, one row per PO (PO #, vendor, project, status chip, "N of M"
received, receive count, last received), text search + project filter, chevron-expandable. A row's
receives load lazily on first expand via the existing `poReceivingDetails` query and show each
receive's GP receipt number, batch, timestamp, receiver and line quantities. Receipt numbers also
show in the receive success dialog ("GP Receipt ...") and as a GP RECEIPT column in Recent Activity.
Receives predating #447 render a dash. TUBC mints receipt numbers prefixed `RC` (e.g. RC0000054),
not the `RCT` prefix the UC Connects docs describe - assert on the number GP actually returned, not
on the prefix.

Three sections since #416, in this order: **POs Awaiting Receipt**, **Back-Ordered Items**, **Recent
Activity**. The back-order grid is line-level and cross-project (no project landing step), carries a
Project column that reads "Stock PO" for a project-less PO, and chips how late or soon each line is
(`3d overdue` / `Today` / `Tomorrow` / `In 5d`, nothing beyond a week or with no date). The same chip
sits on the awaiting-receipt table's Expected Delivery column.

A successful receive now refetches this page's own three reads, so a line the receipt closed leaves
the back-order grid without a manual reload; a queued receipt that drains later evicts
`backOrderedItems` for the same reason. Before #416 a receive only refetched the inventory summaries.

**A PR environment cannot populate either grid, and production is not the answer.** Both grids want
POs at GP_REGISTERED or later, and `registerPoInGp` is relay-gated, so a fresh PR database shows "No
purchase orders awaiting receipt" and "Nothing is back-ordered" no matter what you do. Reaching for
production instead is the exact move the Environment section forbids.

Stub the GraphQL reads instead: from an `initScript`, intercept `window.fetch`, match the operation
name in the request body (`GetOpenPOs` / `GetBackOrderedItems`) and return rows built from `new
Date()` offsets. That drives the real components, which is enough to assert the column set, the
"Stock PO" and em-dash fallbacks, and every urgency band in one pass.

Be honest about what that does and does not cover. It proves the rendering. It does NOT exercise the
receive itself, so the refetch wiring above - the thing that makes a filled line leave the grid
without a reload - stays unverified at runtime until somebody receives against a real GP-registered
PO. Say so rather than calling a stubbed pass end-to-end.

**Build the stub's dates from local components, not `toISOString()`.** `toISOString` is UTC, so
after ~20:00 Eastern it names tomorrow, and the chip you assert against is then off by a day for a
reason that has nothing to do with the code under test. This is the same trap as #238 itself.

**Inventory**: Browse by hardware category and product code, see storage locations.

**Pull Requests**: Queue of pull requests from shop assembly or shipping modules. Two tabs (Shop
Assembly / Shipping Out); clicking a row opens the detail modal. Since #367 the old Staging column is
a **Phase** column - a tag over a line of detail, because `Status` stopped being enough once picking
became its own phase:

| Phase | Detail line | Means |
| --- | --- | --- |
| `Pending` | Not started | Nobody has pressed Start pick |
| `Picking` | Nothing off the shelf yet | IN_PROGRESS, `pickedAt` null, no pick lines |
| `Short` | Part-picked - remainder outstanding | A short confirm landed; some stock is gone, the rest is owed |
| `Staging` | `4 of 8 staged` | Picked, now building carts |
| `Picked` | Ready to hand over | Picked. Marking it pulled completes it, which is where v1 stops following the hardware |
| `Completed` / `Cancelled` | - | Terminal |

An IN_PROGRESS row reading `PICKED` in Phase is the normal, correct state for a shipping-out or
replacement pull - Status and Phase disagreeing is the point of the column.

#### The pick (#367) - where inventory actually moves

Approve is gone. There is no `Approve and Start` button anywhere, and no Available Qty / Status
columns in the detail modal's Loose Items table (they forecast whether an approve would succeed, and
approving no longer moves anything).

**Driving it end to end**, verified live on Railway 2026-07-28:

1. Open a PENDING pull -> **`Start pick`**. This routes straight to
   `/app/warehouse/pull-requests/<id>/pick`; there is no toast and no confirm, because starting is
   the first step of a job rather than a decision. The pull goes IN_PROGRESS and **nothing is
   deducted** - verify with `inventoryItems` before and after.
2. The page: `PICK SHEET` eyebrow, mono PR number, phase tag, project and requester; gauges for
   `PRODUCT CODES / REQUIRED / ENTERED / REMAINING`; then one section per product code.
3. Each section lists **every leaf in full** (`OWED TO 1 LEAF`, `015.2 · L1 × 1`) and a ledger of
   every candidate location: `LOCATION | RECEIVED | AVAILABLE | PULLED`. There is deliberately **no
   suggested column and no autofill** - assert their absence, it is the whole point of the slice.
4. Number inputs carry `aria-label="Pulled from <bin>"` and a `max` of that row's available, which is
   what makes them addressable from the MCP tools.

**What to assert, and the traps:**

- **Deficient units are withheld.** A row with `quantity 4, deficient 1` shows Available **3**.
- **Over-entry** on a row shows `Only N here` under the input, a page-level red alert, and disables
  Confirm. Over the pull's own requirement shows `... more than this request asked for`.
- **`Save draft` then reload**: entries come back. Zeros are *not* stored, so a box you set to `0`
  returns empty - that is correct, not a lost draft.
- **The confirm button changes name**: `Confirm pick` when balanced, `Confirm short pick` when
  something is entered but not everything, disabled when any ceiling is crossed.
- **On success the page navigates back to the queue**, so a toast assertion there is racy - assert
  on the inventory rows and `pickedAt` instead.
- Once picked, the page renders read-only: inputs disabled, `Save draft` and `Confirm pick` gone,
  and a banner naming who picked it and when. `Print pick sheet` still works.

**The against-FIFO test - the one that proves the feature.** Find a product code sitting in two bins
(`inventoryItems(projectId, category, productCode)` returns `receivedAt` per row), note which is
oldest, then deliberately pick from the **newer** one. Old behaviour would have drained the oldest.
Verified live: A-1-1 (oldest, received 03:51) untouched at qty 1, A-1-3 (received 04:07) 4 -> 3, and
the `PULL_DEDUCTION` audit row carrying `aisle/row/bay`, `warehouseCode` and `oldQuantity/newQuantity`
- the record the old FIFO deduction never kept.

**Short pick**: enter less than required and Confirm. The pull stays IN_PROGRESS with `pickedAt`
null, the queue phase reads `Short`, purchasing gets one `INVENTORY_SHORTFALL` notification (deduped
per pull, so a second short confirm does not raise another), and the remainder is keyed in later.
Since PR #401 that notification speaks the pick frame - `<CATEGORY> <CODE>: N of M picked - S still
owed (A free in the project now)` - matching the pick page's own alert. The old gate-frame wording
(`need N, M available (short S)`) still belongs to the *creation-gate* and sent-short messages;
seeing it on a short pick is a regression.
An empty submission is refused *while stock is available* but **allowed when there is none** - that
is the "walked the racks, found nothing" case and it confirms short of everything.

**Fetch list**: a shipping-out pull's OPENING_ITEM lines are *fetched*, not picked - check-offs with
no quantity, persisted per leaf, editable for the whole IN_PROGRESS life of the pull (they outlive
the pick confirmation, because a pure fetch pull is confirmable before a single leaf is ticked).

**The printed sheet** (`Print pick sheet`) opens a blob URL in a new tab: per-code sections, full
leaf lists, every location with Received/Available, **blank write-in boxes**, and a
`Picked by / Date / Keyed into Nexus by` signature footer.

**Per-leaf staging (#343, relaid out as sections in #367)** is the shop-assembly pull's execution
view, inside the detail modal between the header and the Items table, headed
`Stage carts (N of M leaves)`. **It only appears once the pick is confirmed** - before that there is
nothing on a cart to declare.

- One bordered **section per door leaf**, not a table row: header is the mono leaf identity
  (`015.2 · L1`) plus building/floor, with the hardware beneath as ledger rows
  (category | mono product code | right-aligned qty). The old single-cell bulleted list is gone.
- The section carries a 3px left edge: amber when selected, green once staged, hairline otherwise.
- Confirming is **two-step**: tick the checkboxes (`Stage <opening> · LN` - note the new identity
  format), press `Confirm N staged`, then confirm the dialog. A tick alone writes nothing.
  `Select all remaining` ticks every un-staged section.
- Each confirmed leaf is **immediately** assignable/workable in Shop Assembly, while the rest of
  the pull is still un-staged. This is the thing to exercise: stage one leaf of a pair, then go to
  `/app/shop-assembly/assemble` and claim it while its sibling still shows as waiting.
- An already-staged section has a disabled checkbox and a green "Staged" tag with who staged it and when.
- Staging the **last** leaf completes the pull (toast: "All carts staged - <PR> is complete.").
  The panel then renders read-only, so the record of who staged what survives.
- `Mark as Pulled` still exists and now means "stage everything remaining and finish"; its confirm
  dialog says so.
- Nothing moves in inventory at staging. Stock was deducted when the **pick was confirmed**, and
  `stage_pull_openings` refuses outright until it has been.

**Cancel Pull (#343)**: an outlined red button in the modal's action bar on any IN_PROGRESS pull, and
on a COMPLETED *shop-assembly* pull (there "completed" only means every cart is built). Absent on a
PENDING pull - reopen or reject the source request instead - and on a completed shipping-out pull.

- It opens its own modal (not the standard ConfirmDialog) with a warning alert, an optional Reason
  textarea, `Keep pull` and `Cancel pull and restock`.
- Success toast names the units returned and whether the claim was re-created. If the returned
  hardware could **not** be re-reserved you get a *warning* toast carrying the request's new
  `integrityNote` instead - that is a real state, not a failure.
- **Refusal keeps the dialog open** and renders the server's message in a red alert
  (`data-testid="cancel-blocked"`).
- **Only a pull being picked can be cancelled.** A completed one has handed its hardware over - to
  the bench or to a shipping desk - and v1 does not follow it past that point, so there is nothing
  left to reverse. The button is absent on a completed row.
- After a cancel: stock is back in project inventory on the rows it came off, and the source request
  is back in the Shop Assembly / Shipping accept queue as Pending with its claim re-created.
  Re-accepting it mints a **new** pull with the **same request number** - so a search by number can
  legitimately return a cancelled row and a live one.

**Stock Pool** (`/app/warehouse/stock-pool`): Shows stock items not tied to a project. Has a "Warehouse" filter dropdown in the filter row with options "All warehouses", "Warden (WRD)", "VP (VP)". Grid has a "Warehouse" column (visible when data rows exist). Empty state shows "Nothing in the stock pool yet" message.

**Transfer dialog** (PR #159 / PR #160, issue #88): Accessible from two places:
- Stock Pool grid row: "Transfer (same or other warehouse)" icon button (swap-horizontal arrows) in the Actions column.
- Locations tab right-side panel: click a bin row to open the panel, then click "Item actions" on a Stock Pool or Hardware Items row → "Transfer" menu item.

Both entry points open a "Transfer <productCode>" MUI dialog with: an "X available to transfer." line, a "Destination warehouse" dropdown (defaults to the source item's warehouse), Aisle/Bay/Bin MUI Autocomplete fields (suggest existing bin values; are comboboxes with autocomplete="list", NOT plain text boxes), and a Quantity spinbutton defaulting to the available quantity (max=available). Transfer button stays disabled until all three location fields are filled. On success, the dialog closes, the grid refreshes automatically (source row qty drops, a new row appears at the destination bin if it didn't exist), and a success toast fires briefly. To open autocomplete suggestions: focus the input then dispatch a keydown ArrowDown event.

**Receiving warehouse selector** (PR #158): When receiving a PO, the Receive modal includes a "Receive into warehouse" dropdown near the top, defaulting to "Warden (WRD) · default". Only visible when a PO is in ORDERED/VENDOR_CONFIRMED/PARTIALLY_RECEIVED state and you open the receive flow.

**Put Away** (`/app/warehouse/put-away`): Lists unlocated project inventory items grouped by hardware category. Each row shows Product Code, Qty, PO#, Received date, and Aisle/Bay/Bin comboboxes + an "Assign" button (disabled until all three location fields filled). Has a "Filter by Project" dropdown. Items returned to project inventory via the Return dialog appear here immediately.

**Shipments page** (`/app/warehouse/shipments`, issue #89):
- Global list of all shipped packing slips (across projects). Reachable from: direct URL, Warehouse landing "Shipments" card, sidebar nav under Warehouse.
- Grid columns: Packing slip #, Project, Shipped by, Shipped date, Loose units, Actions column with "Return" button.
- Filter controls: "Search packing slip #" text input (filters by packing slip number), "Project" dropdown.
- "Loose units" column shows total loose-line qty originally shipped (does NOT decrease as returns are recorded).
- "Return" button opens the Return dialog for that packing slip.

**Return dialog** (issue #89):
- Title: "Return shipment <PS-NUMBER>"
- Subtitle: "<Project name> · loose hardware only. Opening items are not returned."
- "Destination warehouse" required select (defaults to "Warden (WRD)").
- "Reference / note (optional)" text field.
- "Cancel whole shipment" button (separate cancellation action, distinct from return).
- One section per loose line, each showing: product code (heading), hardware category + opening reference (e.g. "HINGE · opening 101"), a "returnable N" chip showing remaining returnable quantity, Qty spinbutton (min=0, max=returnable remaining), Disposition select (options: "Return to project inventory", "Move to non-stock", "Defective / RMA"), Reason (optional) text field.
- When "Defective / RMA" is selected as Disposition, a "PO / RMA reference (optional)" text field appears between the Disposition select and the Reason field.
- "Cancel" and "Record return" buttons at the bottom.
- On success: dialog closes, toast fires "Return recorded for <PS-NUMBER>".
- Validation: if any Qty exceeds its returnable max, clicking "Record return" shows an inline error alert at the top of the dialog: "<PRODUCT-CODE>: cannot return more than N". Dialog stays open, nothing is submitted.
- After a return is recorded, the returnable chip amounts decrease correctly on the next dialog open. The packing slip row remains in the grid.

**Return disposition outcomes**:
- "Return to project inventory": creates an `InventoryLocation` record for the project with no bin assigned (unlocated). Item appears in Put Away tab and in Inventory under the project. Does NOT appear in Stock Pool.
- "Move to non-stock": creates a `StockItem` with quantity=N, deficientQuantity=0. Appears in Stock Pool.
- "Defective / RMA": creates a `StockItem` with quantity=N, deficientQuantity=N (fully deficient, available=0). Appears in Stock Pool AND in Deficient Items Review page.

**GraphQL queries for verifying returns**:
- `{ stockItems(productCodeContains:"RET-") { productCode quantity deficientQuantity available } }` - checks stock pool entries
- `{ deficientItems { source productCode hardwareCategory deficientQuantity } }` - checks deficient items (DeficientItemRow type, no quantity/available fields)
- `{ unlocatedInventory(projectId:"<UUID>") { inventoryLocation { hardwareCategory productCode quantity aisle row bay bin } } }` - returns InventoryItemDetail (not InventoryLocation directly). Use nested `inventoryLocation` field for product/qty data.

### Shop Assembly Module

**Entry**: `/app/shop-assembly` -> landing page: "Active Pull Requests" and "Awaiting Review" stat
cards, a **Start a Request** button, and one "Go to" card for Requests.

The module is two screens in v1. Composing happens in the import wizard (the button deep-links to
`?purpose=assembly`), and everything after the pull completes is untracked - the bench is outside the
system.

**Requests page**, `/app/shop-assembly/requests`. A Pending / Accepted / Rejected toggle:

- **Pending** is the queue: Accept mints the warehouse pull, Reject releases the claim.
- **Accepted** shows every accepted request with its **stage chip** (Accepted / Pulling / Done) and a
  count per rung above the list - this is where the old Pipeline page went. Reopen is offered on
  every row but **disabled with the reason beside it** once the warehouse has started the pull; that
  is deliberate, because hiding it reads as a missing feature rather than a closed window.
- **Rejected** is history.

Expanding a row shows its lines **grouped by opening tag**, with Owed and Allocated per line and a
`N short` chip where they differ. Grouping is display only - the lines are flat underneath, and a
line raised straight off inventory carries no opening at all and sorts last under "No opening".

**Accept is a pure human gate since #342.** There is no inventory check on Accept and no shortfall
can surface there - the hardware was reserved when the request was created. Accepting neither spends
nor releases that claim; confirming the pick spends it; **rejecting** is the only thing that releases
it.

**The short count is on the summary line, not buried in the tables.** Approving a request that is
knowingly short is fine; approving one without knowing it is short is not.

**The Shop Assembly Manager role gates nothing in v1.** It stays defined in Clerk (its only consumer
was the assignment roster), so a user holding it sees exactly what anybody else does.

### Shipping Module

**Entry**: `/app/shipping` -> Project landing page -> ship-ready items browser

- Shows opening items and loose items ready to ship
- Create packing slips, confirm shipments

**The confirm step is the Delivery Request form since #447** (PR #450). Confirming a cart opens a
sectioned dialog (Shipment / Shipper / Pickup location / Deliver To questionnaire / Contacts), not
the old slip-number-only form. Shipper name is read-only from the signed-in identity and the email
prefills from it; pickup location prefills from the primary warehouse and is name-only when the
seeded warehouse has no address fields. Everything except the slip number is optional. The success
view's "View Delivery Request" opens the generated PDF (client-side react-pdf), which replicates the
paper Delivery Request form; a shipment's document is reprintable later from the shipments list and
regenerates from the STORED fields, so an edit shows up on the next print.

**Shipments carry a lifecycle since #447**: SCHEDULED -> PICKED_UP -> DELIVERED, strict one-way; the
states document the truck's journey only and move no inventory. The Shipments page
(`/app/warehouse/shipments`) is expandable rows now, not a DataGrid: row = slip #, project, status
chip, shipped by, created, pick-up, delivery, carrier; expansion = the item lines plus the actions,
each status-gated - Delivery Request (always), Edit (SCHEDULED only, full-replace semantics, a
cleared field really clears), Mark Picked Up (SCHEDULED), Mark Delivered (PICKED_UP), Return
(unchanged). Lifecycle/edit mutations return the whole header, so the row updates through the Apollo
cache with no reload - assert on the row, do not wait for a refetch.

**Hardware only reaches the staged pool when its SHIPPING_OUT pull is COMPLETED.** Confirming the
pick leaves the pull IN_PROGRESS with phase "Picked - ready to hand over" and the Ship tab stays
empty; "Mark as Pulled" in the pull detail modal is what completes it. Budget for that extra step
when scripting the chain.

**The shipping wizard composes off the same query shop assembly does.** On the Shipping Out step you
get one row per (opening, product) with Still owed / Already sent / On order and a Send box clamped
to what is genuinely free. Shop Hardware is filtered out - it goes to the bench, not on a truck -
and unclassified lines DO appear here, because hardware nobody classified goes to site by default
rather than being silently dropped.

- There is no per-leaf selection and no "ship it short" confirmation any more. Sending short is the
  ordinary case: assign less than the suggestion, or untick the line.
- **Re-run auto-assign** rebuilds the allocation from current availability. It is also what a
  race refusal triggers, with a banner saying availability moved.

### Admin Module

**Entry**: `/app/admin` -> Admin landing: stat cards (Users, Hardware Items, Openings) + "Go to" cards for each sub-route.

**Sub-routes**:
- Project Purchasing Progress (`/app/admin/project-purchasing-progress`)
- Hardware Status by Project (`/app/admin/hardware-status`) - loads nothing until at least one
  project is picked; the Projects Autocomplete is multi-select and quantities SUM across the
  selection (one row per (category, product code), not per project). Columns: Required /
  Not Purchased / PO Drafted / On Order / Received / On Hand / Sent to Shop / Staged / Shipped Out,
  each with an info-tooltip header stating its exact rule. "Sent to Shop" is a lifecycle EXIT
  (completed shop pulls - shop assembly is outside the Nexus pipeline), and "Staged" is completed
  shipping pulls not yet on a packing slip. Zero counts render dimmed. A "Filter products…" box
  appears once a project is selected and matches product code or category.
- Warehouses (`/app/admin/warehouses`) — warehouse CRUD (PR #158, issue #88); see below
- Projects (`/app/admin/projects`) — edit project details + OSSA flag (see below)
- User Management (`/app/admin/users`) — assign Clerk roles
- Location Cleanup (`/app/admin/location-cleanup`)
- (PO Document Settings moved to the PO module: `/app/po/document-settings`; see below. Unknown `/app/admin/*` sub-routes silently render the Admin landing, not a 404.)

Inventory quantity corrections are NOT here — they live in the Warehouse module (Locations tab).

**Warehouses page** (`/app/admin/warehouses`, PR #158, issue #88):
- DataGrid columns: Name, Code, Location (city + province concatenated), Primary (chip "Primary" / blank), Status (chip "Active" / "Inactive"), trash icon.
- Primary warehouse (Warden/WRD) has NO trash icon — delete is blocked on primary.
- Non-primary warehouses have a trash icon that opens a confirm dialog: "Delete [name]? This is blocked if any inventory still references it."
- Create dialog: Name (required), Code (required), Address, City, Province, Postal Code, Primary checkbox, Active checkbox (checked by default). Save toast = "Warehouse created".
- Edit dialog: same fields pre-populated, Save toast = "Warehouse updated".
- Delete confirm toast = "Warehouse deleted".
- Seeds: Warden (WRD, Primary, Active) and VP (VP, Active) are seeded by default.

**Projects page** (`/app/admin/projects`, issue #67):
- Admin/Manager only. Non-admins get a permission Alert; the backend also enforces it (see Lessons Learned).
- DataGrid columns: Project #, Description, Client, Job Site, OSSA (chip "Yes" / "—"), Openings. Click a row to open the edit dialog.
- **Edit dialog**: OSSA toggle + editable text fields (description, client, job site name, address/city/state/zip, general contractor, GC contact name/phone/email, project manager, application). A read-only "From TITAN" section shows project number, submittal job no, submittal assignment count, estimator code, TITAN user ID — these are immutable.
- Save calls `updateProject`, refetches the grid, and shows a "Project updated" toast.

**PO Document Settings page** (`/app/po/document-settings`, issue #230 - lives in the PO module, reached via the "Document Settings" button on the PO list header):
- Admin/Manager only (non-admins get a permission Alert; the mutation is `require_admin`-gated). Single-record form, not a grid.
- Fields: company from-address, payment terms, confirm-with, tax numbers, mandatory bullets (one per line), wood-door FSC note, USA tariff note + effective-until date, customs broker block, shipping accounts (one per line), signature note, footer notes.
- Backed by `poDocumentSettings` (get-or-creates a single row seeded from the guideline doc on first read, so it never returns null) and `updatePoDocumentSettings`. Save toast = "PO document settings saved". These values print on every generated PO document.

---

## Lessons Learned

- `fill_form` is much more reliable than sequential `fill` calls for forms with many fields.
- After "DevAction: drop and rebuild schema", there are TWO dialogs: a MUI confirm dialog, then a `window.alert()`. Must handle both.
- Clerk sign-in tokens: Fetch from `GET /testing/clerk-sign-in` on the backend, then navigate to the frontend with `?__clerk_ticket=TOKEN`. The runtime is the PR environment for the PR under test (issue #182 moved e2e onto Railway; production is not a testing target). Clerk auto-authenticates - no form fill, no verification code. Tokens are one-time use; fetch a fresh one each session.
- When viewing "All Projects", `projectId` is undefined/null in queries — this returns all POs across projects.
- To test the Warehouse Receiving wizard's "Enter Quantities" step, you need at least one PO in ORDERED (or higher) status. DRAFT POs do not appear in the receiving wizard's PO selection list.
- The line item field formerly called "Vendor Alias" is now called "Order As" in pre-order screens (Create PO dialog, PO detail modal) and "Ordered As" in post-order screens (Warehouse receiving wizard).
- On the Import wizard Select Openings/Hardware step with a large XML file (1998 openings), `take_snapshot` produces an output file that exceeds the tool token limit. Use `evaluate_script` with `document.body.innerText` or targeted DOM queries to check state and click buttons. Use `evaluate_script` to click "Select All" when the snapshot uid approach times out due to large DOM.
- Import wizard Classification step columns: Opening #, Product Code, Hardware Category, Manufacturer, List Price, Discount, Unit Cost, Qty, Classification, Site/Shop. Each row has four toggle buttons - "By UCH" / "By Others" in Classification, and "Site" / "Shop" in Site/Shop. Also has "Add group level" button and a header checkbox to select all rows. There are **two** counters ("X of Y items classified" and "X of Y in-scope items site/shop classified") and Next stays disabled until both are satisfied, so ticking only By UCH leaves the step blocked.
- Import wizard step order for "Create Purchase Orders" purpose: Upload File -> Purpose -> Select Openings/Hardware -> Reconciliation -> Classification -> Purchase Orders -> Finalize (7 steps total).
- For a first-time import (new project, no existing data), the Reconciliation step has no data to display — it just shows "New project — all items will be ordered fresh." The step is effectively a pass-through; do NOT use `wait_for` to wait for reconciliation data. Just click Next immediately.
- Classification step grouping: Clicking "Add group level" creates a Level 1 dropdown pre-set to "Hardware Category" with a remove (X) button. Shows accordion rows per group with item counts, "By UCH All" and "By Others All" bulk buttons on the right, and a collapse/expand chevron. Each group shows a chip: "0/N classified" (grey, unclassified), "All By Others" (orange/amber), or "All By UCH" (green). With 26548 items the snapshot is too large — use evaluate_script to find and click buttons. Classification counter turns green when all items are classified.
- Purchase Orders step (step 6 of 7): Shows N manufacturer group(s) each as an expandable card with checkbox, Preferred delivery date, Notes, PO Total, and a line items grid showing Product Code, Hardware Category, Total Qty, Unit Cost, Total Cost, Order As columns. Since #509 there is no vendor field on the card - the group is a TITAN manufacturer, and the GP vendor is picked at register time. Groups default unchecked. Only By UCH items appear (By Others items are excluded). With the contracterp-74.xml file, 41 groups appear.
- Purchase Orders step: The Next button is DISABLED until at least one vendor checkbox is checked. All vendors start unchecked by default. To check all 41 vendors programmatically: use evaluate_script to call `.click()` on each `.MuiCheckbox-root` span inside each `.MuiPaper-outlined.MuiPaper-rounded` card (skip index 0 which may be a header). This triggers React's event handlers properly (direct DOM checkbox manipulation does NOT update React state).
- "By Others" classification in the ALD group correctly EXCLUDES those items from vendor PO cards. Items that appear under vendor "Aluminum Door By Others" (vendor name, not classification) with ALD hardware category are separate — they are items from that vendor that were classified as "By UCH". The vendor name and the hardware category name can both contain "ALD" but refer to different things.
- Finalize step (step 7 of 7): Shows "Review & Finalize" with Import Summary (project name, opening count, hardware item count, PO count). "Finish Import Session" button opens a "Finalize Import" MUI dialog with Cancel and Finalize buttons. After clicking Finalize, shows "Finalizing import session..." progress text, then a success overlay dialog with "Import session completed successfully!", project name, POs created count, and "View Purchase Orders" / "View Warehouse" / "Return to Home" buttons.
- PO list expanded mini-table shows the optional "Received Qty" column only when `po.receiveRecords.length > 0`. POs whose line items have `receivedQuantity > 0` but `receiveRecords` is empty (e.g. GP-generated POs with status PARTIALLY_RECEIVED but no ReceiveRecord rows) will NOT show Received Qty — this is intentional and mirrors `PODetailModal`'s behavior.
- The "All Projects" PO list query (`GET_PURCHASE_ORDERS` with no projectId) is the canonical example of the slow-resolver pattern described in CLAUDE.md rule #6. It eagerly loads every line item, receive record, and document for every PO across all projects. With ~19 POs in test the p90 hit 60s and p99 was ~4min (`http_response_time`). Backend CPU/memory are idle during this — it's a DB-bound issue. A project-scoped view (`projectId` set) returns much faster. If testing All Projects times out, retry with a specific project.
- Locations page redesign (PR #160, issue #88): The `/app/warehouse/locations` page uses a master-detail rail+panel layout. Unselected state: DataGrid shows 4 columns - Location, Warehouse (chip per row), Items, Total Qty. No separate Aisle/Bay/Bin columns. Selected state (row clicked): left DataGrid collapses to a single "Location" column rail (shows location name + warehouse code chip + qty in one compact cell per row), and a right-side panel fills the remaining width showing the bin's contents, a WRD/VP chip in the panel header, and recent activity. Close button in panel returns to unselected state.
- Locations page warehouse filter: A "Warehouse" combobox dropdown sits next to the Search locations input. Options: "All warehouses" (default), "Warden (WRD)", "VP (VP)". When a specific warehouse is selected, the "Warehouse" column disappears from the table (redundant), only that warehouse's bins show, and the count summary updates. In local testing, plain `click` on the combobox uid works fine — it opens the MUI Select portal and the options are visible in the next snapshot. (The "requires mousedown + mouseup via evaluate_script" note may have been a Railway-only issue.)
- Locations page horizontal scroll: body has `overflow-x: hidden` applied. No hard min-widths on the layout. `document.documentElement.scrollWidth === clientWidth` with panel open or closed.
- After a deploy on Railway, the previously-loaded SPA tab keeps the OLD `index.html` reference until full page reload (`navigate_page type=reload` is NOT enough). Bust by either closing the tab and `new_page` to the URL, or adding a query-param cache-buster like `?cb=1`. The HTML headers (`Cache-Control: no-cache, must-revalidate`) cover the *next* page load but not the currently-cached document.
- MUI `Autocomplete` with `freeSolo` (used by `LocationAutocomplete` and `OrderAsAutocomplete`) is flaky to drive via `fill` — the tool tries to find a matching dropdown option and errors with "Could not find option with text X" when the value is a brand-new free-form string. Worse, when fill fails on a follow-up Autocomplete it sometimes mutates the previous field. For tests that need to set a specific value, use `evaluate_script` to set the underlying input's `value` and dispatch a synthetic `input` event, or drive the mutation directly via `curl` to the `/graphql` endpoint (the location-string normalization can be verified that way without UI flake).
- Mutation success in the new LocationsTab triggers `refetchContents()` + parent `refetch()`, but Apollo Client's normalized cache can leave the just-mutated `InventoryLocation` entity visible in the panel until the cache settles. The DB is correct (verified by full page reload). If you need to assert post-mutation UI state, reload the page rather than trusting the immediate snapshot after `wait_for` on the success toast.
- The Location Cleanup admin screen lives at `/app/admin/location-cleanup`. It queries `locationDuplicates` which groups location triples by case-insensitive canonical form (uppercase + trim + collapse whitespace) and surfaces variants. Empty state ("No location duplicates found") is the happy path. The merge dialog calls `mergeLocations` which rewrites every matching row across inventory_locations + opening_items + stock_items and writes one MOVE audit per row.
- The admin Projects page (issue #67) is the first screen backed by real server-side auth. The frontend now sends the Clerk session token on every GraphQL request (Apollo auth link via `window.Clerk.session.getToken()`), and two resolvers are gated on the Admin/Manager role: `adminProjects` (query) and `updateProject` (mutation). Unauthenticated calls to them return a GraphQL error with `extensions.code = "UNAUTHENTICATED"`; signed-in non-admins get `FORBIDDEN`. Every other resolver is still ungated, so existing tests are unaffected.
- Issues #198 and #380: free-form project creation is gone, and so is manual adoption. `createProject`/`CreateProjectInput` and `adoptGpJob`/`AdoptGpJobInput` no longer exist. Projects now appear on their own: the `gp_job_sync` background service creates one for every job in GP's job master (JC00102), on a ~5 minute timer and immediately on every relay reconnect, setting `projectId` = the GP job number and `description` = the GP job name. That means **there is no longer any way to seed a project through GraphQL without a relay** - the old ungated `adoptGpJob` fetch trick is dead. To get projects in a test environment, connect and enrol the relay and let the sync run, or hit the admin `syncGpJobs` mutation (Admin -> Projects -> "Sync from GP", which returns `{total, adopted}`) once a relay is up.
- Issue #380: the Import landing page's button is now "Create GP Job" (`CreateGpJobDialog`), rendered for the Admin/Manager role only - a non-admin sees the landing page with no create button. It originates a job in GP via `createGpJob(input: CreateGpJobInput!)`, which is admin-gated and requires a connected relay. Every field except the job number and name is a live GP read (`gpCustomers`, `gpCustomerAddresses`, `gpTaxSchedules`, `gpDivisions`, `gpEmployees`), so the whole form stays disabled while the relay is down. The two address selects stay disabled until a customer is picked and re-fetch when it changes. Eight optional fields sit behind a "Show optional fields" toggle. GP validates the submit and its own message is shown in the dialog - in TUBC the fiscal calendar ends 2025-09-30, so today's date reliably produces "Job cannot be created within a closed period"; use a FY2025 `createdDate` for a success path. Issue #392: Estimator and WS Manager are selects over `gpEmployees` (the GP payroll master UPR00100), not free text - the proc rejects an id that is not in that master with "The estimator does not exist in the payroll master table" (error state 51117). TUBC has exactly two employees, IANB and JONATHANR. `createGpJob` returns `{created, project}`: `created` is false when GP already held the job number and the mutation adopted it instead of creating one, so resubmitting an existing number succeeds with "already existed in GP and is now a project" rather than erroring. New projects default `offSiteStorageAgreement` to false and the GC/address fields to null, handy for testing the Projects edit flow.
- Issue #444: both address selects in `CreateGpJobDialog` carry a "+ Add new address" row pinned last (only when that picker's customer is set). It opens a nested `AddCustomerAddressDialog` scoped to that customer and creates the code in GP via `createGpCustomerAddress` (admin-gated, relay write `create_customer_address`, RM00102 create-only - the relay pins the proc's UpdateIfExists to 0). The address code uppercases as typed; on success the picker refetches and auto-selects the new code. A duplicate code answers relay code `address_code_already_exists` rendered inside the nested dialog, which stays open with the typed input intact. Verified live on pr-445 (2026-07-30): NEXTEST1 under ELL100 in TUBC, then a full `createGpJob` using it (NEXUS-444-T1). The op is new, so a release relay build answers RELAY_OP_UNSUPPORTED on the create (the reads still work) until the relay is rebuilt.
- A DataGrid driven by a `cache-and-network` query (e.g. the admin Projects grid) can render "0–0 of 0" for a beat on first mount before data arrives, so `take_snapshot` immediately after navigation may catch the empty state. Re-snapshot or `wait_for` a known row value before asserting the grid is empty.
- MUI `spinbutton` (number input) fields with a pre-filled value will APPEND when driven by `fill` or `fill_form` - "3" becomes "31" if you try to fill "1". Always click the field first, then `Control+A` to select all, then `fill` with the desired value. Alternatively use `evaluate_script` to set the value directly.
- The Transfer dialog success toast is very brief - by the time `take_snapshot` runs after the click, it may already be gone. Confirm success by observing the grid data (dialog closed + new/updated row present) rather than waiting for the toast text.
- There is no vendor field in PO create/edit at all since #509, and no Admin > Vendors page behind it - the local vendors table is gone. The only vendor a PO carries is the GP one (PM00200), chosen in the Register in GP dialog from the live `gpVendors` list, so a draft shows a blank vendor until it is registered. `/app/admin/vendors` now falls through to the Admin landing like any other unknown sub-route.
- Receiving wizard: after selecting POs and clicking "Receive N Selected", the Receive modal opens. The "Receive Now" spinbutton defaults to 0. Using `fill` fails (value doesn't stick on React controlled spinbutton). Use `evaluate_script` to focus the input, then `press_key` ArrowUp to increment. ArrowUp from 0 goes directly to the max (pending qty) in one press.
- Receiving wizard: "Assign locations & flag deficient units now" toggle appears only AFTER entering a Receive Now quantity > 0. Turn it on to get the Aisle/Bay/Bin text fields (regular textbox, not autocomplete). `fill_form` works fine on these.
- Transfer dialog Aisle/Bay/Bin: these are comboboxes with autocomplete="list". Use `evaluate_script` to set the underlying input value (native value setter + `input` event). This reliably sets the values without triggering dropdown selection. The Transfer button enables once all three fields are filled.
- Locations page (Warden filter, panel open): when a single warehouse filter is active, the left rail single-column shows just the bin name + qty (no warehouse chip in that column, since filter is already scoped). The right panel header still shows the warehouse chip (e.g. "WRD").
- Verifying a generated PDF (issue #230 PO document): the doc is text-based react-pdf, not an image, so `pdftotext` works. Fastest path for content assertions: use the dialog's "Save to PO documents" to upload it, query the PO's `documents { downloadUrl }` (presigned S3 URL) via GraphQL, `curl` the URL to a file, then `pdftotext -layout` (or `-raw` for the totals column, which `-layout` misaligns since Subtotal/Freight/Miscellaneous/Tax/Order-Total are right-aligned). "Generate & preview" opens a blob in a new tab that's hard to read via MCP - prefer save-then-fetch.
- pdftotext/poppler is NOT installed on the dev machine, and naive stream-inflation can't read the text (react-pdf subsets fonts to custom glyph IDs). Working alternative: open the presigned `downloadUrl` directly in a browser tab (Chrome renders PDFs natively) and `take_screenshot` - the full totals column is readable in the image. Verified this way for issue #156 (Tariffs line + Order Total math).
- Issue #156 fields: PO detail modal shows "Shipping Costs" / "Tariffs" info rows ('-' when null) and edit-mode number fields; the generate-document dialog's Freight prefills from the PO's shippingCost (saved documentData override wins) and its new Tariffs field from the PO's tariffAmount; the PDF prints a Tariffs totals line only when > 0.
- Issue #216 buyer identity (scoped to REGISTERING by issue #256 - drafting needs neither): registering a PO into GP REQUIRES the signed-in user to have a GP buyer identity (Clerk publicMetadata.gpBuyerId, set in Admin -> User Management) AND, for project POs, a buyer assignment (Admin -> Buyers: assigned projects). Without them the register dialog blocks and the backend rejects. The test user (Jay Puzon) is linked to GP buyer "mira" with project 80003 assigned. The register dialog's Buyer field is read-only (your identity); its cost-code dropdown offers every code GP has active on the job - per-buyer cost-code designation was removed (PR #430), so there is no Designated Cost Codes field in Admin -> Buyers anymore. Stock POs (no project) skip the assignment check but still need the identity.
- Issue #216 delivery dates: PO Requests capture "Preferred delivery date" per vendor card in the import wizard's PO step; the detail modal edits Preferred only while DRAFT and Expected only when GP-Registered/Vendor-Confirmed (server-enforced).
- Import-created PO drafts have EMPTY Order As values unless set in the wizard's PO step - the register dialog then blocks submit with per-line 'Required' errors until each line's Order As is filled.
- The generate dialog + admin PO-settings text fields APPEND when driven by `fill`/`fill_form` if they already hold a value (same MUI controlled-input quirk as spinbuttons). For a pre-filled field, set the value via `evaluate_script` using the native value setter + an `input` event (match the label's `for` attr to the input id), or drive the mutation directly. Empty fields fill fine.
- Date-only fields: a `<TextField type="date">` renders as Month/Day/Year spinbuttons in the a11y tree. Set it via `evaluate_script` native setter with a `YYYY-MM-DD` string on the underlying input (dispatch `input` + `change`). Note: formatting a `YYYY-MM-DD` string with `new Date(str)` is UTC and prints the previous calendar day in a behind-UTC tz - the PO-document code parses date-only strings as local (fixed in #238), so the printed required-by should match what was entered.
- To seed a project's job-site address for the PO document's "Use project site" ship-to option (most test projects have null address fields), call `updateProject(id, {jobSiteName, address, city, state, zip})` via `evaluate_script` (Admin/Manager gated). Then the dialog's "Use project site" button builds a real "UC Hardware Inc. - Deliver to site / ..." block.
- PO list rows: clicking the row's StaticText via a snapshot uid may NOT open the detail modal (the a11y click can miss the row handler). Reliable alternative: `evaluate_script` finding the leaf element by text and clicking its `closest('td')`.
- Locations page bin panel "Item actions" menu (stock rows): Move / Transfer / Adjust Qty / Unlocate. "Adjust Qty" opens the shared LocationActionDialog - Confirm stays disabled until a non-zero adjustment AND a reason are entered; the helper text under the adjustment shows the computed "New qty: N" and flags negatives. Verified live: adjustment writes an ADJUSTMENT audit row (`auditLog(limit: N)`) with performedBy "Admin/Manager".
- Draft PO create (issue #256 dialog) works with the relay down end to end: the created draft's `preferredDeliveryDate` round-trips exactly (entered 2026-08-15 -> stored 2026-08-15 -> detail modal renders 8/15/2026, no UTC day shift). Cancelling a draft removes it from the `purchaseOrders` list entirely.
- Availability semantics (issue #229): available = quantity - deficient, so a 10-qty row with 7 deficient shows available 3. Read it per row via `inventoryRows` (`inventoryLocation.available`) or per combo via `projectInventoryAvailability`; cross-check against `deficientItems`. (The old `inventoryHierarchy` roll-up query that documented this is deleted.)
- `Notification` has no `kind` field - it is `type` (`{ notifications { id type message isRead createdAt recipientRole projectId } }`). Querying `kind` fails the whole document, so a mistyped notification field takes the relay/pull/request fields in the same query down with it.
- The bell panel is a plain MUI Popover with a "Notifications" heading and one bold row per unread item; the app-bar badge count matches `notifications` where `isRead: false`. It renders every audience regardless of your role, so 4 in the badge means 4 rows in the panel.
- `shopAssemblyRequests` takes a `status` and defaults to **PENDING**, so `[]` means the accept queue is empty, not that no requests exist. Ask for `status: APPROVED` (or `REJECTED`) to see the rest; every row carries a derived `stage` telling you how far its pull has got.

### Driving the app with the Chrome MCP tools

- **`file_upload` caps at 10 MB and `contracterp-74.xml` is 11.5 MB**, so the real fixture cannot be uploaded through the tool at all. Either take the "Use last uploaded schedule" card (almost always right), or build a subset: keep everything up to `<Detail>` (that block holds all 1998 opening/assignment definitions, ~1.07 MB) then append `<Detail>` + the first N `</Material_List>`-delimited blocks + `</Detail></Contract>`. ~600 blocks lands at ~3.5 MB, parses clean, and yields "1998 openings parsed / 12746 hardware items parsed / 22 opening(s) had no hardware items assigned". Parsing is entirely client-side - nothing is persisted until Finalize - so uploading a trimmed file is safe on a database you are trying to preserve.
- **`navigate` costs a full reload and wipes any instrumentation you injected.** React Router picks up `history.pushState(...)` + `window.dispatchEvent(new PopStateEvent('popstate'))`, so route sweeps can be done client-side with a `fetch` wrapper still installed. That wrapper is far better evidence than `read_network_requests`, which only starts recording when first called and misses everything before it, and it can see GraphQL errors - which come back **HTTP 200** with an `errors` array, so status-code filtering finds nothing.
- **A `javascript_tool` call that hits the 45s CDP timeout keeps running in the page.** Its `await` chain continues after the tool has given up, so the next call races it and you get results tagged with the wrong route. Keep loops under ~8 route-hops, or step one route per call. If output ever looks mismatched, sleep ~6s and start over.
- `computer screenshot` times out with "renderer may be frozen" while the Import wizard renders 1998 openings or 26k classification rows. It is not frozen - wait 10s and take it again. Same for the first paint after "Use last uploaded schedule".
- The screenshot image is scaled down from the real viewport (1568px wide image for a 1918px window), so a card that looks cut off at the right edge usually is not. Check `document.documentElement.scrollWidth === clientWidth` before reporting a horizontal-overflow regression.
- The Pull Request detail modal **closes on Escape since the 2026-07-28 UI revamp** (it used to swallow it). Its nested confirm dialogs are siblings, so an Escape inside a confirm closes only the confirm. "Cancel Pull" is still a real destructive action - never use it as a way out.
- MUI option cards (import Purpose, module "Go to" cards) are `useNavigate` buttons with no `href`, so there are no anchors to click and `find`'s ref sometimes lands on the inner text node rather than the clickable card. Setting the underlying `input[type=radio]`/`input[name=select_row]` via native `.click()` works reliably and does update React state.
- The import landing project card is a `MuiCardActionArea` **button** wrapping the `MuiPaper`. Coordinate clicks land on it only sometimes (it takes focus but does not activate, and Enter does not help either). Reliable: find the element whose `textContent` matches the project *and* whose `tagName === 'BUTTON'`, then `.focus()` + `.click()`.
- **Select Openings is paginated at 50 rows/page, ordered by the schedule, not sorted**, and the "Filter" control is a Select (column filter), *not* a text search - there is no way to type an opening number. To enumerate or tick specific openings, scroll the `.MuiDataGrid-virtualScroller` in ~150px steps, and after each `scrollTop` assignment **dispatch a `scroll` event and wait ~450ms** or the virtualizer does not re-render and you silently collect only the first screenful (17 of 50). Keep the sweep under ~40s of `await` or the 45s CDP cap kills the call mid-loop - it leaves the page in a valid state (rows already ticked stay ticked), so just re-run and top up the selection.
- The Receive modal has **two** confirmations: `Complete Receive` opens a nested `Confirm Receive` ("Receive N items across M PO into inventory?") whose button is just `Receive`. Scripting only the outer button looks like a silent no-op - inventory stays empty and the outbox stays at 0 because no mutation ever fired.
- Receive modal quantity + location fields take a native value-setter + `input`/`change` event fine (no need for the ArrowUp trick), and the location block only appears once a Receive Now qty > 0. `all placed` chips per product gate `Complete Receive`.
- **DataGrid rows are invisible to `take_snapshot`.** The a11y snapshot gives you `columnheader`s and
  the pagination controls and *nothing else* - no row uids - so `click(uid)` cannot reach a row at
  all. Read rows with `evaluate_script` over `[role="row"]`, and prefer the per-cell form, which
  gives you the column names too:
  `[...r.querySelectorAll('[role="gridcell"]')].map(c => ({field: c.getAttribute('data-field'), text: c.innerText}))`.
  To open one, dispatch the event yourself:
  `cell.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}))`.
- **Read grid rows twice after switching tabs.** A read ~3s after a tab click came back with the last
  two cells missing (`... | Jay Puzon | 2` and nothing else); the same read a moment later had the
  full six. It is render timing, not a bug - do not report a missing column off a single sample.
- **Multi-line cells arrive as one string.** The Phase cell is a tag over a caption, so its `innerText`
  reads `PENDING
Not started` - replace newlines before matching, or assert on the parts.
- **Waiting for a Railway deploy**: poll the *schema* for a field the new build adds rather than
  guessing at a duration -
  `{ __type(name: "PickSheetSection") { fields { name } } }` until the new field appears. Backend and
  frontend deploy separately; the backend took ~225s from merge to serving on 2026-07-28. `/health`
  answering is not sufficient, it answers on the old build too.
- **Most warehouse reads are ungated, so curl is faster than the browser for setup and assertions.**
  `pullRequests`, `inventoryItems`, `inventoryHierarchy` and `auditLog` all answer unauthenticated;
  `shopAssemblyRequests`, `relayStatus` and the pick mutations are `require_user`. A partially-gated
  query returns HTTP 200 with `data.<field>: null` *and* an `errors` array - if a list looks
  mysteriously empty, print `errors` before concluding the data is missing.
- Allocator step (#378) specifics: the summary table is `Owed / Available / Allocated / Left to assign / Short`; each leaf card carries a `Fully covered` / `Not covered - auto-dropped` chip, an `N of M allocated` caption and an include/exclude toggle; the steppers have `aria-label`s `Add one <productCode>` / `Remove one <productCode>` and the `+` disables at `allocated === owed`. Driving a leaf's only line to 0 flips it to auto-dropped, greys the card, drops it out of the `Door leaves (N of M being sent)` count, removes its owed units from the summary, and shows an amber `N short` chip - **and Next stays enabled**, which is the whole point of the change.

## 2026-07-28 UI revamp - what changed for testers

An experimental aesthetic+motion revamp landed on master (single revertable PR). Business logic,
queries/mutations and every action are unchanged, but a lot of chrome moved:

- **Navigation is a persistent left rail on desktop** (collapsible via the panel icon in the app
  bar; state persists in localStorage `uc-nexus-rail-collapsed`). The hamburger-opens-drawer flow
  now exists only below the `md` breakpoint. Sub-items expand under
  the active module. The `<- Warehouse` / `<- Projects` back buttons are gone - breadcrumbs (now
  labelled "Purchase Orders", "Start a Request") are the way back.
- **Icons are lucide (stroke) not Material (filled)**; icon-only buttons gained aria-labels
  (e.g. `Open <PO> details`). Snapshot selectors keyed on Material icon `data-testid`s will miss.
- **Stat values animate** (count-up over ~0.5s on mount). A snapshot taken immediately after
  render can catch a mid-flight number - `wait_for` the final value or re-snapshot. With
  `prefers-reduced-motion`, values render instantly.
- **PO list**: the 7 stat tiles are now one status strip; segments are still the same filters
  (`aria-pressed`, `aria-label="Filter by <status>"`). The whole data row opens the detail modal;
  the leading chevron cell only toggles the line-item expand. Empty modal fields render an em-dash
  `—` (was `-`).
- **Escape behavior changed on purpose**: Pull Request detail modal now closes on Escape;
  Receive modal and Transfer dialog now *block* Escape once you have typed values into them
  (they used to discard silently). The assembly modal's close semantics are unchanged.
- **Shipping browse (Ship tab)** lists the staged pool - what a completed shipping-out pull put on
  the floor, minus what a slip has already carried out - with a text search and the container
  workspace beside it. The per-leaf status panel it used to carry is gone with the leaves.
- **Import wizard**: step 1 shows a single success strip (the old second green alert is merged
  in); Purpose options are cards now but the radio semantics and the exact label strings
  ("Create Purchase Orders", "Pull Request for Shop Assembly", "Pull Request for Shipping Out")
  are unchanged.
- **Warehouse/Admin/Shop-Assembly landings**: the "Go to" cards now carry live counts (pending
  pulls, unlocated, deficient, etc.), driven by the same queries as before.
- **DevAction: drop and rebuild schema** is finally visible in light mode (it was ink-on-ink);
  same label, now to the right of the bar spacer, and its confirm button is red.
- Home's Recent Activity renders human sentences ("Staged door leaf ..."), never raw enums like
  `INSTALL_PROGRESS SHOP_ASSEMBLY_OPENING`. Since PR #396 the rows also carry a real identity mined
  from the audit `detail` payload - `Staged door leaf 62 · L1`, `Pulled inventory item 2× BB1068 ...
  · SA-E2E-367`, `Received ... · PO0000066` - with the shortened UUID only as a last resort.
- Every server timestamp in the app parses as UTC since PR #399 (`parseServerDate`; backend
  datetimes are naive-UTC with no zone suffix). Relative times reading "just now" for hours, or
  wall-clock times off by your UTC offset, are a regression of that fix, not server clock drift.
