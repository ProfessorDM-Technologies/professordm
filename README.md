# ProfessorDM

AI-assisted Instagram question monetization + searchable expert knowledge. ASU capstone, V1 MVP for Sweetlife Flora.

| Folder | What | Owner |
|---|---|---|
| `apps/creator-workspace` | Creator Workspace (Next.js, Vercel) | Ritvik |
| `apps/consumer` | Ask page + Ask Sweetlife Flora (Next.js, Vercel) | Arun |
| `services/*` | Lambdas: ig-webhook, stripe-webhook, api, sender (Akshay), ai-worker (Chinmay), scheduler (Karthik) | see diagram 12 |
| `packages/contracts` | Shared statuses + queue payloads | Karthik + all |
| `supabase/` | Migrations, RLS, seed | Karthik |
| `infra/` | AWS SAM template | Karthik + Akshay |
| `eval/`, `e2e/` | AI evaluation, Playwright | Chinmay, Karthik |
| `docs/architecture/` | Diagrams + BASELINE.md | Karthik |

Start here: `docs/architecture/BASELINE.md`, then diagrams `02` and `02b`. Rules: `CONTRIBUTING.md`.

Setup: Node 22 (`.nvmrc`), pnpm 10, then `pnpm install`.
