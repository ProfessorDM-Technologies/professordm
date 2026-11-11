# Creator Workspace Brand Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Also load `frontend-ui-engineering` and `frontend-design:frontend-design` before any UI task.

**Goal:** Restyle `apps/creator-workspace` to the ProfessorDM Brand Style Guide v1, with a frosted-glass top navigation, brand tokens, the Montserrat/Aptos type system and the real logo.

**Architecture:** Role-named colour tokens in Tailwind v4 `@theme` (`globals.css`) are the only place brand hex values live. Task 1 adds the new tokens and temporarily **aliases the old `pdm-accent*`/`pdm-tint`/`pdm-surface` names to them**, so every commit renders on-brand and nothing breaks mid-migration. Tasks 4–7 migrate components file by file. Task 8 deletes the aliases and adds a guard test.

**Tech Stack:** Next.js 16.4 (App Router; read `apps/creator-workspace/node_modules/next/dist/docs/` before using any Next API), React 19, Tailwind CSS 4.3, `next/font/google`, `next/image`, Vitest 5 (node env, `src/**/*.test.ts`).

> **HARD RULE:** the implementer never commits or pushes. Each task ends at a STOP with a one-line commit message for Ritvik. Ritvik commits, and pushes manually at the end. See Global Constraints.

**Spec:** `docs/plans/creator-brand-refresh-spec.md`. Read it first; token values, sizes and rules are defined there and are not repeated here.

## Global Constraints

- **HARD RULE: never commit, never push.** Never run `git commit`, `git push` or any other git command (not even `git status`/`diff`), and never push to GitHub by any route (`gh`, the API, etc.). Each task ends with **STOP**: report the files changed and hand Ritvik the one-line commit message given in the task. Ritvik makes every commit himself, and pushes to GitHub manually at the end of the branch. This rule overrides any "Commit" step in a sub-skill such as superpowers:executing-plans or subagent-driven-development.
- Scope is `apps/creator-workspace` only. Do not touch `apps/consumer`.
- No new runtime dependencies. Icons are inline SVG. The account menu uses native `<details>`.
- Never hard-code a brand hex in a `.tsx` file. Use `pdm-*` tokens only.
- Raw `pdm-success`, `pdm-ai` and `pdm-money` are never used for text or under white text. Use the `-text` variants.
- Never re-type "ProfessorDM" as a logo. Use `<BrandMark>` / `<BrandLogo>` (Task 2).
- Sentence case; no all-caps labels; no `rounded-2xl`; no shadows on cards.
- Do not change business logic, server actions, queries or copy beyond what a restyle requires.
- Verify per task: `pnpm --filter @professordm/creator-workspace test`, `… lint` and `… typecheck` are all green.

## Review Focus

1. **Content hidden under the glass bars.** The sticky top bar and the mobile bottom bar overlap content. Expected: anchors (`#main`, the skip link) scroll so the target sits below the top bar (`scroll-padding-top` on `html`), and the last item on a mobile page clears the bottom bar.
2. **Browsers without `backdrop-filter`, or with reduced transparency on.** Expected: the bar is near-solid white and nav text keeps ≥ 4.5:1 contrast. Owned by Task 3, verified by the CSS checks in Task 8.
3. **Long display names or 3-digit counts in the top bar at 768px.** Expected: the name truncates, nav items never wrap to a second row, and there is no horizontal scroll. Checked in Task 8 QA at 768px with a 40-character name and Inbox count 120.
4. **Keyboard-only use of the account `<details>` menu.** Expected: Enter/Space opens it, Tab reaches Knowledge and Sign out, Escape closes it and returns focus to the summary. Owned by Task 3.
5. **Logo on non-white surfaces.** Expected: the logo PNGs (opaque white backgrounds) never sit directly on the mist or canvas, only inside a white tile or card. Owned by Task 2.

---

### Task 1: Brand tokens, fonts and the contrast test

**Files:**
- Modify: `apps/creator-workspace/src/app/globals.css`
- Modify: `apps/creator-workspace/src/app/layout.tsx`
- Create: `apps/creator-workspace/src/lib/brand/contrast.ts`
- Test: `apps/creator-workspace/src/lib/brand/contrast.test.ts`

**Interfaces:**
- Produces: `contrastRatio(foreground: string, background: string): number` (hex `#RRGGBB`). `readThemeTokens(css: string): Record<string, string>` maps `--color-pdm-*` names (without the `--color-` prefix) to hex values.
- Produces Tailwind classes: every token in spec §3.1 (`bg-pdm-canvas`, `text-pdm-ai-text`, …) plus `font-display` and `font-sans`.

- [ ] **Step 1: Write the failing test** `contrast.test.ts`

```ts
import { readFileSync } from "node:fs";
const css = readFileSync(new URL("../../app/globals.css", import.meta.url), "utf8");
const t = readThemeTokens(css);

test("contrastRatio matches WCAG reference values", () => {
  expect(contrastRatio("#FFFFFF", "#000000")).toBeCloseTo(21, 1);
  expect(contrastRatio("#043B65", "#FFFFFF")).toBeCloseTo(11.55, 1);
});

test.each([
  ["pdm-ink", "pdm-card"], ["pdm-ink", "pdm-canvas"], ["pdm-heading", "pdm-canvas"],
  ["pdm-muted", "pdm-card"], ["pdm-muted", "pdm-canvas"], ["pdm-muted", "pdm-primary-tint"],
  ["pdm-primary", "pdm-primary-tint"], ["pdm-success-text", "pdm-success-tint"],
  ["pdm-ai-text", "pdm-ai-tint"], ["pdm-money-text", "pdm-money-tint"],
  ["pdm-danger-text", "pdm-danger-tint"], ["pdm-ink", "pdm-human"],
])("%s on %s passes AA text (4.5:1)", (fg, bg) => {
  expect(contrastRatio(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5);
});

test("white on primary and primary-hover passes AA", () => {
  expect(contrastRatio("#FFFFFF", t["pdm-primary"])).toBeGreaterThanOrEqual(4.5);
  expect(contrastRatio("#FFFFFF", t["pdm-primary-hover"])).toBeGreaterThanOrEqual(4.5);
});

test("input border passes AA non-text (3:1)", () => {
  expect(contrastRatio(t["pdm-border-strong"], t["pdm-card"])).toBeGreaterThanOrEqual(3);
});

test("brand accents are pinned to the style guide", () => {
  expect(t["pdm-heading"]).toBe("#043B65");
  expect(t["pdm-ink"]).toBe("#12232E");
  expect(t["pdm-success"]).toBe("#17A770");
  expect(t["pdm-ai"]).toBe("#0DBED6");
  expect(t["pdm-money"]).toBe("#DB8424");
});
```

- [ ] **Step 2: Run** `pnpm --filter @professordm/creator-workspace test -- contrast`. Expected: FAIL (module not found).
- [ ] **Step 3: Implement `contrast.ts`** using the WCAG 2.1 relative-luminance formula. `readThemeTokens` regex-matches `--color-(pdm-[a-z-]+):\s*(#[0-9a-fA-F]{6})`.
- [ ] **Step 4: Rewrite `@theme` in `globals.css`** with every token and hex in spec §3.1, uppercase hex. Add **temporary aliases**, each marked `/* legacy alias — removed in Task 8 */`:
  - `pdm-accent` and `pdm-accent-strong` → `var(--color-pdm-primary)`
  - `pdm-tint` → `var(--color-pdm-primary-tint)`
  - `pdm-surface` → `var(--color-pdm-canvas)`

  Set `--font-sans: Aptos, var(--font-inter), ui-sans-serif, system-ui, sans-serif` (Aptos first, so machines that have it use it). Set `--font-display: var(--font-montserrat), ui-sans-serif, system-ui, sans-serif`. Add to the base layer:
  - `html { scroll-padding-top: 5rem }`
  - `h1, h2, h3 { font-family: var(--font-display); color: var(--color-pdm-heading) }`
  - `:focus-visible { outline: 2px solid var(--color-pdm-primary); outline-offset: 2px }`
- [ ] **Step 5: Load the fonts in `app/layout.tsx`.** Use `Montserrat({ subsets: ["latin"], weight: ["600", "700"], variable: "--font-montserrat", display: "swap" })` and `Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" })`. Put both `.variable` classes on `<html>`. The body className becomes `bg-pdm-canvas font-sans text-pdm-ink antialiased`.
- [ ] **Step 6: Run** test, lint and typecheck. Expected: all PASS. Run `pnpm --filter @professordm/creator-workspace dev` and open `/login`: Montserrat heading, navy instead of amber.
- [ ] **Step 7: STOP.** Commit message: `Add ProfessorDM brand tokens, Montserrat/Aptos fonts and a contrast test`

---

### Task 2: Logo assets and brand mark components

**Prerequisite (Ritvik):** the clarified full logo (spec §5, 4× upscaled then downsampled to 1240 × 980) is saved as `apps/creator-workspace/public/brand/pdm-logo.png`. If it is missing, STOP and ask; do not upscale it yourself.

**Files:**
- Create: `apps/creator-workspace/public/brand/pdm-icon.png`: from the square logo, centre-cropped to 1254 × 880 with `sips -c 880 1254`, then `sips -Z 512`
- Create: `apps/creator-workspace/src/app/icon.png`: square logo resized with `sips -Z 512`
- Create: `apps/creator-workspace/src/components/brand/brand-mark.tsx`
- Test: `apps/creator-workspace/src/components/brand/brand-assets.test.ts`

**Interfaces:**
- Produces: `<BrandMark size?: "sm" | "md" />` is the icon inside a white `rounded-lg` tile with a 1px `pdm-border` border and `p-1`. `sm` = 32px tile, `md` = 36px. The image `alt=""`; the parent link carries the label. `<BrandLogo width: number />` is the full logo through `next/image` with `alt="ProfessorDM"`, height derived from 1240:980, `priority`.

- [ ] **Step 1: Write the failing test.** Read the PNG IHDR bytes with `node:fs` (width = bytes 16–19, height = 20–23, big-endian):

```ts
test("logo assets exist at retina-safe sizes", () => {
  expect(pngSize("public/brand/pdm-logo.png")).toEqual({ width: 1240, height: 980 });
  expect(pngSize("public/brand/pdm-icon.png").width).toBeGreaterThanOrEqual(512);
  expect(pngSize("src/app/icon.png")).toEqual({ width: 512, height: 512 });
});
```

- [ ] **Step 2: Run** it. Expected: FAIL (files missing).
- [ ] **Step 3: Generate the icon files** with the `sips` commands above (source PNGs are in the brand Drive folder; Ritvik supplies the path). Open each PNG and confirm by eye that nothing is cut off at the edges.
- [ ] **Step 4: Implement `brand-mark.tsx`** per the Interfaces block. Read `node_modules/next/dist/docs/01-app/03-api-reference/02-components/image.md` first.
- [ ] **Step 5: Run** test, lint and typecheck. Expected: PASS.
- [ ] **Step 6: STOP.** Commit message: `Add ProfessorDM logo assets, favicon and BrandMark/BrandLogo components`

---

### Task 3: Glass top bar, mobile glass tab bar and brand mist

**Files:**
- Create: `apps/creator-workspace/src/lib/nav.ts`
- Test: `apps/creator-workspace/src/lib/nav.test.ts`
- Create: `apps/creator-workspace/src/components/nav-icons.tsx`: 7 inline 20px line icons (`stroke="currentColor"`, `strokeWidth={1.75}`, `aria-hidden`)
- Create: `apps/creator-workspace/src/components/brand/brand-mist.tsx`
- Modify: `apps/creator-workspace/src/components/workspace-nav.tsx`
- Modify: `apps/creator-workspace/src/components/account-menu.tsx`
- Modify: `apps/creator-workspace/src/app/(workspace)/layout.tsx`
- Modify: `apps/creator-workspace/src/app/globals.css`: add `@utility glass` per spec §4.3, including the `@supports`, `prefers-reduced-transparency` and `forced-colors` fallbacks

**Interfaces:**
- Consumes: `BrandMark` (Task 2), tokens (Task 1).
- Produces: `NAV_ITEMS: readonly { href: string; label: string; mobile: boolean; icon: NavIconName }[]` (same 7 items and `mobile` flags as today), `isActive(pathname: string, href: string): boolean` (moved unchanged), `mobileNavItems(): typeof NAV_ITEMS[number][]`, `inboxBadgeText(count: number | null | undefined): string | null`. `WorkspaceNav` variants become `"top" | "bottom"`; `"sidebar"` is removed. `AccountMenu({ displayName, role })` loses `compact`.

- [ ] **Step 1: Write the failing test** `nav.test.ts`:

```ts
test("isActive: root only matches exactly", () => {
  expect(isActive("/", "/")).toBe(true);
  expect(isActive("/inbox", "/")).toBe(false);
});
test("isActive: nested routes match their section", () => {
  expect(isActive("/inbox/question/abc", "/inbox")).toBe(true);
  expect(isActive("/inboxes", "/inbox")).toBe(false);
});
test("mobile bar keeps the five thumb items in order", () => {
  expect(mobileNavItems().map((i) => i.label)).toEqual(["Bank", "Incoming", "Inbox", "Moderation", "Profile"]);
});
test("every desktop item has an icon", () => {
  expect(NAV_ITEMS.every((i) => i.icon)).toBe(true);
});
test("badge text caps at 99+ and hides for zero or unknown", () => {
  expect(inboxBadgeText(0)).toBeNull();
  expect(inboxBadgeText(null)).toBeNull();
  expect(inboxBadgeText(7)).toBe("7");
  expect(inboxBadgeText(120)).toBe("99+");
});
```

- [ ] **Step 2: Run** it. Expected: FAIL (module not found).
- [ ] **Step 3: Implement `lib/nav.ts`**, then make `workspace-nav.tsx` import from it.
- [ ] **Step 4: Build the `top` variant.** It is a horizontal `ul` of pills (`min-h-10 px-3 rounded-full font-display text-sm font-semibold`). Active: `bg-white text-pdm-primary ring-1 ring-pdm-primary/10 shadow-sm`. Inactive: `text-pdm-muted hover:text-pdm-primary`. All pills use `motion-safe:transition-colors`, and the active one has `aria-current="page"`.
- [ ] **Step 5: Build the `bottom` variant.** Each item is an icon over a 12px label, `min-h-12`. Active: `text-pdm-primary` plus a 3px top indicator (`before:` pseudo-element, `bg-pdm-primary`).
- [ ] **Step 6: Rebuild `AccountMenu` as a `<details>` disclosure.** The `<summary>` is a 40px round initials badge on `pdm-primary-tint` with `aria-label="Account menu"` (falls back to "PD" when there is no name). The panel is `absolute right-0 mt-2 w-64 rounded-xl bg-white border border-pdm-border` with the bar shadow from spec §3.3. It holds the name (truncate), the role chip, a **Knowledge** link (`md:hidden`) and Sign out using `buttonClass` once Task 4 lands; inline navy classes are fine for now. Close on Escape with a tiny client `onKeyDown` that sets `open=false` and focuses the summary.
- [ ] **Step 7: Implement `BrandMist`.** One fixed `div` with `aria-hidden pointer-events-none fixed inset-x-0 top-0 -z-10 h-[30rem]` and the three radial gradients from spec §4.3, written with `color-mix(in srgb, var(--color-pdm-ai) 14%, transparent)` and so on, so no hex appears in the TSX.
- [ ] **Step 8: Rewrite `(workspace)/layout.tsx`.**
  - Keep the skip link, `getSessionUser` and the redirects unchanged.
  - Remove the `<aside>`.
  - Render `<BrandMist />`.
  - Add a header `sticky top-0 z-40 glass`. Inside it, `mx-auto flex h-16 max-w-6xl items-center gap-4 px-4 md:px-8` holds: a link to `/` (`aria-label="ProfessorDM Creator Workspace home"`) containing `<BrandMark />` and a `hidden lg:inline` "Creator Workspace" text label; `<WorkspaceNav variant="top" className="hidden md:block flex-1" />`; then `<AccountMenu />`.
  - `main` becomes `mx-auto w-full max-w-6xl px-4 pb-28 pt-8 md:px-8 md:pb-12`.
  - Bottom nav: `fixed inset-x-0 bottom-0 glass md:hidden pb-[env(safe-area-inset-bottom)]`.
  - **Inbox count badge (spec §4.1):** the layout awaits `queueCounts()` from `lib/inbox/questions.ts` and passes `inboxCount={counts.inbox}` to both `WorkspaceNav` instances. `WorkspaceNav` gains `inboxCount?: number | null` and renders a `min-w-5 rounded-full bg-pdm-primary px-1.5 text-xs font-semibold text-white` badge on the Inbox item only when the count is above 0. The visible text is `99+` above 99, and it has `aria-label="{n} unanswered"`. A null count (failed load) renders nothing.
- [ ] **Step 9: Run** test, lint and typecheck. Expected: PASS. Run dev, sign in as the test creator, then check 375px and 1280px: the glass blurs the mist on scroll, and the skip link lands below the bar.
- [ ] **Step 10: STOP.** Commit message: `Move creator workspace nav to a frosted-glass top bar with mobile glass tab bar`

---

### Task 4: Shared primitives (buttons, chips, headings, tabs)

**Files:**
- Create: `apps/creator-workspace/src/components/ui/button-styles.ts`
- Test: `apps/creator-workspace/src/components/ui/button-styles.test.ts`
- Modify: `components/inbox/status-chip.tsx`, `lib/inbox/question-state.ts` (add `"success"` to `CardTone` and use it for delivered/sent states only), `components/page-section.tsx`, `components/placeholder.tsx`, `components/queue-tabs.tsx`, `components/refresh-button.tsx`, `components/account-menu.tsx` (adopt `buttonClass`)
- Test: `apps/creator-workspace/src/lib/inbox/question-state.test.ts` (extend)

**Interfaces:**
- Produces: `type ButtonVariant = "primary" | "secondary" | "ghost" | "danger"`, `type ButtonSize = "md" | "sm"`, and `buttonClass(variant?: ButtonVariant, size?: ButtonSize, extra?: string): string` (defaults: `primary`, `md`). It returns base classes `inline-flex items-center justify-center gap-2 rounded-lg font-semibold motion-safe:transition-colors disabled:cursor-not-allowed disabled:opacity-60` plus:
  - primary: `bg-pdm-primary text-white hover:bg-pdm-primary-hover`
  - secondary: `border border-pdm-border-strong bg-white text-pdm-ink hover:bg-pdm-canvas`
  - ghost: `text-pdm-primary hover:bg-pdm-primary-tint`
  - danger: `bg-pdm-danger-text text-white hover:opacity-90`
  - sizes: `md` = `min-h-11 px-4 text-sm`, `sm` = `min-h-9 px-3 text-sm`
- Produces: `CardTone = "progress" | "danger" | "accent" | "neutral" | "success"`.

- [ ] **Step 1: Write failing tests.**
  - `buttonClass()` contains `bg-pdm-primary` and `min-h-11`.
  - `buttonClass("secondary","sm")` contains `border-pdm-border-strong` and `min-h-9`, and does not contain `bg-pdm-primary`.
  - `extra` is appended last.
  - In `question-state.test.ts`, a delivered question's `cardState(...).tone` is `"success"`. Read the existing test fixtures for how to build a delivered question. If delivered questions never reach `cardState`, assert on the Sent page mapper instead and note that.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** `button-styles.ts` and the `success` tone.
- [ ] **Step 4: Restyle the primitives.**
  - `StatusChip` tone map: `progress` → `bg-pdm-ai-tint text-pdm-ai-text` (pulse dot `bg-pdm-ai`); `accent` → `bg-pdm-primary-tint text-pdm-primary`; `danger` → `bg-pdm-danger-tint text-pdm-danger-text`; `neutral` → `bg-white text-pdm-muted ring-1 ring-pdm-border`; `success` → `bg-pdm-success-tint text-pdm-success-text` (dot `bg-pdm-success`).
  - `PageHeader`: H1 `text-[1.75rem] leading-[2.125rem] font-bold tracking-[-0.01em]`, description `max-w-[70ch] text-pdm-muted`.
  - `PageSection` H2: `text-lg font-semibold`.
  - `Placeholder`: `rounded-xl border border-dashed border-pdm-border bg-white/60`.
  - `QueueTabs`: `font-display`, active border `border-pdm-primary` with text `text-pdm-primary`, active count on `bg-pdm-primary-tint`, inactive count `bg-pdm-canvas text-pdm-muted`.
  - `RefreshButton`: `buttonClass("secondary","sm")`.
- [ ] **Step 5: Run** test, lint and typecheck. Expected: PASS.
- [ ] **Step 6: STOP.** Commit message: `Add brand button styles and restyle status chips, headings and queue tabs`

---

### Task 5: Inbox, Sent and Moderation surfaces

**Files (modify only):** `components/inbox/question-card.tsx`, `components/inbox/message-row.tsx`, `components/inbox/source-list.tsx`, `components/inbox/flag-panel.tsx`, `components/inbox/reply-box.tsx`, `app/(workspace)/inbox/page.tsx`, `app/(workspace)/inbox/loading.tsx`, `app/(workspace)/inbox/[id]/page.tsx`, `app/(workspace)/sent/page.tsx`, `app/(workspace)/moderation/page.tsx`

**Interfaces:**
- Consumes: `buttonClass`, the `StatusChip` tones (Task 4) and the tokens (Task 1).

Mapping applied in every file (this is the whole decision set; apply it mechanically):

| Old | New |
|---|---|
| `bg-pdm-accent … text-white` buttons | `buttonClass()` |
| `border-pdm-accent` (selected/left accent) | `border-pdm-primary` |
| `text-pdm-accent-strong` links | `text-pdm-primary underline-offset-4 hover:underline` |
| `bg-pdm-tint` | `bg-pdm-primary-tint` |
| `bg-pdm-surface` | `bg-pdm-canvas` |
| `bg-red-50 border-red-200 text-red-800/700` | `bg-pdm-danger-tint border-pdm-danger-border text-pdm-danger-text` |
| `bg-red-100 text-red-800` chips | `bg-pdm-danger-tint text-pdm-danger-text` |
| `bg-green-50 border-green-200 text-green-800` | `bg-pdm-success-tint border-pdm-success/30 text-pdm-success-text` |
| `bg-stone-100/200`, `text-stone-600` | `bg-pdm-canvas` / skeleton `bg-pdm-border/60` / `text-pdm-muted` |
| `rounded-lg` on cards, `rounded-2xl` | `rounded-xl` (buttons and inputs stay `rounded-lg`) |
| `"Paid (test)"` footer text | Wrap in `text-pdm-money-text` (gold = money) |

Message thread: follower messages use `bg-white border border-pdm-border`. The creator's own sent messages use `bg-pdm-human`. AI or system notes use `text-pdm-ai-text`.

- [ ] **Step 1: Write a failing scoped guard test** `src/components/inbox/palette.test.ts`. It reads every file in this task's list and asserts that none matches `/\b(?:bg|text|border|ring|divide)-(?:stone|red|green|amber)-\d|pdm-(?:accent|tint\b|surface)/`.
- [ ] **Step 2: Run** it. Expected: FAIL, listing the offending files.
- [ ] **Step 3: Apply the mapping** file by file.
- [ ] **Step 4: Run** test, lint and typecheck. Expected: PASS. In dev, check Inbox (with drafting, failed and flagged cards), a thread page, Sent and Moderation at 375px and 1280px.
- [ ] **Step 5: STOP.** Commit message: `Restyle inbox, sent and moderation views to ProfessorDM brand tokens`

---

### Task 6: Answer workspace (composer and question detail)

**Files (modify only):** `components/inbox/answer-composer.tsx` (455 lines), `app/(workspace)/inbox/question/[id]/page.tsx`
**Test:** extend `src/components/inbox/palette.test.ts` with both files.

- [ ] **Step 1: Add both files** to the guard test's list. Run it. Expected: FAIL.
- [ ] **Step 2: Apply the Task 5 mapping**, plus these:
  - The AI draft reference panel gets `rounded-xl bg-pdm-ai-tint` and a label "AI draft" in `text-xs font-semibold text-pdm-ai-text`.
  - The editable answer textarea is `bg-white border-pdm-border-strong rounded-lg`. Once the text differs from `aiText` (reuse the existing `changeRatio`/state; add no new logic) it switches to `bg-pdm-human`.
  - The send button is `buttonClass()`.
  - The confirm dialog overlay `bg-black/40` becomes `bg-pdm-ink/40 backdrop-blur-sm`. The dialog panel is `rounded-xl` with the bar shadow.
  - The undo/success toast uses `bg-pdm-success-tint text-pdm-success-text`.
  - Byte/length meter: normal `text-pdm-muted`, over-limit `text-pdm-danger-text`.
- [ ] **Step 3:** If `answer-composer.tsx` is still over 400 lines after the restyle, leave it. Splitting it is out of scope; note it as a follow-up in the STOP report.
- [ ] **Step 4: Run** test, lint and typecheck. Expected: PASS. In dev, open a question awaiting the creator. Edit the draft and confirm the field turns sage. Open the confirm dialog and Tab through it, checking focus stays inside. Cancel.
- [ ] **Step 5: STOP.** Commit message: `Restyle answer workspace with AI-draft cyan and creator-voice sage states`

---

### Task 7: Bank, Profile, Incoming, Knowledge, Login and 404

**Files (modify only):** `app/(workspace)/page.tsx`, `app/(workspace)/profile/page.tsx`, `app/(workspace)/incoming/page.tsx`, `app/(workspace)/knowledge/page.tsx`, `app/login/page.tsx`, `app/login/login-form.tsx`, `app/not-found.tsx`
**Test:** add these files to `palette.test.ts`.

- [ ] **Step 1: Add the files** to the guard test. Run it. Expected: FAIL.
- [ ] **Step 2: Bank.** Balance tiles become `rounded-xl bg-white border border-pdm-border`, with a 3px top rule in `bg-pdm-money` (decorative) and a value in `font-display text-2xl font-bold text-pdm-heading`. Withdraw uses `buttonClass()` (still disabled). Gold appears only on this page.
- [ ] **Step 3: Login and 404.** Each renders `<BrandMist />` and `<BrandLogo width={200} />` centred above a `rounded-xl bg-white border border-pdm-border p-6 md:p-8` card. Remove the text wordmark. Inputs get `border-pdm-border-strong rounded-lg`, the submit button gets `buttonClass(undefined, undefined, "w-full")`, and errors use `text-pdm-danger-text`.
- [ ] **Step 4: Profile, Incoming and Knowledge.** Apply the Task 5 mapping.
- [ ] **Step 5: Run** test, lint and typecheck. Expected: PASS. Check `/login` signed out at 320px: the logo is crisp at 2× and the card has no horizontal scroll.
- [ ] **Step 6: STOP.** Commit message: `Restyle bank, profile, login and 404 with ProfessorDM logo and tokens`

---

### Task 8: Retire legacy tokens, app-wide guard and QA

**Files:**
- Modify: `apps/creator-workspace/src/app/globals.css` (delete the four legacy aliases)
- Create: `apps/creator-workspace/src/lib/brand/palette.test.ts` (app-wide; replaces `src/components/inbox/palette.test.ts`, which is deleted)

- [ ] **Step 1: Write the app-wide guard.** It recursively scans `src/**/*.tsx` and asserts no file matches `/\b(?:bg|text|border|ring|divide|outline)-(?:stone|red|green|amber|gray|slate)-\d|\bbg-black\b|pdm-(?:accent|tint\b|surface)|rounded-2xl/`. There are no exceptions. A second test asserts `globals.css` contains none of `--color-pdm-accent`, `--color-pdm-tint` or `--color-pdm-surface`.
- [ ] **Step 2: Run** it. Expected: FAIL only on the `globals.css` aliases. Fix any stragglers it reports.
- [ ] **Step 3: Delete the aliases.** Run test, lint, typecheck and `build`. Expected: all PASS.
- [ ] **Step 4: Visual QA** in Chrome against the dev server, signed in as the test creator. Check every route at 320, 768, 1024 and 1440 px, and screenshot Inbox, the answer workspace, Bank and Login. Check each Review Focus item 1–5. Use DevTools rendering emulation to check `prefers-reduced-motion` and `forced-colors`, and also toggle `prefers-reduced-transparency`. Tab through the top bar and account menu.
- [ ] **Step 5: Accessibility pass.** Run Lighthouse accessibility on `/login` and `/inbox`; expected score ≥ 95 with no contrast failures.
- [ ] **Step 6: STOP.** Report the screenshots and any follow-ups (composer split, vector logo request, consumer spec). Commit message: `Remove legacy amber tokens and guard creator workspace against off-brand classes`
