import type { Metadata } from "next";
import { Placeholder } from "@/components/placeholder";
import { signOut } from "@/lib/auth/actions";

export const metadata: Metadata = {
  title: "Profile",
};

export default function ProfilePage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Profile</h1>

      <section aria-labelledby="account-heading" className="space-y-2">
        <h2 id="account-heading" className="text-lg font-semibold">
          Account
        </h2>
        <Placeholder>Name, email, photo and notification settings will appear here.</Placeholder>
      </section>

      <section aria-labelledby="plan-heading" className="space-y-2">
        <h2 id="plan-heading" className="text-lg font-semibold">
          Plan and billing
        </h2>
        <Placeholder>Your plan, free answers remaining, renewal date and saved card will appear here.</Placeholder>
      </section>

      <section aria-labelledby="history-heading" className="space-y-2">
        <h2 id="history-heading" className="text-lg font-semibold">
          Question history
        </h2>
        <Placeholder>Your past questions will appear here.</Placeholder>
      </section>

      <form action={signOut}>
        <button
          type="submit"
          className="rounded-lg border border-flora-border bg-white px-4 py-3 font-medium hover:bg-flora-tint"
        >
          Sign out
        </button>
      </form>
    </div>
  );
}
