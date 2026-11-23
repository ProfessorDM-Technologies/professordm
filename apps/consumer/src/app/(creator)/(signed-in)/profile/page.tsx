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
    <div className="space-y-8">
      <h1 className="text-3xl leading-tight font-extrabold sm:text-4xl">Profile</h1>

      <section aria-labelledby="account-heading" className="space-y-2">
        <h2 id="account-heading" className="text-lg font-bold">
          Account
        </h2>
        <dl className="divide-y divide-pdm-border rounded-2xl border border-pdm-border bg-pdm-panel">
          <div className="flex flex-col gap-1 p-4 sm:flex-row sm:justify-between">
            <dt className="text-sm text-pdm-muted">Name</dt>
            <dd className="font-medium">{name ?? "Not set"}</dd>
          </div>
          <div className="flex flex-col gap-1 p-4 sm:flex-row sm:justify-between">
            <dt className="text-sm text-pdm-muted">Email</dt>
            <dd className="font-medium break-all">{email}</dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="plan-heading" className="space-y-2">
        <h2 id="plan-heading" className="text-lg font-bold">
          Plan
        </h2>
        <p className="rounded-2xl border border-pdm-border bg-pdm-panel p-4 font-semibold">Free Trial</p>
      </section>

      <form action={signOut}>
        <button
          type="submit"
          className="pdm-press min-h-11 rounded-full border border-pdm-border bg-pdm-panel px-5 font-semibold text-pdm-ink hover:border-pdm-accent hover:bg-pdm-subtle"
        >
          Sign out
        </button>
      </form>
    </div>
  );
}
