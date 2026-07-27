# Running the relay channel across more than one backend replica

**Status: designed, not built. Do not build it yet.** This document exists so that when the
prerequisite actually arrives, the work is execution rather than design (#353 PR F).

## Why this is deferred

Railway runs **one** backend replica, there is **one** relay, and the project has **no Redis
service**. `relay_gateway` holds the single live socket in module memory, and that is correct under
those conditions — `services/relay_gateway.py` says so explicitly.

Adding Redis today would buy nothing and would put a new hard dependency directly in the auth-and-
dispatch path of every GP write. A Redis blip would then become a GP outage: a *worse* failure mode
than the one being fixed, and precisely the kind of trade #353 exists to stop making.

### The prerequisite trigger

Build this when **either** becomes true, and not before:

1. The backend runs more than one replica (horizontal scaling, or a rolling deploy that overlaps
   two live containers rather than replacing one).
2. A second relay — a second company, or a second workstation — needs to be connected concurrently.

Until then, the single-socket registry plus the incumbent-wins rule is the simpler correct design.

## Why not sticky routing

The obvious alternative is to pin a relay's WebSocket to one replica at the proxy. Railway's proxy
offers no WS-aware sticky routing keyed on anything the relay controls, so there is no reliable way
to make "the replica that holds the socket" and "the replica that received the GraphQL mutation" the
same process. Pub/sub between replicas is the path.

## Design

### Ownership lease

The replica holding a relay's socket takes a lease:

```
SET relay:owner:{install_id} {instance_id} NX PX 30000
```

- Refreshed every 10 s by the owner, on the heartbeat it already runs (`_relay_heartbeat_loop`) — no
  new timer.
- Released on `unregister`.
- **Only the lease holder may write to the socket.** That is the whole invariant.

`NX` plus the incumbent-wins rule already in `try_register` is what stops two replicas both believing
they own the same relay after a network partition.

### Dispatch

A replica that does *not* own the socket cannot call `relay_call` locally. Instead:

1. Caller **subscribes** to `relay:replies:{job_id}` — **before** publishing. Subscribing after the
   publish races the reply and loses it intermittently, which would look exactly like a relay
   timeout.
2. Caller publishes `{job_id, company, op, payload, reply_to}` to `relay:jobs:{instance_id}` of the
   owning replica.
3. The owner runs today's `relay_call` locally and publishes the reply to `relay:replies:{job_id}`.

The timeout, the `unknown_op` mapping and the error taxonomy stay where they are; only the transport
between the caller and the socket-holder changes.

### Registry read

`relayStatus` stops being a read of local module state and becomes:

- `relay:owner:*` — who is connected, and which replica holds them.
- `relay:meta:{install_id}` — a hash carrying `company`, `build`, `connected_at`.

### Fallback

**No owner key ⇒ `RelayUnavailableError(dispatched=False)` ⇒ the PR E outbox absorbs the write.**

This is why the outbox landed first. Without it, a multi-replica rollout would turn every "the owner
lease had just expired" moment into a user-visible failure; with it, those writes queue and drain.

### Failure modes to handle explicitly

| Failure | Required behaviour |
|---|---|
| Redis unavailable | **Fail closed to the outbox.** Never bypass the lease and write to a local socket "just in case" — that is how two replicas post the same GP receipt. |
| Lease expires mid-job | The reply can no longer be delivered, so the caller must treat it with `dispatched=True` semantics: GP may hold the write, so it is `ambiguous` and must not be auto-retried. |
| Duplicate owners after a partition | The `NX` lease plus incumbent-wins resolves it; the loser must `unregister` rather than keep serving. |

## What stays the same

- Every GP write is still an `EXEC` of an eConnect-registered proc on the relay. Nothing here changes
  the GP access path.
- The idempotency ledger (`gp_write_idempotency`) is still the thing that makes a retry safe, and it
  is already shared state in Postgres — it needs no Redis equivalent.
- The outbox is still the durability layer; Redis is a routing layer only, and must never become the
  system of record for a pending write.
