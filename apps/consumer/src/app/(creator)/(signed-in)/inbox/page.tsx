import type { Metadata } from "next";
import { Placeholder } from "@/components/placeholder";

export const metadata: Metadata = {
  title: "Inbox",
};

export default function InboxPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Inbox</h1>
        <p className="text-flora-muted">Answers to questions you asked in the app.</p>
      </div>

      <section aria-labelledby="answers-heading" className="space-y-2">
        <h2 id="answers-heading" className="text-lg font-semibold">
          Your questions
        </h2>
        <Placeholder>Your questions and answers will appear here.</Placeholder>
      </section>
    </div>
  );
}
