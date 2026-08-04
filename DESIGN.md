---
name: UC Nexus
description: Internal door-hardware fulfillment tool - one shared toolkit across import, PO, warehouse, shop, and shipping
colors:
  ink: "#1d1b17"
  ink-hover: "#3a362f"
  ink-dark: "#e9e5dc"
  paper: "#fdfcfa"
  canvas: "#f2f0ea"
  paper-dark: "#201e1b"
  canvas-dark: "#161513"
  text-secondary: "#5c564b"
  text-secondary-dark: "#a49e91"
  shop-amber: "#ffca28"
  shop-amber-hover: "#ffb300"
  shop-amber-dark: "#ffd54f"
  status-success: "#2e7d32"
  status-warning: "#ed6c02"
  status-error: "#d32f2f"
  status-info: "#0288d1"
typography:
  display:
    fontFamily: "Source Sans 3 Variable, Source Sans 3, Helvetica Neue, Arial, sans-serif"
    fontSize: "2.125rem"
    fontWeight: 700
    lineHeight: 1.235
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Source Sans 3 Variable, Source Sans 3, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.334
  title:
    fontFamily: "Source Sans 3 Variable, Source Sans 3, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.6
  body:
    fontFamily: "Source Sans 3 Variable, Source Sans 3, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.43
  label:
    fontFamily: "Source Sans 3 Variable, Source Sans 3, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.66
  micro-label:
    fontFamily: "Source Sans 3 Variable, Source Sans 3, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 700
    letterSpacing: "0.08em"
    textTransform: uppercase
  identifier:
    fontFamily: "IBM Plex Mono, Cascadia Code, Consolas, ui-monospace, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
rounded:
  control: "3px"
  tag: "3px"
  input: "4px"
  card: "6px"
  dialog: "10px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    padding: "6px 20px"
  button-secondary:
    backgroundColor: "{colors.shop-amber}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "6px 20px"
  button-outlined:
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "6px 20px"
  status-tag:
    rounded: "{rounded.tag}"
    fontSize: "0.6875rem"
    fontWeight: 600
    letterSpacing: "0.05em"
    textTransform: uppercase
    treatment: "tinted background at 12% of the status hue, 1px border at 55%, text in the status hue"
  card:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.card}"
    padding: "16px"
  dialog:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.dialog}"
  ledger-table-header:
    backgroundColor: "transparent"
    borderBottom: "2px solid {colors.ink}"
    typography: micro-label
---

# Design System: UC Nexus

## 1. Overview

**Creative North Star: "Shop instrument, not admin template."**

UC Nexus is one continuous lifecycle - TITAN import, purchase orders, warehouse receiving, shop
assembly, shipping - and every module draws from a single MUI theme: one warm-neutral palette, two
typographic voices, one 3px-edge accent motif, one component set. The visual language never changes
station to station. What changes is density and rhythm, and only that.

The character is industrial and precise - a dependable shop tool. The neutrals are *warm* steel and
kraft (never the stock Material grey ramp): ink `#1d1b17`, bone canvas, warm-white paper, and a
night-shift warm charcoal in dark mode. Structure is carried by hairline borders and 2px ink rules,
not shadows or tinted fills. A single Shop Amber accent marks the one thing that matters on a screen
and doubles as the selection *edge*. Data speaks in its own voice: identifiers in a mono face,
counts in tabular numerals, captions as stenciled micro-labels. Iconography is stroke-based
(Lucide), never filled Material glyphs.

Density flexes by station, within the one language:

- **Dashboard (home):** compact bordered gauges and a bounded activity feed, scannable in one glance.
- **Operational tables (PO, warehouse):** the ledger is the screen - 2px header rule, mono
  identifiers, right-aligned tabular counts, inline filters, status tags, row hover with a clear
  affordance.
- **Guided wizard (import / Start a Request):** linear and calm; one decision per step; step content
  transitions quickly.
- **Master-detail (shop assembly, shipping, locations):** compact list rail plus a wide detail pane;
  the rail collapse is animated so the space handoff reads as physical.
- **Task modals:** focused overlays; titled, section-ruled, actions bottom-right, destructive
  actions in the error hue.

This system explicitly rejects consumer SaaS gloss, sprawl (regions that don't earn their space),
legacy-ERP gray-on-gray, and decorative motion. If a screen looks like a template, it is wrong.

**Key Characteristics:**
- One shared theme across every module; density varies, vocabulary does not.
- Warm steel/kraft neutrals + a single Shop Amber accent spent as edge + primary action.
- Flat and bordered at rest; elevation only as feedback (hover, dialogs).
- Two type voices: Source Sans 3 for UI, IBM Plex Mono for identifiers; hierarchy from weight/size.
- Every region earns its space; the viewport never scrolls sideways.
- Full light and dark schemes, WCAG 2.1 AA, `prefers-reduced-motion` respected.

## 2. Colors

A warm near-neutral system carried by ink and kraft tones, with exactly one saturated accent. Two
full schemes via MUI CSS variables.

### Primary
- **Ink** (`#1d1b17`, dark scheme `#e9e5dc`): the structural color - app bar, primary buttons,
  headings, body text, the ledger header rule. Hover deepens to `#3a362f` (dark: `#c9c4b8`).

### Secondary
- **Shop Amber** (`#ffca28`, dark `#ffd54f`): the single accent. The screen's primary action fill,
  and the 3px edge that marks selection/current state (selected rows, active nav item, active
  wizard step, attention gauges). Hover `#ffb300`. Spent on roughly 10% of a surface.

### Tertiary
- **Status set** (success `#2e7d32`, warning `#ed6c02`, error `#d32f2f`, info `#0288d1`): semantic
  only - relay/GP state, lifecycle status, validation. Rendered as square stenciled tags (see
  Components), never decoratively.

### Neutral
- **Paper** (`#fdfcfa`, dark `#201e1b`): cards, dialogs, table bodies, the nav rail.
- **Canvas** (`#f2f0ea`, dark `#161513`): the page ground behind surfaces.
- **Hairlines** (`rgba(29,27,23,0.14)`, dark `rgba(233,229,220,0.16)`): borders carry structure in
  place of shadow.

### Named Rules
**The One Accent Rule.** Shop Amber marks at most one primary thing per screen, plus the selection
edge. If two amber fills compete, one is wrong.

**The Amber-Edge Rule.** Selection and "current" are expressed as a 3px amber left edge (rows, nav
items, gauges, steps) - never as a full amber fill on content surfaces.

**The Status-Only Color Rule.** Status hues mean real system state, exclusively.

**The Warm-Neutral Rule.** No pure Material greys (`#f5f5f5`, `#eeeeee`, `#9e9e9e`...). Every
neutral comes from the warm ramp above.

## 3. Typography

**UI voice:** Source Sans 3 Variable - headings, labels, buttons, prose.
**Data voice:** IBM Plex Mono - identifiers and codes.

### Hierarchy
- **Display** (700, 2.125rem, -0.01em): page titles. One per screen.
- **Headline** (600, 1.5rem): section headers.
- **Title** (600, 1.25rem): sub-sections, dialog titles, gauge values (gauges may go to 1.7rem/700).
- **Body** (400, 0.875rem): the workhorse.
- **Label** (500, 0.75rem): helper text, sentence case.
- **Micro-label** (700, 0.6875rem, +0.08em, UPPERCASE): table headers, gauge captions, eyebrows,
  status tags. This is the stencil voice - use it for labels-of-data, never for prose.
- **Identifier** (mono, 0.8125rem): PO/request numbers, product codes, opening/leaf refs, bins,
  packing slips. Never for prose.

Buttons: body size, weight 600, `text-transform: none`.

### Named Rules
**The Fixed-Scale Rule.** Fixed rem sizes, never fluid/clamp().

**The Two-Voice Rule.** Source Sans 3 for UI, Plex Mono for identifiers - no third family, no
display face. Anything that names a *thing in the system* (a PO, a code, a bin) is mono; anything
that talks to the user is sans.

**The Tabular Rule.** Any column of figures gets `font-variant-numeric: tabular-nums` and right
alignment.

## 4. Elevation

Flat by default; hairlines and the canvas/paper split carry structure. Depth only as feedback:
- **Card hover** (`0 4px 14px rgba(29,27,23,0.09)`, dark `rgba(0,0,0,0.45)`) with a one-step border
  darken and an optional 1px lift, 0.2s.
- **Dialog** (MUI default + 1px hairline border).

**The Flat-At-Rest Rule.** A resting shadow is a bug.

## 5. Components

### Buttons
- 3px radius, `6px 20px`, weight 600, no elevation, no uppercase.
- **Secondary (default)**: amber fill, ink text - the screen's one primary action.
- **Primary**: ink fill, paper text - structural/confirm.
- **Outlined / Text**: quiet ink-on-transparent for lower-priority actions.
- **Destructive**: `color="error"` outlined - cancelling a PO or pull IS real state.
- Never hardcode a palette hex in a component override that must work on both light surfaces and
  the ink app bar - use theme vars so `color="inherit"` survives.

### Status tags (formerly chips)
Square (3px), uppercase micro-label type, tinted ground (12% of status hue) + 1px border (55%) +
status-hue text. Meanings: success = done/staged/closed, warning = pending/attention, info =
in-progress, error = failed/cancelled, ink = registered/structural, default = neutral (Draft).

### Cards / Gauges
6px radius, paper on canvas, hairline border, hover feedback only. **Stat gauges**: value in
1.5-1.7rem weight-700 tabular numerals (animated on mount), micro-label caption, compact padding,
`flex: 1 1 0; min-width ~130px`; an optional 3px left edge carries meaning (amber = needs someone
now, status hue = real state). Zero-value gauges render dimmed, never celebrated.

### Inputs
MUI outlined, `size="small"`, 4px radius, real floating labels (placeholder-only labels are a bug).

### Navigation
- **App bar:** ink in both schemes, sticky, elevation 0.
- **Nav rail:** persistent on desktop, collapsible to icon rail; active module carries the amber
  edge; stroke icons; mobile falls back to a drawer.
- **Breadcrumbs:** 0.875rem, human labels (never raw path segments).

### The Ledger (signature component)
Tables and DataGrids: transparent header with a **2px ink rule** underneath, micro-label header
type, hairline row dividers, row hover, mono identifier columns, right-aligned tabular numeric
columns, amber-edge selection. Density is highest here; sprawl is most forbidden here. A row that
opens something shows a trailing chevron and pointer cursor, and the whole row is the target.

## 6. Motion

Physical, quick, and state-bearing - the app should feel like a well-oiled machine, not a slideshow.
One vocabulary (`src/motion`): springs at ~0.22s / ~0.34s / ~0.48s visual duration with minimal
bounce.

- **Entrances:** page content rises 12px on module change; card grids and gauge rows stagger in
  (≤0.05s per item, total ≤0.45s); the dashboard may orchestrate greeting → gauges → feed within
  0.6s.
- **State:** chips/tags, staged rows, and progress bars transition when state changes; numbers
  count via spring on mount and on change.
- **Structure:** master-detail rail collapse and panel entrances use the slow spring; wizard steps
  cross-fade+rise.
- **Feedback:** hover lift 1px; toasts slide+fade with a status edge.
- **Never:** decorative loops, heavy bounce/elastic, motion that delays an action, or animation
  during cell editing/scrolling of large grids (transform/opacity only there).
- `prefers-reduced-motion` collapses everything to opacity or nothing - enforced globally via
  MotionConfig and a CSS media query.

## 7. Do's and Don'ts

### Do:
- **Do** keep one vocabulary across modules; the same action looks the same everywhere.
- **Do** spend amber on one primary thing per screen plus the selection edge.
- **Do** put every identifier in mono and every figure column in tabular numerals.
- **Do** size regions to content; let one flexible element absorb slack.
- **Do** ship every interactive state, use skeletons over spinners, animate entrances once.
- **Do** reserve status hues for real state and render them as tags.

### Don't:
- **Don't** reintroduce Material greys, filled icons, pill chips, or tinted table-header fills.
- **Don't** sprawl - no lone full-width cards, no 2-character values in 250px columns, no
  stranded far-edge timestamps.
- **Don't** let motion decorate: no gradients, no bounce, no load choreography beyond the one
  entrance, nothing above ~0.6s.
- **Don't** let the viewport scroll sideways (`min-width: 0` on flex/grid children).
- **Don't** reach for a modal first; and never let Escape silently discard typed input.
- **Don't** render raw enums, machine strings, or unpluralized counts to a human.
