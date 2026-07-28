# iui/ - Impeccable UI design artifacts

This folder holds the design-system context that the [Impeccable](https://github.com/anthropics/impeccable)
design skill reads before it touches any frontend code. These are agent artifacts, not product
documentation, which is why they live here instead of in `docs/`.

| File | What it is |
| --- | --- |
| `DESIGN.md` | The binding visual contract: tokens in YAML frontmatter, then the prose system (colors, typography, elevation, components, do's and don'ts). Frontmatter is normative. |
| `PRODUCT.md` | Durable product context: who uses UC Nexus, brand personality, anti-references, design principles, accessibility floor. |

## Required environment variable

Impeccable resolves `PRODUCT.md` and `DESIGN.md` in a fixed order: the project root first, then
`.agents/context/`, then `docs/`, and only then the `IMPECCABLE_CONTEXT_DIR` override. Because these
files live in `iui/`, which is not one of the built-in fallback directories, that override is the
only thing that makes them discoverable:

```
IMPECCABLE_CONTEXT_DIR=iui
```

For Claude Code this is set in `.claude/settings.json`, which is gitignored in this repo, so **a
fresh clone will not have it**. Set it before running any Impeccable command, or the skill resolves
`designPath: null`, concludes the project has no established visual system, and is free to invent a
new one. Verify with:

```
node <impeccable-skill-dir>/scripts/context.mjs
```

`productPath` and `designPath` in the `RESOLVED_CONTEXT` block should read `iui\PRODUCT.md` and
`iui\DESIGN.md`. If either is `null`, the variable is not set.

## What could not move here

`.impeccable/` stays at the repo root. Its location is a hardcoded constant in the skill
(`lib/impeccable-paths.mjs`, `IMPECCABLE_DIR = '.impeccable'`) with no override, and every path
beneath it is derived by joining that constant to the project root. It holds:

- `design.json` - the sidecar extending `DESIGN.md` with tonal ramps, shadow and motion tokens,
  breakpoints, renderable component snippets, and the narrative. Tracked; regenerate it whenever
  `DESIGN.md` changes, or the two contradict each other.
- `hook.cache.json`, `config.local.json`, `live/`, `critique/` - machine-local state. Gitignored.

## Keeping the two in sync

`DESIGN.md` and `.impeccable/design.json` are one contract split across two files. When `DESIGN.md`
is edited without regenerating the sidecar, the sidecar keeps serving the previous design to the
detector and the live panel. `/impeccable doctor` reports this as `design-sidecar-stale`; the repair
is `/impeccable document`, asking it to refresh the sidecar only and preserve `DESIGN.md`.
