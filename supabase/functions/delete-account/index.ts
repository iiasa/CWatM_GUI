// delete-account - permanently delete the caller's account and all their data.
//
// Deleting an auth user needs the service role, which never leaves the server, so
// the GUI calls this function instead. The password is asked again, so a leaked
// access token alone cannot delete an account. profiles / point_events / user_badges
// go with the auth user (on delete cascade).
//
// POST, header "Authorization: Bearer <access_token>", body {"password": "..."}
//   200 {"deleted": true}
//   401 {"error": "not_authenticated" | "invalid_password"}
//
// Deploy with --no-verify-jwt: the token is verified here (getUser), which works with
// both the legacy JWT keys and the new publishable keys.

import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const NO_SESSION = { auth: { persistSession: false, autoRefreshToken: false } };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  const token = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
  if (!token) return json({ error: "not_authenticated" }, 401);

  let password = "";
  try {
    const body = await req.json();
    password = typeof body?.password === "string" ? body.password : "";
  } catch {
    return json({ error: "bad_request" }, 400);
  }
  if (!password) return json({ error: "invalid_password" }, 401);

  const admin = createClient(SUPABASE_URL, SERVICE_KEY, NO_SESSION);
  const { data: userData, error: userErr } = await admin.auth.getUser(token);
  const user = userData?.user;
  if (userErr || !user?.email) return json({ error: "not_authenticated" }, 401);

  // Re-check the password.
  const anon = createClient(SUPABASE_URL, ANON_KEY, NO_SESSION);
  const { error: pwErr } = await anon.auth.signInWithPassword({
    email: user.email,
    password,
  });
  if (pwErr) return json({ error: "invalid_password" }, 401);

  const { error: delErr } = await admin.auth.admin.deleteUser(user.id);
  if (delErr) return json({ error: "server_error" }, 500);
  return json({ deleted: true });
});
