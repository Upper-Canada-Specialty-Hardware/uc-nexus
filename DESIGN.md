---
name: UC Nexus
description: Internal door-hardware fulfillment tool - one shared toolkit across import, PO, warehouse, shop, and shipping
colors:
  ink: "#212121"
  ink-hover: "#424242"
  ink-dark: "#e0e0e0"
  paper: "#ffffff"
  canvas: "#f5f5f5"
  table-header: "#eeeeee"
  shop-amber: "#ffca28"
  shop-amber-hover: "#ffb300"
  shop-amber-dark: "#ffd54f"
  canvas-dark: "#121212"
  paper-dark: "#1e1e1e"
  table-header-dark: "#2a2a2a"
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
    letterSpacing: "normal"
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
rounded:
  sm: "4px"
  md: "8px"
  lg: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.md}"
    padding: "6px 20px"
  button-primary-hover:
    backgroundColor: "{colors.ink-hover}"
    textColor: "{colors.paper}"
  button-secondary:
    backgroundColor: "{colors.shop-amber}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "6px 20px"
  button-secondary-hover:
    backgroundColor: "{colors.shop-amber-hover}"
    textColor: "{colors.ink}"
  button-outlined:
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "6px 20px"
  chip-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  chip-secondary:
    backgroundColor: "{colors.shop-amber}"
    textColor: "{colors.ink}"
  card:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.md}"
    padding: "16px"
  dialog:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.lg}"
  data-grid-header:
    backgroundColor: "{colors.table-header}"
    textColor: "{colors.ink}"
---

# Design System: UC Nexus

## 1. Overview

**Creative North Star: "One toolkit, many stations."**

UC Nexus is one continuous lifecycle - TITAN import, purchase orders, warehouse receiving, shop assembly, shipping - and every module draws from a single MUI theme: one font, one palette, one 8px radius, one component set. The visual language never changes station to station. What changes is density and rhythm, and only that. This is deliberate: an operator who learns the vocabulary at the PO station reads the warehouse station without relearning anything.

The character is efficient, precise, and industrial - a dependable shop tool, not a consumer app. Near-black ink carries structure and primary actions; a single Shop Amber accent marks the one thing that matters on a screen (the primary action, the current selection). Surfaces are flat and bordered, not shadowed. Type is a single humanist sans at a fixed rem scale. Nothing is decorative; every pixel either states information or affords an action. Components should feel solid and dependable - substantial, confident, built to take the same task performed dozens of times a day.

Density flexes by station, within the one language:

- **Dashboard (home):** the lowest density. Compact bordered stat tiles and a plain activity feed, sized to scan in one glance. Never a gradient hero-metric wall.
- **Operational tables (PO, warehouse):** the workhorse and the highest density. The data grid IS the screen - inline filter row, grouped and expandable rows, status chips, a tinted sticky header. It should feel like a full instrument panel, not a sparse report.
- **Guided wizard (import):** linear and calm. One step visible at a time via the MUI stepper; the operator makes one decision, then the next. Density drops so the current step is unambiguous.
- **Master-detail (shop assembly, shipping):** a compact list rail plus a wide detail pane. The rail collapses to give the detail the room - the space-efficiency law made structural.
- **Task modals (detail, edit, generate):** focused overlays for a single sub-task. Titled, dividered content, actions pinned to the bottom-right. Used when a task genuinely interrupts the flow, never as the first reach.

This system explicitly rejects consumer / playful SaaS gloss, sprawly layouts that waste horizontal space, legacy-ERP gray-on-gray clutter, and flashy or heavy motion. If a screen looks like it belongs on a marketing site, or if a region renders mostly empty, it is wrong.

**Key Characteristics:**
- One shared theme across every module; density varies, vocabulary does not.
- Near-black ink + a single Shop Amber accent; accent on roughly 10% of a screen, never decoration.
- Flat and bordered by default; elevation appears only as a response to state.
- One humanist sans (Source Sans 3) at a fixed rem scale, bold headings, no display faces in UI.
- Every region earns its space; the viewport never scrolls sideways.
- Full light and dark schemes, WCAG 2.1 AA.

## 2. Colors

A restrained near-neutral system carried by ink and gray, with exactly one saturated accent. Two full schemes (light and dark) via MUI CSS variables; the accent shifts one step lighter in dark mode for contrast.

### Primary
- **Ink** (`#212121`, dark scheme `#e0e0e0`): The structural color. Top app bar, primary buttons, primary chips, headings, and body text. In dark mode the roles invert - light-gray ink on near-black surfaces. Hover for ink buttons deepens to **Ink Soft** (`#424242`).

### Secondary
- **Shop Amber** (`#ffca28`, dark scheme `#ffd54f`): The single accent. Primary/default action buttons, the floating action button, selected toggle buttons, and current-selection highlights. Hover warms to `#ffb300`. This is the only saturated color in the system and it is spent carefully.

### Tertiary
- **Status set** (success `#2e7d32`, warning `#ed6c02`, error `#d32f2f`, info `#0288d1`): Semantic only. Relay connectivity, GP-sync state, validation, and PO status. Never used decoratively or for emphasis - a red here always means a real error.

### Neutral
- **Paper** (`#ffffff`, dark `#1e1e1e`): Cards, dialogs, table body, elevated surfaces.
- **Canvas** (`#f5f5f5`, dark `#121212`): The page background behind cards and panels - a second, cooler layer that separates content from chrome.
- **Table Header** (`#eeeeee`, dark `#2a2a2a`): The tinted sticky header row on data grids, distinguishing header from body without a border.
- **Hairlines** (`rgba(0,0,0,0.08-0.16)`, dark `rgba(255,255,255,0.12-0.24)`): Card and panel borders; these carry structure in place of shadow.

### Named Rules
**The One Accent Rule.** Shop Amber marks at most one primary thing per screen - the main action or the current selection. It appears on roughly 10% of a surface. If two amber elements compete, one is wrong. Its scarcity is what makes it read as "here."

**The Status-Only Color Rule.** Success/warning/error/info hues are reserved for real system state. Never reach for green because a thing is "good" or red for emphasis - color that can mean status must only ever mean status.

## 3. Typography

**Display / Body / Label Font:** Source Sans 3 Variable (with Source Sans 3, Helvetica Neue, Arial, sans-serif fallback)

**Character:** One humanist sans does the entire job - headings, buttons, labels, body, and dense table data. Humanist proportions keep long lists and numeric columns legible at small sizes; the variable weight axis supplies hierarchy without a second family. There is no display face anywhere in the UI.

### Hierarchy
- **Display** (700, 2.125rem / 34px, line-height 1.235): Page titles - "Purchase Orders", "Welcome back, [name]". One per screen.
- **Headline** (600, 1.5rem / 24px): Section headers inside a page or modal.
- **Title** (600, 1.25rem / 20px): Sub-section labels, stat-tile values, dialog titles.
- **Body** (400, 0.875rem / 14px, line-height 1.43): The workhorse - table cells, form fields, descriptions. Compact by default because most screens are data. Prose blocks cap at 65-75ch; tables run denser.
- **Label** (500, 0.75rem / 12px): Captions, stat-tile labels, helper text, breadcrumbs. Sentence case, not uppercase-tracked.

Buttons use body size at weight 600 with `text-transform: none` - shop tools spell words out, they don't SHOUT.

### Named Rules
**The Fixed-Scale Rule.** Type sizes are fixed rem values, never `clamp()`/fluid. Operators work at a consistent DPI across desktop screens; a heading that shrinks inside a sidebar reads as broken, not responsive.

**The One-Family Rule.** Source Sans 3 carries everything. No display or secondary family enters the UI - hierarchy comes from weight and size alone.

## 4. Elevation

Flat by default. AppBar, Card, and Paper all ship at elevation 0; structure is carried by hairline borders and the canvas/paper tonal split, not by drop shadows. Depth appears only as a response to state - a card raises a soft shadow on hover, a dialog floats above a scrim. This keeps dense screens quiet: a table of 200 rows with no resting shadows reads as one calm plane.

### Shadow Vocabulary
- **Card hover** (`box-shadow: 0 4px 12px rgba(0,0,0,0.08)`, dark `rgba(0,0,0,0.4)`): The only ambient shadow, and only on interactive cards, only on hover. Paired with a one-step border darken over a 0.2s transition.
- **Dialog** (MUI default dialog elevation): Structural - separates a focused task overlay from the scrimmed page beneath.

### Named Rules
**The Flat-At-Rest Rule.** Surfaces are flat when idle. A shadow is feedback, never decoration - if an element has a resting shadow for looks, remove it and let the border do the work.

## 5. Components

Buttons, cards, inputs, chips, and tables share one vocabulary across every module. Learn it once, read it everywhere. Every interactive component ships all of its states - default, hover, focus, active, disabled, loading - not half.

### Buttons
- **Shape:** Gently rounded (8px radius), padding `6px 20px`, weight 600, `text-transform: none`, no elevation.
- **Default / Secondary:** Shop Amber fill, ink text - the standard action ("Create PO"). Hover `#ffb300`.
- **Primary:** Ink fill, white text - structural or confirm actions. Hover `#424242`.
- **Outlined / Text:** Ink border and/or ink text on transparent - lower-priority actions ("Register in GP"), inline row actions.
- **Hover / Focus:** Background shift on hover; keep the MUI focus ring visible - never remove focus without a replacement.

### Chips
- **Style:** Weight 500. Primary chips are ink-on-white-text; secondary chips are Shop Amber with ink text.
- **State:** Used as status markers (PO status like "GP-Registered", "Draft") and compact filters. Status chips inherit meaning from the status color set, not from the accent.

### Cards / Containers
- **Corner Style:** 8px radius.
- **Background:** Paper (`#ffffff` / dark `#1e1e1e`) on the canvas layer.
- **Shadow Strategy:** Flat at rest; hover shadow only (see Elevation).
- **Border:** 1px hairline (`rgba(0,0,0,0.08)`), darkening to `0.16` on hover.
- **Internal Padding:** 16px (`spacing.md`); compact tiles use 12px vertical.
- **Stat tiles:** `flex: 1 1 0; min-width: 140px` so tiles share width evenly and stay compact - never a gradient hero-metric block.

### Inputs / Fields
- **Style:** MUI outlined, `size="small"`, 8px radius, hairline stroke. The floating label doubles as the placeholder for an empty field.
- **Focus:** Border shifts to the theme's focus treatment; label floats to the notch.
- **Error / Disabled:** Error uses the status-error hue on border and helper text; disabled dims stroke and text. Helper text sits below the field in Label type.

### Navigation
- **Top app bar:** Ink fill, white text, elevation 0 - a fixed anchor carrying the app name, mode toggle, notifications, and account.
- **Sidebar:** The module switcher; the active module reads via ink/amber emphasis, not a heavy fill.
- **Breadcrumbs:** 0.875rem, sentence case, for location within a module.

### Data Grid (signature component)
The operational surface for PO and warehouse. Borderless (`border: none`, 8px outer radius), with a tinted sticky header row (`#eeeeee` / dark `#2a2a2a`, weight 600) so the header reads without a divider line. Supports an inline filter row, grouped and expandable rows, and status chips inline. This is where density is highest and where the "every region earns its space" law is enforced hardest.

## 6. Do's and Don'ts

### Do:
- **Do** keep one shared vocabulary across modules - the same button, chip, input, and table styles everywhere. If "Create PO" is an amber button here, the equivalent action is an amber button there.
- **Do** spend Shop Amber on one thing per screen (the primary action or current selection), at roughly 10% coverage.
- **Do** keep surfaces flat and bordered at rest; let shadow appear only on hover or in dialogs.
- **Do** use fixed rem type sizes and the single Source Sans 3 family; build hierarchy from weight and size.
- **Do** size every region to its content and let one flexible element absorb the slack - in master-detail, collapse the list to a rail and give the detail the width.
- **Do** ship every interactive state (default, hover, focus, active, disabled, loading) and use skeletons for loading, not centered spinners.
- **Do** reserve success/warning/error/info strictly for real system state (relay, GP sync, validation).

### Don't:
- **Don't** make it look like consumer / playful SaaS - no rounded-everything, no colorful marketing gloss, no oversized empty hero sections.
- **Don't** sprawl - no short values stretched across empty columns, no panel sprawling vertically while starved horizontally. Every region must earn its space.
- **Don't** slide into legacy enterprise clutter - no gray-on-gray, cramped, inconsistent old-ERP density with no hierarchy.
- **Don't** add flashy or heavy motion - no gradients-as-decoration, no bounce or elastic, no orchestrated page-load sequences. Transitions are 150-250ms and convey state only.
- **Don't** let the viewport scroll sideways - a component may scroll inside its own bounded container, but the page never widens (put `min-width: 0` on flex/grid children).
- **Don't** build a gradient hero-metric tile; stat tiles stay compact, bordered, and flat.
- **Don't** reach for a modal first - exhaust inline and progressive-disclosure alternatives before overlaying the flow.
- **Don't** introduce a second font family or a display face into UI labels, buttons, or data.
