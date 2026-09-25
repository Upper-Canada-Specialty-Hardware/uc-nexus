# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UC Nexus is a door installation hardware management system. It tracks hardware schedules imported from TITAN (hardware schedule writing software) through the full lifecycle: import, purchase orders, warehouse receiving, shop assembly, and shipping out.

## Architecture

**Monorepo** with two deployable services sharing a single git root:

- `backend/` — Python 3.11, FastAPI + Strawberry GraphQL + SQLAlchemy 2.0 + Alembic
- `frontend/` — React 19, TypeScript, Vite, Apollo Client 4, MUI 7, Tailwind CSS 4

Communication is entirely through a single `/graphql` endpoint (Strawberry GraphQL). There is no REST API beyond `/health` and a dev-only `/admin/reset-data`.

### Backend layers

```
main.py              → FastAPI app, GraphQL router, error handler extension
app/schemas/         → Strawberry types, queries, mutations, inputs, enums (GraphQL schema)
app/repositories/    → Data access (SQLAlchemy queries, business logic)
app/models/          → SQLAlchemy ORM models + enums.py (DB enums)
app/services/        → Cross-cutting services (notifications, locking, PDF)
app/database.py      → Engine + SessionLocal factory
app/config.py        → DATABASE_URL from .env
app/errors.py        → AppError hierarchy (ValidationError, NotFoundError, ConflictError, etc.)
alembic/             → Migration scripts, env.py reads DATABASE_URL from environment
```

Repositories open their own `SessionLocal()` sessions (no dependency injection). GraphQL resolvers call repository functions directly.

There are two separate enum files: `app/models/enums.py` (DB-level Python enums) and `app/schemas/enums.py` (Strawberry GraphQL enums). Keep them in sync when adding new enums.

### Frontend structure

```
src/main.tsx          → App entry (Apollo, MUI theme, context providers)
src/App.tsx           → Routes, lazy-loaded modules
src/modules/          → Feature modules (import, po, warehouse, shop-assembly, shipping, admin)
src/components/       → Shared UI (DataTable, Modal, Wizard, Toast, etc.)
src/contexts/         → React contexts (Role, Project, Wizard, Cart)
src/graphql/          → queries.ts + mutations.ts (Apollo gql documents)
src/hooks/            → Custom hooks (useHardwareScheduleParser)
src/workers/          → Web workers (XML parser runs in worker thread)
src/types/            → Shared TypeScript types
```

Each module in `src/modules/` has an `index.tsx` that serves as the route entry point, lazy-loaded by `App.tsx`.

Apollo Client uses sub-path imports: `@apollo/client/core`, `@apollo/client/react`, `@apollo/client/link/error`, `@apollo/client/errors`.

## Development Commands

### Backend (run from `backend/`)

```bash
poetry install                          # Install dependencies
poetry run uvicorn main:app --reload    # Start dev server (port 8000)
poetry run ruff check .                 # Lint
poetry run ruff format --check .        # Format check
poetry run ruff format .                # Auto-format
poetry run pytest                       # Run all tests
poetry run pytest tests/test_health.py  # Run a single test file
```

### Frontend (run from `frontend/`)

```bash
npm ci                    # Install dependencies
npm run dev               # Start Vite dev server (proxies /graphql to :8000)
npm run lint              # ESLint
npm run build             # TypeScript check + Vite build
npm run test              # Vitest in watch mode
npm run test:run          # Vitest single run (CI mode)
```

### Database / Migrations (from `backend/`)

```bash
poetry run alembic upgrade head                        # Apply all migrations
poetry run alembic revision --autogenerate -m "desc"   # Generate migration from model changes
poetry run alembic check                               # Verify models match migrations (no drift)
poetry run alembic downgrade -1                        # Rollback one migration
```

Alembic `env.py` reads `DATABASE_URL` from `.env` (via python-dotenv). The `compare_type=True` flag is enabled for migration autogeneration.

## CI Pipeline

GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR to `master`:

- **Frontend**: `npm ci` → `lint` → `test:run` → `build`
- **Backend**: `poetry install` → `ruff check` → `ruff format --check` → `pytest` → `alembic upgrade head`
- **Migration Integrity**: `upgrade head` → `downgrade base` → `upgrade head` → `alembic check`

## Deployment

Both services deploy to Railway via Dockerfiles. Backend entrypoint auto-runs `alembic upgrade head` before starting uvicorn.

## Environment

- The GitHub repo and the Railway deployment are the **test environment**.
- All existing data is dev-only. It is safe to drop or recreate the DB or manipulate it directly.
- The Railway CLI is installed on developer machines.
- psql cannot be installed locally (business restriction). Use Alembic migrations for DB schema changes.
- The Railway Postgres public TCP proxy is reachable from company machines. For a one-off read, run a Python script through `railway run --service Postgres --environment <env> -- poetry run python script.py` and connect with `DATABASE_PUBLIC_URL`.

## Key Conventions

- Backend linting: Ruff (line-length 120, target Python 3.11)
- Frontend linting: ESLint 9 flat config with typescript-eslint + react-hooks + react-refresh
- Frontend testing: Vitest with jsdom environment, `@testing-library/react`, test files co-located as `__tests__/*.test.{ts,tsx}`
- Models use SQLAlchemy 2.0 `Mapped[]` type annotations
- GraphQL errors use the `AppError` → `GraphQLError` extension pattern with `code` and optional `field`
- Hardware schedule XML parsing happens client-side in a web worker (`fast-xml-parser`)

## GraphQL / SQLAlchemy Performance Rules

The biggest perf trap in this codebase is the **resolver/DTO-builder N+1**: a `_xxx_to_type` helper iterates an ORM relationship collection (`p.openings`, `po.line_items`, `sar.openings`, etc.) to build the Strawberry type. If the resolver that called it didn't `selectinload` that relationship, SQLAlchemy issues a separate `SELECT` for every parent row. With Railway's network hop to managed Postgres, this turns "fast on dev" queries into multi-minute requests in production. Apollo then queues additional in-flight queries behind the same DB pool, and from the user's perspective the page is frozen.

Apply these rules whenever you touch resolvers or `_xxx_to_type` helpers:

1. **Every relationship a `_xxx_to_type` helper iterates must be `selectinload`-ed by the calling resolver.** If you add a new field that walks a relationship, audit every caller of that helper.
2. **List resolvers must never lazily load child collections.** Either `selectinload` the relationship, or — preferred for list views — skip building it and expose a scalar (`opening_count`, `line_item_count`, etc.) computed via a single grouped query (`select(Child.parent_id, func.count()).group_by(Child.parent_id)`).
3. **Don't request fields you don't use.** A `query { projects { openings { id } } }` from the frontend forces the backend to materialize every Opening object even if only `id` is read. Prefer scalar summary fields (`openingCount`) for list views.
4. **`_xxx_to_type` helpers that can be called in both list and detail contexts should take an `include_<relationship>: bool` flag** (e.g. `_project_to_type(p, *, include_openings, opening_count=None)`). List callers pass `include_openings=False` and the precomputed count; detail callers leave defaults.
5. **`.unique()` doesn't help with N+1.** It only dedupes rows; if you didn't `selectinload`, accessing the relationship still triggers per-row lazy queries.
6. **When investigating "slow page" reports, pull Railway HTTP logs first** (`mcp__Railway__get_logs` with `log_type: "http"`). Look for cohorts of 200/499s with multi-second `duration_ms`; that's the signature of pool starvation behind a slow resolver, not a hung backend.

## Frontend Lazy-Loading Rules

UC Nexus modules are code-split via `React.lazy(() => import('./modules/<name>'))` in `frontend/src/App.tsx`. Each module ships as a separately hashed JS bundle in `assets/`. Two failure modes follow from that:

1. **All lazy routes must be wrapped in `LazyRoute` from `components/LazyBoundary.tsx`**, not bare `<Suspense>`. `LazyBoundary` catches `ChunkLoadError` / "Failed to fetch dynamically imported module" and triggers a single `window.location.reload()` (cooldown via `sessionStorage` to prevent reload loops). Without this boundary, a stale tab whose in-memory module graph references the previous build's chunk hashes will go white-page the first time the user navigates to a not-yet-loaded route after a deploy.
2. **`index.html` must be served with `Cache-Control: no-cache, must-revalidate`** (see `frontend/nginx.conf`). The hashed asset filenames in the HTML are the only signal to a browser of which chunk hashes are current. Hashed assets in `/assets/` stay `public, immutable` with a 1y expiry — that's correct because the hash changes on every content change.

## UI Laws

Two laws govern every screen. They outrank visual preference and apply to all UI work in this project.

1. **Space is used efficiently, always.** This is the highest-priority UI value here. No wasted gaps, no columns spreading short values across empty space, no panel sprawling vertically while it is starved horizontally. Size elements to their content and let one flexible element absorb the slack. In a master-detail layout, collapse the list to a compact rail and give the detail the freed width. If a region renders mostly empty, the layout is wrong - rebalance it. The test on any new or changed UI: is every region earning its space? If not, fix it before shipping.
2. **No horizontal PAGE scroll, ever.** The viewport never scrolls sideways to reveal primary content. `html, body { overflow-x: hidden }` in `frontend/src/index.css` is the enforced guard - it clips rather than scrolls, so a layout that overflows gets a clipped (invisible) control, which is a bug, not an acceptable state. Layouts MUST fit. A component MAY scroll horizontally inside its own bounded container when that is genuinely the right affordance (a wide data grid, a horizontal carousel); the ban is on the page widening, not on every internal scroll. Put `minWidth: 0` on flex/grid children so they shrink to fit instead of forcing overflow - a missing `minWidth: 0` is the most common cause of accidental page-width blowout.

Both laws are read every session and weighed on review.

## Testing

See [testing/CLAUDE.md](testing/CLAUDE.md) for the simulated user testing guide (Chrome DevTools MCP, app workflows, interaction patterns). Read the `testing/` knowledgebase only when testing actually begins - not during planning or implementation - to avoid consuming context prematurely; testing, when done, is performed by the main agent directly, not the `tester` subagent.

Plans do NOT end with a Simulated User Testing section - omit it.

