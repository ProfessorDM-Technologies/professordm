# Creator Workspace Brand Refresh — Spec

Status: Draft for review · Owner: Ritvik (Creator App & Transaction Workflow) · Date: 2026-11-11
Scope: `apps/creator-workspace` only. The consumer app (`apps/consumer`) follows in a separate spec once this one is signed off.

Source of truth: *ProfessorDM Technologies Inc. Brand Style Guide v1* (Oct 2026) and the two logo PNGs in the brand Drive folder.

> **Hard rule: no git by the implementer.** Whoever implements this spec (human or AI agent) never runs `git commit`, `git push` or any other git command, and never pushes to GitHub. Work ships in small parts, incremental commits. At the end of each part, the implementer stops and gives Ritvik a one-line commit message. Ritvik makes every commit himself, and pushes to GitHub manually at the end.

## 1. Why

The creator workspace currently uses an amber/stone palette and system fonts, and renders "ProfessorDM" as plain semibold text. None of that matches the brand guide:

| Brand guide says | Today |
|---|---|
| Navy + white do ~50% of the visual work; teal/cyan ~25%; gold ≤10% accent | Amber (`#b45309`) is the primary action and active colour everywhere |
| Montserrat headings, Aptos body | `ui-sans-serif, system-ui …` |
| Never recreate the wordmark in another typeface | Header writes "ProfessorDM" in the body font |
| Rounded containers echo speech bubbles; selective cyan/teal glow; clean line icons | Generic stone cards, no icons |

## 2. Decisions (agreed with Ritvik, 2026-11-11)

| # | Decision |
|---|---|
| D1 | **Navigation moves to the top.** The left sidebar is removed. Desktop gets a sticky **light frosted-glass** top bar. |
| D2 | A faint fixed **brand mist** backdrop (soft cyan / teal / navy blooms) sits behind the top of every page, so the glass has something to blur. Content cards stay solid white. |
| D3 | **Mobile (< 768px):** a slim glass top bar (icon + account) and a **glass bottom tab bar** with the same 5 items as today. |
| D4 | **Navy is the action colour** (primary buttons, active nav, focus). Teal = success / sent / done. Cyan = AI and question states. Gold = money only. |
| D5 | **Logo:** icon mark in the nav, full stacked logo on login and 404, icon as favicon. The wordmark is never re-typed. |
| D6 | **Fonts:** Montserrat for headings and nav; body stack `Aptos, Inter, system-ui`. Both web fonts are self-hosted through `next/font/google` (no runtime Google requests, $0). |
| D7 | Consumer app is **out of scope** here. |

## 3. Design tokens

All tokens live in `apps/creator-workspace/src/app/globals.css` under `@theme`. They are named for their role, not their hue, so components never hard-code brand hex values.

### 3.1 Colour

| Token | Hex | Role | Contrast (measured) |
|---|---|---|---|
| `pdm-canvas` | `#F5F8FA` | Page background below the mist | — |
| `pdm-card` | `#FFFFFF` | Cards, inputs, menus | — |
| `pdm-ink` | `#12232E` | Body text (Midnight Navy) | 16.1 on white |
| `pdm-heading` | `#043B65` | H1/H2 (Professor Navy) | 11.6 on white |
| `pdm-muted` | `#4A5B6A` | Secondary text | 7.0 on white, 6.0 on primary-tint |
| `pdm-border` | `#DCE4EB` | Hairline card dividers (decorative) | — |
| `pdm-border-strong` | `#788A99` | Input and checkbox borders | ≥ 3.0 on white (non-text) |
| `pdm-primary` | `#043B65` | Primary buttons, active nav, focus ring | white text 11.6 |
| `pdm-primary-hover` | `#032B4A` | Primary hover/pressed | white text 14.5 |
| `pdm-primary-tint` | `#E8EEF4` | Selected rows, active count badges | navy text 9.9 |
| `pdm-success` | `#17A770` | Brand teal: fills, dots, icons only | — |
| `pdm-success-text` | `#0E7A51` | Teal text | 5.4 on white, 4.7 on tint |
| `pdm-success-tint` | `#E4F4EC` | Sent / delivered chip background | — |
| `pdm-ai` | `#0DBED6` | Brand cyan: fills, dots, glow only | — |
| `pdm-ai-text` | `#08707F` | AI-state text | 5.8 on white, 5.1 on tint |
| `pdm-ai-tint` | `#E0F5F8` | "AI is drafting", AI draft panel | — |
| `pdm-money` | `#DB8424` | Brand gold: fills, icons only | — |
| `pdm-money-text` | `#8F530F` | Money text | 6.2 on white, 5.4 on tint |
| `pdm-money-tint` | `#FBEFDF` | Bank tiles, "Paid" chip | — |
| `pdm-human` | `#EEF4E6` | Soft Sage tint: the creator's own words (the edited answer, sent replies in a thread) | ink 14.3 |
| `pdm-danger-text` | `#B42318` | Errors, safety flags | 6.6 on white, 6.0 on tint |
| `pdm-danger-tint` | `#FEF1F0` | Error banners, flag chips | — |
| `pdm-danger-border` | `#F5C2BD` | Error banner border (decorative) | — |

Rules:
- The raw brand teal, cyan and gold **fail** WCAG AA as text or under white text (3.1, 2.2, 2.9). They appear only as fills, dots, icons and glow. Text uses the `-text` shades.
- Red is not a brand colour. It is kept only for errors and safety states, because those need a universally understood signal. Every chip still carries a text label, so colour is never the only signal.
- Soft Sage marks *human* content (the brand's "people, learning" meaning). It visually separates the creator's voice from the AI draft (cyan), which reinforces the "Creator is Boss" rule.

### 3.2 Typography

| Role | Face | Size / line-height | Weight |
|---|---|---|---|
| H1 page title | Montserrat | 28/34 (`text-[1.75rem]`), −0.01em | 700 |
| H2 section | Montserrat | 18/26 | 600 |
| Nav items, tabs | Montserrat | 14/20 | 600 |
| Body | Aptos → Inter | 16/24 | 400 |
| Labels, data, chip text | Aptos → Inter | 14/20 or 12/16 | 600 |
| Captions | Aptos → Inter | 12/16 | 400 |

- Sentence case everywhere. No all-caps eyebrow labels.
- Long text (questions, answers, drafts) is capped at about 70ch.
- Tokens: `--font-display` (Montserrat) and `--font-sans` (Aptos stack). The `next/font` CSS variables are wired in the root layout.

### 3.3 Shape, depth, motion

- **Radius follows hierarchy:** glass bar, nav pills and chips use `rounded-full`. Cards and panels use `rounded-xl` (12px). Buttons and inputs use `rounded-lg` (8px). Nothing uses `rounded-2xl`.
- **Depth:** cards have a border and **no shadow**. Only the glass bars, the account menu and the send-confirm dialog get a shadow (`shadow-[0_8px_24px_-12px_rgb(4_59_101/0.25)]`).
- **Motion:** nav pills and buttons change colour with a 150ms `transition-colors` (`motion-safe:` only). The existing drafting-dot pulse stays. No page-load, slide or card-hover animations.

## 4. Layout

### 4.1 Desktop and tablet (≥ 768px)

```
░░▒ cyan bloom ▒░░                      ░▒ teal bloom ▒░   ← fixed mist, top ~480px, fades to canvas
╭──────────────────────────────────────────────────────────────╮  sticky top-0, z-40
│ [▣] Creator Workspace │ Bank  Incoming (Inbox) Sent  Moderation  Knowledge  Profile │ [RG ▾] │
╰──────────────────────────────────────────────────────────────╯  frosted: white/70, blur-xl, saturate-150
        max-w-6xl content, left-aligned
        Inbox                                      ← Montserrat 700, navy
        ─ Inbox 4 ─  Sent 12   Moderation 1        ← queue tabs
        ┌────────────────────────────────────────┐
        │ @plantmom          ◔ AI is drafting     │ ← white card, hairline border, no shadow
        └────────────────────────────────────────┘
```

- `[▣]`: the icon mark on a 36px white rounded-lg tile with a 1px border. The source PNGs have opaque white backgrounds, and the guide prefers white behind the logo. The tile provides that, and its padding provides clear space.
- The "Creator Workspace" label is plain body text, not part of the logo. It shows at `lg` (≥ 1024px) only, which keeps 7 items plus the account button on one row at 768px.
- **Active item:** a solid white pill with navy semibold text, a `ring-1 ring-pdm-primary/10` and a small shadow. It looks lifted out of the glass. This is the one memorable element. Inactive items are `pdm-muted` and turn navy on hover.
- The Inbox nav item shows the unanswered count as a small navy badge when the count is above zero.

### 4.2 Mobile (< 768px)

- Top: a 56px glass bar with the icon tile on the left and the compact account menu on the right.
- Bottom: a glass tab bar with Bank, Incoming, Inbox, Moderation and Profile (the current `mobile: true` set). Each item has a 20px line icon over a 12px label, a 48px minimum target and `pb-[env(safe-area-inset-bottom)]`. The active item shows a navy icon and label plus a 3px navy indicator above.
- Sent and Knowledge stay reachable as they are today: through the queue tabs (Sent) and the account menu (Knowledge link added there).

### 4.3 Glass implementation

```
.glass {  bg-white/70  backdrop-blur-xl  backdrop-saturate-150
          border border-white/60  ring-1 ring-pdm-heading/5
          shadow-[inset_0_1px_0_rgb(255_255_255/0.7),0_8px_24px_-12px_rgb(4_59_101/0.25)] }
@supports not (backdrop-filter: blur(1px))  → bg-white/95
@media (prefers-reduced-transparency: reduce) → bg-white (solid), no blur
@media (forced-colors: active) → border: 1px solid CanvasText
```

The mist is a single fixed `div` (`aria-hidden`, `pointer-events-none`, `-z-10`) with three radial gradients:

- cyan `#0DBED6` at 14% opacity, top-left
- teal `#17A770` at 10% opacity, top-right
- navy `#043B65` at 6% opacity, top-centre

It fades to `pdm-canvas` by about 480px. It is static and not animated.

## 5. Logo assets

| File (in `apps/creator-workspace/`) | Source | Use |
|---|---|---|
| `public/brand/pdm-icon.png` | Square logo, cropped to its content box plus clear-space padding (≈ 1100 × 860) | Nav tile (rendered at 36px tall), mobile top bar |
| `public/brand/pdm-logo.png` | Full stacked logo (620 × 490 today) | Login (rendered at about 200px wide), 404 |
| `src/app/icon.png` | Square logo, 512 × 512 | Favicon via Next.js file convention |

**Clarity:** the full logo is 620 × 490, which is soft at 2× on retina. Before Task 2 it must be upscaled 4× **without editing content** (Real-ESRGAN `realesrgan-x4plus-anime` or Upscayl with the same model), then downsampled to 1240 × 980. *
Ask to Kristin:* an SVG or high-resolution transparent master, plus a horizontal lockup. Both PNGs have opaque white backgrounds, so they must always sit on white (the tile handles this).

Rendering always uses `next/image` with explicit `width`/`height`, never CSS stretching. `alt="ProfessorDM"` on the full logo. The nav icon sits inside a link with `aria-label="ProfessorDM Creator Workspace home"`, and the image's own `alt` is empty.

## 6. Component changes (creator workspace)

| Area | Change |
|---|---|
| Root layout | Load the fonts, set `bg-pdm-canvas text-pdm-ink font-sans`, add `BrandMist` |
| Workspace layout | Remove the `<aside>`. Add `TopBar` (glass) and keep `WorkspaceNav variant="bottom"` (glass). Main becomes `max-w-6xl`. |
| `WorkspaceNav` | New `variant="top"` with pills. Nav data and `isActive` move to `lib/nav.ts`. |
| Buttons | One `buttonClass(variant, size)` helper (`primary`, `secondary`, `ghost`, `danger`). It replaces about 15 hand-rolled class strings. |
| `StatusChip` | Tones map to brand meaning: `progress` → AI cyan tint, `accent` → primary tint, `danger` → danger tint, `neutral` → canvas plus border. Add a `success` tone for delivered/sent. |
| Queue tabs | Montserrat 600; navy underline on the active tab; counts in `pdm-primary-tint` |
| Question card / message row | White card, `rounded-xl`, no shadow. Follower message on white; creator's sent reply on `pdm-human`. |
| Answer composer | AI draft panel on `pdm-ai-tint` with an "AI draft" label. The creator's editable answer sits on a white field, which becomes `pdm-human` once the creator edits it. Send is navy primary. The success toast uses `pdm-success`. |
| Bank | Balance tiles use the `pdm-money-*` tokens (gold appears only here). Withdraw is navy primary. |
| Login / 404 | Full logo centred above the form on canvas plus mist; card `rounded-xl` white |
| Loading skeletons | `bg-pdm-border/60` instead of `stone-200` |

Copy changes are out of scope, except for label text the restyle requires.

## 7. Quality bar

- WCAG 2.1 AA. Every text/background token pair in §3.1 passes 4.5:1, and inputs pass 3:1. A unit test parses `globals.css` to enforce this.
- No legacy palette. A unit test fails if any `.tsx` under `src/` uses `stone-`, `amber-`, `red-`, `green-`, `gray-`, `black` or the retired `pdm-accent*` / `pdm-tint` / `pdm-surface` classes.
- Keyboard: skip link, visible focus (`outline-2 outline-pdm-primary outline-offset-2`), logical tab order through the top bar, and `aria-current="page"` on the active nav item.
- Responsive at 320, 768, 1024 and 1440 px, with no horizontal scroll and nothing hidden under the bottom bar (`pb-24` on mobile main).
- `prefers-reduced-motion`, `prefers-reduced-transparency` and `forced-colors` are all respected.
- `pnpm --filter @professordm/creator-workspace lint typecheck test build` passes.

## 8. Out of scope / follow-ups

- Consumer app restyle: a separate spec reusing these tokens. Lift `@theme` into a shared `packages/brand` then.
- Dark mode (not covered by brand guide v1).
- Vector logo and horizontal lockup (asset request to Kristin).
- Brand guide v1 says it will be updated "to incorporate finalized interface design". This spec is a candidate input for that update.
