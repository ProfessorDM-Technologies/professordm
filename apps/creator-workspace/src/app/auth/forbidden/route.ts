import { redirect } from "next/navigation";
import { LOGIN_PATH } from "@/lib/routes";
import { createClient } from "@/lib/supabase/server";

// Server layouts can't clear auth cookies, so a signed-in user without a workspace role is sent here
// to be signed out before landing on /login. Going straight to /login would bounce back via the proxy.
export async function GET() {
  const supabase = await createClient();
  await supabase.auth.signOut();
  redirect(`${LOGIN_PATH}?error=forbidden`);
}
