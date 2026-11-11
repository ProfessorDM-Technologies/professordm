# Creator Workspace UI v2 Implementation Plan

> **HARD RULE:** never commit or push, and run no git commands. Each task ends at a STOP with a one-line commit message for Ritvik. He commits, and pushes manually at the end.
> Load `frontend-design:frontend-design` and `frontend-ui-engineering` before UI work.

**Goal:** Dark mode, a translucent floating island nav, narrow readable layouts, a pinned conversation composer, an inbox chat rail and smooth motion. See `docs/plans/creator-ui-v2-spec.md`.
**Stack:** Next 16.4 App Router, React 19.3 (`<ViewTransition>`), Tailwind 4.3 tokens, Vitest (node).

## Global constraints
- v1 rules stand: tokens only, no brand hex in TSX, sentence case, logo only through `BrandMark`/`BrandLogo`.
- No new dependencies. All checks green per task: `pnpm --filter @professordm/creator-workspace test lint typecheck`.

## Tasks

### Task 1 — Dark-mode tokens and theme plumbing
- `globals.css`: add `on-primary` and `logo-bg` tokens. Add a `:root[data-theme="dark"]` block with the dark palette (spec), plus `color-scheme`.
- `lib/theme.ts`: `type ThemePref = "light" | "dark" | "system"`; `resolveTheme(pref, systemDark): "light" | "dark"`; `parseThemePref(raw: string | null): ThemePref`; `THEME_STORAGE_KEY`; and `themeBootScript` (an inline string).
- Root layout: `<html suppressHydrationWarning>` with the boot script in `<head>`.
- Migrate `bg-white` → `bg-pdm-card` and `text-white` → `text-pdm-on-primary`. Logo tiles use `bg-pdm-logo-bg`.
- Tests: `theme.test.ts` (resolve and parse). `contrast.test.ts` gains the same pairs for dark via `readThemeTokens(css, "dark")`. The palette guard bans `bg-white` and `text-white`.
- STOP → `Add dark mode tokens with system-default theme and no-flash boot script`

### Task 2 — Translucent island nav and avatar menu
- `lib/nav.ts`: drop Profile from `NAV_ITEMS`. The mobile items become Bank, Incoming, Inbox, Sent, Moderation. Update `nav.test.ts` first.
- The `glass` utility is rewritten to the spec's translucent recipe, with light and dark variables.
- Layout: a centred sticky pill (`mx-auto w-fit`) holding logo tile, nav and avatar. Mobile: a small top island plus a floating bottom island (`inset-x-3 bottom-3 rounded-full`).
- The active pill gets `viewTransitionName: "nav-pill"`.
- `AccountMenu`: Profile and Knowledge links, a `ThemeSwitch` (3-way radio group writing `localStorage` and `data-theme`, following system changes when set to "system"), Sign out, and an animated open.
- STOP → `Turn the top bar into a translucent glass island and move Profile and theme switch into the avatar menu`

### Task 3 — Readable widths
- `components/page.tsx`: `<Page width="narrow" | "wide">` sets `max-w-3xl` or `max-w-6xl`, with `mx-auto w-full`.
- Wrap every list page in `narrow`.
- STOP → `Constrain list pages to a readable column`

### Task 4 — Inbox detail layout: chat rail and pinned composer
- `lib/inbox/conversations.ts`: `groupConversations(messages: InboxMessage[]): ConversationSummary[]` (one per follower, latest first) and `railModeFor(pathname): "chats" | "questions" | null`, both tested first.
- Move `inbox/[id]` and `inbox/question/[id]` into the `inbox/(detail)/` route group. URLs are unchanged.
- `(detail)/layout.tsx` fetches both lists and renders `<ChatRail>` (desktop, `lg+`) plus the mobile drawer.
- Conversation page: a `h-[calc(100dvh-…)]` flex column with the header, `<MessagePane>` (client; own scroll; sticks to bottom unless the creator scrolled up) and the pinned `ReplyBox`.
- STOP → `Add inbox chat rail and pin the conversation reply box`

### Task 5 — Motion
- Workspace layout: wrap children in `<ViewTransition default="page">`. CSS adds the page and nav-pill keyframes and the reduced-motion kill switch.
- `loading.tsx` for incoming, sent, moderation and both detail routes.
- Micro-interactions in `buttonClass` and the cards. Bubbles and question cards get `<ViewTransition enter="rise">`.
- `RealtimeRefresh` calls `router.refresh()` inside `startTransition`, so inserts animate.
- Optimistic reply bubble via `useOptimistic` in the conversation pane.
- STOP → `Add page transitions, skeletons, live insert animations and micro-interactions`

### Task 6 — QA
- Iframe sweep at 320/768/1024/1440 in both themes, keyboard pass, reduced-motion pass. Fix what it finds.
- STOP → `Polish UI v2 after responsive, dark-mode and keyboard QA`
