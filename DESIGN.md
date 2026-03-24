# Magnifier — Design System Audit & Guide

> Generated 2026-03-23 by design-system audit.

---

## Visual Audit Scores

| # | Dimension | Score | Notes |
|---|-----------|-------|-------|
| 1 | Color consistency | **5/10** | Good accent-color token system, but 3 hard-coded out-of-system colors |
| 2 | Typography hierarchy | **4/10** | 11 distinct font-size values, mixed px/rem/clamp, `!important` overrides |
| 3 | Spacing rhythm | **5/10** | No 4/8px grid — arbitrary values (9px, 26px padding etc.) |
| 4 | Component consistency | **6/10** | `.btn` pattern is consistent; `.filter-btn` is defined twice with conflicts |
| 5 | Responsive behavior | **5/10** | Single breakpoints per page; camera/remote pages have no responsive rules |
| 6 | Dark mode | **N/A** | App is intentionally dark-only for accessibility |
| 7 | Animation | **7/10** | Purposeful, consistent 0.3s ease transitions and glow hover states |
| 8 | Accessibility | **8/10** | Excellent forced-colors, focus-visible, aria-labels throughout |
| 9 | Information density | **7/10** | Camera pages are clean; home page is well-structured |
| 10 | Polish | **7/10** | Glow effects, tutorial highlight ring, and hover states are high quality |

**Overall: 61/90 (68%)**

---

## Critical Issues (fix these)

### C1 — `.filter-btn` defined twice with conflicting rules
**File:** `static/css/samples.css:97` and `:269`
The first block sets `font-size: 28px !important; border-radius: 36px; min-height: 65px`.
The second block (line 269) overrides it with `font-size: 16px; padding: 10px 20px; white-space: nowrap` — which makes the `!important` on line 107 a lie.

**Fix:** Merge into a single `.filter-btn` rule. Remove `!important`.

---

### C2 — `#remote-status-badge` uses `#7CFC00` (hard-coded lawn green)
**File:** `static/css/samples.css:572`
This is the only green in the entire app and ignores the user's chosen accent color.

```css
/* Before */
color: #7CFC00;
border: 1px solid #7CFC00;

/* After */
color: var(--accent-color);
border: 1px solid var(--accent-color);
```

---

### C3 — Custom slider uses `#0078ff` (hard-coded blue)
**File:** `static/css/samples.css:203, 214, 226`
The hue/brightness/contrast/saturation sliders use a bright blue that clashes with the accent system.

```css
/* Before */
accent-color: #0078ff;
background: #0078ff;

/* After */
accent-color: var(--accent-color);
background: var(--accent-color);
```

---

### C4 — Zoom slider webkit thumb uses `#ffd900` instead of `#ffd700`
**File:** `static/css/samples.css:333`
Off by 2 from the accent color — almost certainly a typo. Firefox already uses `var(--accent-color)`.

```css
/* Before */
background: #ffd900;

/* After */
background: var(--accent-color);
```

---

## High Issues

### H1 — Typography: no base font-size set, 11 distinct sizes in use
**File:** `static/css/samples.css`, `static/css/styles.css`

The app uses: 12px, 14px, 15px, 16px, 18px, 24px, 28px, 34px, 36px, 1rem, 1.5rem, and `clamp(18px,5vw,28px)` — no single source of truth.

**Proposed scale** (see `design-tokens.json → typography.font-size`):
| Token | Value | Usage |
|-------|-------|-------|
| `--fs-xs`  | 12px | Captions, labels |
| `--fs-sm`  | 14px | Badges, secondary |
| `--fs-md`  | 18px | Nav, body |
| `--fs-lg`  | 24px | Control buttons |
| `--fs-xl`  | 28px | Start buttons, filter buttons |
| `--fs-2xl` | 34px | Zoom buttons |
| `--fs-3xl` | 36px | Page h1 |

---

### H2 — Border-radius: 7 distinct values with no pattern
**File:** `static/css/samples.css`

Current values: 8px, 10px, 12px, 14px, 15px, 20px, 36px, 50%

**Proposed scale:**
| Token | Value | Usage |
|-------|-------|-------|
| `--radius-sm`   | 8px  | Buttons, badges |
| `--radius-md`   | 12px | Panels, cards |
| `--radius-lg`   | 20px | Tutorial box |
| `--radius-pill` | 36px | Filter buttons, slider columns |
| `--radius-full` | 50%  | Circular buttons, thumbs |

10px, 14px, 15px are orphans — consolidate to nearest token value.

---

### H3 — Duplicate `--accent-color` token declaration
**Files:** `static/css/styles.css:1` and `static/css/samples.css:1`

Both files independently declare `:root { --accent-color: #ffd700; }`. If one is ever updated, they drift.

**Fix:** Extract shared tokens into a `static/css/tokens.css` imported first by both pages, or simply keep the declaration only in `styles.css` (since `samples.css` is only used on pages that already include it).

---

## Medium Issues

### M1 — Spacing uses arbitrary values (no 4/8px grid)
Observed: `gap: 150px` (zoom container), `padding: 9px 12px` (filter-btn), `margin-top: 5px` (custom-filter).
Not critical for this app's audience, but makes future edits unpredictable.

### M2 — `z-index` values span 200–5500 with no documented layers
`z-index: 200` (back-btn) to `z-index: 5500` (tutorial highlight) — see `design-tokens.json → z-index` for the full map.

### M3 — `#back-btn` overrides `.btn` without `btn` class override
`#back-btn` sets `border: none` but `.btn` sets `border: none` too — fine.
However `#back-btn` doesn't inherit the `btn` class in the HTML (`id="back-btn"` plus `class="btn"`), so this is actually fine. Minor note.

### M4 — `.custom-slider-col input[type=range]::-webkit-slider-thumb:hover` applies `transform: scale(1.2)` but the `transition` property is missing
The zoom happens instantly. Add `transition: transform 0.18s ease` to the thumb.

---

## What's Working Well

- **Accent color system** — CSS custom properties with RGB split for `rgba()` usage is elegant and the user-customisable theme is well-implemented
- **Forced-colors / high-contrast** — Both CSS files have comprehensive `@media (forced-colors: active)` blocks. This is above average for web apps
- **Focus states** — Every interactive element has a `focus-visible` outline. No focus traps observed
- **Tutorial highlight ring** — The `box-shadow` glow on the tutorial overlay element is a polished touch
- **Transition consistency** — `0.3s ease` and `0.18s ease` are used intentionally; fast for micro-interactions, default for UI feedback
- **Binary frame protocol metadata** — Not a design issue, but shows thoughtful systems thinking that carries through to the UI

---

## Design Token Usage (CSS variables)

These are already in place and should be expanded:

```css
:root {
  /* Accent — user-overridable */
  --accent-color:     #ffd700;
  --accent-color-rgb: 255, 215, 0;

  /* Proposed additions */
  --fs-xs:  12px;
  --fs-sm:  14px;
  --fs-md:  18px;
  --fs-lg:  24px;
  --fs-xl:  28px;
  --fs-2xl: 34px;
  --fs-3xl: 36px;

  --radius-sm:   8px;
  --radius-md:   12px;
  --radius-lg:   20px;
  --radius-pill: 36px;
  --radius-full: 50%;

  --transition-fast:    0.18s ease;
  --transition-default: 0.3s ease;
}
```

Full token definitions: `design-tokens.json`
Interactive preview: `design-preview.html`
