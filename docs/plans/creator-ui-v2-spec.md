# Creator Workspace UI v2 — Spec

Status: Approved in chat (2026-11-11) · Owner: Ritvik · Builds on `creator-brand-refresh-spec.md` (tokens, logo and type rules still apply).
Scope: `apps/creator-workspace` only.

> **Hard rule: no git by the implementer.** Never run `git commit`, `git push` or any other git command, and never push to GitHub. Each task ends with a STOP and a one-line commit message for Ritvik. He commits, and pushes manually at the end.

## Why

Ritvik's verdict on v1: "it feels so old." The palette is right, but the frame isn't. The full-width bar and full-width content read like a 2015 admin panel. Moving between screens is a hard cut. In a conversation, the reply box scrolls away with the messages. And switching between chats means going back to a list every time.

## Requirements (Ritvik's list → decisions)

| # | Request | Decision |
|---|---|---|
| 1 | Dark mode | Follows the device setting by default. The avatar menu has a **Light / Dark / System** switch, remembered per browser in `localStorage`. No flash on load: an inline head script sets `data-theme` before paint. |
| 2 | Nav as an island, not full width | A **centred floating glass pill**, `sticky top-3`, sized to its content: logo tile, 6 sections, avatar. On mobile, a small top island (logo + avatar) and a **floating bottom tab island**. |
| 2b | "Translucent, proper glass" | Card colour at ~50% opacity, `backdrop-filter: blur(20px) saturate(180%)`, a 1px inner top highlight, a hairline border and a soft long shadow. There are matching dark-mode values. Fallbacks: solid when blur is unsupported or reduced transparency is on; `CanvasText` border in forced colours. |
| 3 | Dynamic and super smooth | **All four:** (a) route cross-fades with a slight rise via React `<ViewTransition>`, plus the active nav pill gliding between items; (b) instant feel: `loading.tsx` skeletons on every route, prefetching links, and an optimistic reply bubble; (c) micro-interactions: buttons press in, cards lift on hover, menus scale and fade open; (d) live updates: new bubbles and cards animate in when realtime refreshes. Everything is off under `prefers-reduced-motion`. |
| 4 | Conversation reply box must stay put | The conversation becomes a fixed-height pane: the header stays at the top, the **messages scroll inside their own area**, and the reply box is **pinned to the bottom**. It opens scrolled to the newest message and follows new messages unless the creator has scrolled up. |
| 5 | Don't span everything full width; follow HCI principles | List pages (Bank, Incoming, Inbox, Sent, Moderation, Knowledge, Profile) use a **narrow reading column, `max-w-3xl` (768px)**. Split views (conversation, answer workspace) use up to `max-w-6xl`. Content is left-aligned inside a centred column. Spacing stays on the 4px scale, and every target is ≥ 44px. |
| 6 | Profile lives under the avatar | Profile leaves the nav. The avatar menu holds the name and role, then **Profile**, **Knowledge** (mobile), the **theme switch** and **Sign out**. |
| 7 | Use frontend-design + superpowers skills | Applied. Process: spec → plan → TDD per task. |
| 8 | Left chat switcher in the inbox | Only on `/inbox/[id]` (conversation) and `/inbox/question/[id]` (answer). A persistent left rail (`w-72`) with two tabs: **Chats**, one row per follower with the latest message first, and **Questions**, the inbox queue. The rail's tab defaults to the current route type. The rail lives in a shared route-group layout, so it never reloads when you switch chats. On phones it's a **"Chats" button that opens a drawer**. |

## Dark palette

These are added to the v1 token table. They're swapped on `:root[data-theme="dark"]`, and every pair is enforced by `contrast.test.ts`.

| Token | Dark | Note |
|---|---|---|
| canvas | `#0B1620` | Deeper than Midnight Navy |
| card | `#12232E` | Midnight Navy (brand) |
| ink | `#E6EEF4` | |
| heading | `#F2F7FB` | |
| muted | `#9DB0C0` | |
| border | `#22384A` | |
| border-strong | `#6B8396` | ≥ 3:1 on card |
| primary | `#7CB8EA` | Navy can't be an action colour on navy; a light brand-navy tint is used instead |
| primary-hover | `#A3CDF1` | |
| primary-tint | `#1A3346` | |
| on-primary | `#06233B` (dark) / `#FFFFFF` (light) | Text on primary buttons |
| success / ai / money | brand hexes unchanged | Fills only |
| success-text / ai-text / money-text | `#4FD19F` / `#5FD6E8` / `#F0B266` | |
| success-tint / ai-tint / money-tint | `#0F3326` / `#0B3038` / `#3A2A14` | |
| human (sage) | `#1E2A1A` | |
| danger-text / -tint / -border | `#FF8A80` / `#3A1715` / `#6B2A25` | |
| logo-bg | `#FFFFFF` in both themes | The logo PNGs are opaque white, so their tile and frame stay white in dark mode too |

Components must use `bg-pdm-card` and `text-pdm-on-primary`, never `bg-white` or `text-white`. The palette guard adds both to its banned list.

## Motion spec

- Route change: the old page fades out in 120ms. The new page fades in and rises 6px over 220ms with `cubic-bezier(.2,.8,.2,1)`.
- Nav pill: a shared `view-transition-name` on the active pill, so it glides to the new item (300ms).
- Menus and the drawer: `@starting-style` scale .96→1 and opacity 0→1, 160ms.
- Buttons: `active:scale-[.98]`. Cards: hover `-translate-y-px` plus a soft shadow, 150ms.
- Live inserts: new bubbles and question cards enter with a 200ms fade and rise.
- `prefers-reduced-motion: reduce` removes all of it, including the view transitions.

## Non-goals

- The consumer app.
- New data or backend changes. The rail reuses `listInboundMessages` and `listQuestions`.
- Redesigning copy.
