import type { Metadata } from "next";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";

export const metadata: Metadata = {
  title: "ProfessorDM Bank",
};

const BALANCE_TILES = [
  { label: "Available Now", note: "Ready to withdraw." },
  { label: "Pending", note: "Released after the 3-day hold." },
  { label: "Total Balance", note: "Available plus pending." },
] as const;

export default function BankPage() {
  return (
    <div className="space-y-8">
      <PageHeader title="ProfessorDM Bank" description="Your earnings, held funds and payouts." />

      <PageSection id="refunds" title="Refund requests">
        <Placeholder>Open refund requests will show here as a banner.</Placeholder>
      </PageSection>

      <PageSection id="balance" title="Balance">
        <ul className="grid gap-3 sm:grid-cols-3">
          {BALANCE_TILES.map((tile, index) => (
            <li
              key={tile.label}
              className={`relative space-y-1 overflow-hidden rounded-2xl border bg-pdm-panel p-5 ${
                index === 0 ? "border-pdm-gold/50" : "border-pdm-border"
              }`}
            >
              {/* Gold is the money colour (brand §03); only the withdrawable figure gets it. */}
              {index === 0 ? <span aria-hidden="true" className="absolute inset-x-0 top-0 h-1 bg-pdm-gold" /> : null}
              <p className="text-sm font-semibold text-pdm-muted">{tile.label}</p>
              <p
                className={`font-display text-3xl font-extrabold tabular-nums ${index === 0 ? "text-pdm-gold-ink" : "text-pdm-heading"}`}
                aria-label={`${tile.label}: not available yet`}
              >
                —
              </p>
              <p className="text-xs text-pdm-muted">{tile.note}</p>
            </li>
          ))}
        </ul>
        <p className="text-sm text-pdm-muted">Lifetime earnings will appear here.</p>
      </PageSection>

      <PageSection id="transactions" title="Transactions">
        <Placeholder>
          Paid questions filterable by status: unanswered, in progress, completed and refund requested.
        </Placeholder>
      </PageSection>

      <PageSection id="withdraw" title="Withdraw">
        <button
          type="button"
          disabled
          aria-describedby="withdraw-note"
          className="pdm-press rounded-full bg-pdm-accent px-4 py-3 font-semibold text-pdm-on-accent disabled:cursor-not-allowed disabled:opacity-60"
        >
          Withdraw Available Balance
        </button>
        <p id="withdraw-note" className="text-sm text-pdm-muted">
          Withdrawals are not available yet.
        </p>
      </PageSection>
    </div>
  );
}
