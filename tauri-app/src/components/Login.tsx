import { useState } from "react";
import { AUTH_CODE_URL } from "../lib/accelerator/config";
import { redeemDeviceCode } from "../lib/accelerator/auth";
import { openExternal } from "../lib/accelerator/platform";

interface LoginProps {
  onLoggedIn: () => void;
}

export default function Login({ onLoggedIn }: LoginProps) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await redeemDeviceCode(code.trim());
      onLoggedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container">
      <h1>CWatM Accelerator Client</h1>
      <p>
        1. Open the authorization page and sign in with your Accelerator
        account:
      </p>
      <p>
        <button type="button" onClick={() => openExternal(AUTH_CODE_URL)}>
          Open {AUTH_CODE_URL}
        </button>
      </p>
      <p>2. Paste the code it shows you below:</p>
      <form className="row" onSubmit={submit}>
        <input
          autoFocus
          value={code}
          onChange={(e) => setCode(e.currentTarget.value)}
          placeholder="Authorization code"
        />
        <button type="submit" disabled={busy || !code.trim()}>
          {busy ? "Logging in..." : "Log in"}
        </button>
      </form>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
    </main>
  );
}
