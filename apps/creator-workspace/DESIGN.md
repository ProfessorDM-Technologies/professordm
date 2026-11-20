# Creator Workspace design system

Source of truth: *ProfessorDM Brand Style Guide v1* (sponsor, Oct 2026). This file turns it into rules for the
Creator Workspace UI. The consumer app is out of scope for now.

## Idea

A calm, credible desk where a creator turns questions into answers. The brand story is
**question → knowledge → value**, and the workspace follows it: cyan marks questions, teal marks progress and
done work, gold marks money and appears only on the Bank page. Navy and white carry the rest of the screen.

Motion verb: **settle**. Things move a few pixels and fade in on a short ease, like a card put down on a desk. No
bounce, no glow pulses, no gaming or crypto feel (brand guide §05: "selective glow").

## Palette (brand §03, 50 / 25 / 15 / 10 balance)

| Token | Light | Dark | Role |
|---|---|---|---|
| `surface` | `#F5F8F9` | `#0E1B24` | Page ground |
| `panel` | `#FFFFFF` | `#152936` | Cards, inputs, menus |
| `ink` | `#12232E` Midnight Navy | `#E8EFF3` | Body text |
| `heading` | `#043B65` Professor Navy | `#FFFFFF` | Headings |
| `muted` | `#4A5D6B` | `#A3B5C2` | Secondary text (AA on surface and panel) |
| `border` | `#DCE5EA` | `#26404F` | Hairlines |
| `accent` | `#043B65` Professor Navy | `#0DBED6` Electric Cyan | Primary buttons, active states |
| `accent-strong` | `#032C4C` | `#6FDCEB` | Hover, link text |
| `on-accent` | `#FFFFFF` | `#0B1A22` | Text on accent |
| `tint` | `#E3F1EA` | `#163A38` | Selected and soft-accent fills |
| `teal` | `#17A770` | `#17A770` | Progress dots, success marks (never small text on white: 3:1) |
| `cyan` | `#0DBED6` | `#0DBED6` | Questions, AI drafts |
| `gold` | `#DB8424` | `#DB8424` | Money only (Bank page), at most 10% of any screen |
| `sage` | `#D2E1BE` | `#D2E1BE` | Human and learning content, sparingly |
| `danger` / `success` | red and green families | tuned for dark | Alerts; always paired with text |

Colours live as CSS variables on `<html>` (`:root` for light, `[data-theme="dark"]` for dark) and reach Tailwind
through `@theme inline`, so every `bg-pdm-*` / `text-pdm-*` class switches theme with no per-component work.
Hard-coded `bg-white`, `stone-*`, `red-*` and `green-*` classes are not allowed in components.

## Type (brand §04)

- **Headings:** Montserrat 600 / 700 / 800, self-hosted with `next/font/google`. Tracking `-0.02em` on display sizes.
- **Body:** Aptos, then the platform UI face (`Segoe UI Variable`, `-apple-system`, `system-ui`). Aptos has no web
  licence we can self-host, and the guide asks us not to add families, so devices without Aptos use the system
  sans instead of a third webfont.
- Body is 16 px with 1.5 leading. Labels and data are 12 to 14 px semibold.

## Shape and depth

- Cards and panels: 16 px radius (`rounded-2xl`), echoing speech bubbles (brand §05 "rounded containers").
- Buttons, chips, the nav island: full pill.
- One soft shadow token for floating UI. Cards on the page stay flat with a hairline border.

## Layout

```
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ [logo]          ( Bank  Incoming  Inbox  Sent  Mod  Knowledge  Profile )  (◐ R) │  ← fixed, never scrolls
 │ fade scrim ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
 │                 ┌──────────── max 64rem column ───────────┐               │
 │                 │ H1 Montserrat                           │               │
 │                 │ cards …                                 │               │
 └──────────────────────────────────────────────────────────────────────────┘
```

- **Logo:** fixed top-left with no background: the icon mark next to the vector wordmark. It does not move on scroll.
- **Nav island (xl, 1280 px and up):** fixed, centred, glass pill (`backdrop-filter: blur(16px) saturate(160%)` over a 72%
  panel tint, a hairline border and a soft shadow). The current page gets a solid panel pill with a teal dot.
- **Account island:** fixed top-right glass pill with the theme toggle and an account popover (role, sign out).
- **Below xl:** the logo and account row stay at the top. The nav island docks at the bottom as a glass pill with the
  five mobile items, inside the safe area. Seven items do not fit a 390 px top bar, and the bottom is where thumbs are.
- A fixed gradient scrim under the top row, matching the ground colour, stops scrolled text from colliding with the
  logo. The logo itself still has no background.
- Glass is used **only** on floating chrome (the nav and account islands). Content cards are solid, for legibility.

## Logo (brand §02)

- The wordmark is traced to true vectors from the sponsor PNG, filled with the exact brand hexes
  (`#043B65` Professor, `#17A770` DM): `public/brand/wordmark-light.svg`.
- The icon mark is the sponsor illustration, with the white background removed by an edge flood fill so its
  highlights survive. It stays a high-resolution transparent PNG, because tracing the glows and gradients distorts
  the art, which the guide forbids.
- **Dark mode:** navy "Professor" disappears on a navy ground, so `wordmark-dark.svg` sets it in white and keeps
  "DM" teal. This is the one recolour, and it **needs sponsor sign-off** (guide §02: "do not recolour individual parts").
- Clear space: at least the height of the "D" on every side.

## Theme

- Light is the default for everyone and does not follow the OS.
- The choice is saved in a `pdm-theme` cookie and read by the root layout, so the server renders the right theme with
  no flash.

## Motion

- One easing curve: `cubic-bezier(0.2, 0.7, 0.2, 1)`; 160 ms for controls, 240 ms for cards.
- Hover on primary targets (nav items, cards, buttons): a 1 to 2 px lift plus a fill or border change. Press is
  `scale(0.98)`.
- The page stays still at rest, and that's deliberate: this is a work tool. Only the "drafting" status dot pulses.
- `prefers-reduced-motion`: no transforms or transitions beyond opacity.

## Accessibility

- Skip link first in tab order; visible 2 px focus ring in `accent` with offset on every control.
- AA contrast for all text in both themes; status is never colour alone.
- Tap targets ≥ 44 px; no horizontal scroll at 390 px.
