import type { Metadata } from "next";
import { signOut } from "@/lib/auth/actions";
import { getCurrentUser } from "@/lib/auth/session";
import { getDisplayName } from "@/lib/knowledge/queries";

export const metadata: Metadata = {
  title: "Profile",
};

export default async function ProfilePage() {
  const user = await getCurrentUser();
  const displayName = user ? await getDisplayName(user.id) : null;
  const email = user?.email ?? "";
  const name = displayName && displayName !== email ? displayName : null;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Profile</h1>

      <section aria-labelledby="account-heading" className="space-y-2">
        <h2 id="account-heading" className="text-lg font-semibold">
          Account
        </h2>
        <dl className="divide-y divide-flora-border rounded-lg border border-flora-border bg-white">
          <div className="flex flex-col gap-1 p-4 sm:flex-row sm:justify-between">
            <dt className="text-sm text-flora-muted">Name</dt>
            <dd className="font-medium">{name ?? "Not set"}</dd>
          </div>
          <div className="flex flex-col gap-1 p-4 sm:flex-row sm:justify-between">
            <dt className="text-sm text-flora-muted">Email</dt>
            <dd className="font-medium break-all">{email}</dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="plan-heading" className="space-y-2">
        <h2 id="plan-heading" className="text-lg font-semibold">
          Plan
        </h2>
        <p className="rounded-lg border border-flora-border bg-white p-4 font-medium">Free Trial</p>
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
