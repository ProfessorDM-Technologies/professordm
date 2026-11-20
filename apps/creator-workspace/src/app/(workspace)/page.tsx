import type { Metadata } from "next";
import { EmptyState } from "@/components/empty-state";
import { PageHeader, PageSection } from "@/components/page-section";

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
        <EmptyState icon="money" tone="gold" title="No refund requests">
          Nothing needs your attention. A follower&apos;s refund request would show here first.
        </EmptyState>
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
              >
                $0.00
              </p>
              <p className="text-xs text-pdm-muted">{tile.note}</p>
            </li>
          ))}
        </ul>
        <p className="text-sm text-pdm-muted">
          Lifetime earnings: <span className="font-semibold text-pdm-ink tabular-nums">$0.00</span>
        </p>
      </PageSection>

      <PageSection id="transactions" title="Transactions">
        <EmptyState icon="list" tone="gold" title="No transactions yet">
          Each paid question is listed here with its status: unanswered, in progress, completed or refund requested.
        </EmptyState>
      </PageSection>

      <PageSection id="withdraw" title="Withdraw">
        <button
          type="button"
          disabled
          aria-describedby="withdraw-note"
          className="min-h-11 cursor-not-allowed rounded-full border border-dashed border-pdm-border bg-pdm-panel px-5 font-semibold text-pdm-muted"
        >
          Withdraw $0.00
        </button>
        <p id="withdraw-note" className="text-sm text-pdm-muted">
          Withdrawals open once payouts are connected to your account.
        </p>
      </PageSection>
    </div>
  );
}
