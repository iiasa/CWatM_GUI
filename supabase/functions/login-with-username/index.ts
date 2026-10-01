// login-with-username - sign in with username + password.
//
// Supabase Auth only knows email + password. This function resolves the username to
// its email on the server (so no email address is ever exposed to a client) and
// signs in with it, returning the normal Supabase session. The GUI then hands that
// session to its supabase client (auth.set_session).
//
// POST {"username": "...", "password": "..."}
//   200 {"session": {...}}                         access_token, refresh_token, user, ...
//   400 {"error": "invalid_credentials"}           unknown username OR wrong password
//   400 {"error": "email_not_confirmed"}
//   429 {"error": "too_many_attempts"}             game_config login_max_failures
//
// Deploy with --no-verify-jwt: the caller is not logged in yet.

import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

// Same rule as the profiles.username check constraint.
const USERNAME_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{2,29}$/;

const NO_SESSION = { auth: { persistSession: false, autoRefreshToken: false } };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// One answer for "no such user" and "wrong password", so the endpoint does not tell
// which usernames exist.
const INVALID = { error: "invalid_credentials", message: "Invalid login credentials" };

Deno.serve(async (req) => {
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  let body: { username?: unknown; password?: unknown };
  try {
    body = await req.json();
  } catch {
    return json({ error: "bad_request" }, 400);
  }
  const username = typeof body.username === "string" ? body.username.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!USERNAME_RE.test(username) || !password || password.length > 256) {
    return json(INVALID, 400);
  }

  const admin = createClient(SUPABASE_URL, SERVICE_KEY, NO_SESSION);

  const { data: throttled, error: throttleErr } = await admin.rpc("_login_throttled", {
    p_username: username,
  });
  if (throttleErr) return json({ error: "server_error" }, 500);
  if (throttled) {
    return json({
      error: "too_many_attempts",
      message: "Too many failed logins for this username. Try again later.",
    }, 429);
  }

  const { data: email, error: emailErr } = await admin.rpc("_email_for_username", {
    p_username: username,
  });
  if (emailErr) return json({ error: "server_error" }, 500);
  if (!email) {
    await admin.rpc("_login_record", { p_username: username, p_success: false });
    return json(INVALID, 400);
  }

  // No X-Forwarded-For is passed on: the client can write anything into that header,
  // so forwarding it would let a caller pick a fresh "IP" for every attempt and slip
  // past Auth's per-IP rate limit (security.md #6). Password guessing is limited by
  // the per-username throttle above (_login_throttled) instead.
  const anon = createClient(SUPABASE_URL, ANON_KEY, NO_SESSION);

  const { data, error } = await anon.auth.signInWithPassword({ email, password });
  if (error || !data.session) {
    // Auth reports an unconfirmed email only after the password matched.
    if (error?.code === "email_not_confirmed") {
      return json({
        error: "email_not_confirmed",
        message: "Please confirm your email address first.",
      }, 400);
    }
    await admin.rpc("_login_record", { p_username: username, p_success: false });
    return json(INVALID, 400);
  }

  await admin.rpc("_login_record", { p_username: username, p_success: true });
  return json({ session: data.session });
});
