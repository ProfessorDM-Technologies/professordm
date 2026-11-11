import type { Metadata } from "next";
import { Page } from "@/components/page";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";
import { buttonClass } from "@/components/ui/button-styles";

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
    <Page className="space-y-8">
      <PageHeader title="ProfessorDM Bank" description="Your earnings, held funds and payouts." />

      <PageSection id="refunds" title="Refund requests">
        <Placeholder>Open refund requests will show here as a banner.</Placeholder>
      </PageSection>

      <PageSection id="balance" title="Balance">
        <ul className="grid gap-3 sm:grid-cols-3">
          {BALANCE_TILES.map((tile) => (
            <li
              key={tile.label}
              // Gold marks money (spec section 3.1): a decorative top rule; text stays navy for contrast.
              className="relative space-y-1 overflow-hidden rounded-xl border border-pdm-border bg-pdm-card p-4 pt-5 before:absolute before:inset-x-0 before:top-0 before:h-[3px] before:bg-pdm-money"
            >
              <p className="text-sm font-medium text-pdm-muted">{tile.label}</p>
              <p className="font-display text-2xl font-bold text-pdm-heading" aria-label={`${tile.label}: not available yet`}>
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
          className={buttonClass()}
        >
          Withdraw Available Balance
        </button>
        <p id="withdraw-note" className="text-sm text-pdm-muted">
          Withdrawals are not available yet.
        </p>
      </PageSection>
    </Page>
  );
}
