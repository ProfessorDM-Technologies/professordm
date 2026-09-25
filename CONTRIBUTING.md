# Working in this repo

1. Branch from `main`: `feature/SCRUM-28-short-name` or `fix/SCRUM-30-short-name`.
2. Open a PR to `main`. Fill the template. Assign the owning lead as reviewer (see `.github/CODEOWNERS`).
3. Merge only with **1 approval from the owning lead + green CI**. Squash merge.
4. Change touches another person's area? Write a short ADR in `docs/adr/` and add Karthik as a second reviewer.
5. **Never push to `main` directly.** GitHub Free can't enforce this on private repos, so it's a team rule.
6. **No secrets in code, commits, PRs, Jira or chat.** Values live in Vercel env vars, AWS SSM or GitHub secrets.
   If one leaks, tell Karthik and rotate it immediately.
7. Shared types come from `packages/contracts`. Don't redefine statuses or job types in your own code.
