"use client";

import { useState } from "react";

export default function LoginPage() {
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function sendCode() {
    setLoading(true);
    setMessage(null);
    try {
      const res = await fetch("/api/auth/request-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (res.ok) {
        setStep("code");
        setMessage("Code sent (check console in dev).");
      } else {
        const data = await res.json();
        setMessage(data.error || "Failed to send code.");
      }
    } catch (err) {
      console.error(err);
      setMessage("Network error – please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function verifyCode() {
    setLoading(true);
    setMessage(null);
    try {
      const res = await fetch("/api/auth/verify-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code }),
      });
      const data = await res.json();
      if (res.ok) {
        setMessage("Logged in. Redirecting...");
        window.location.href = "/playground";
      } else {
        setMessage(data.error || "Invalid code.");
      }
    } catch (err) {
      console.error(err);
      setMessage("Network error – please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center justify-center py-16">
      <div className="w-full max-w-sm rounded-xl border border-nepsis-border bg-nepsis-panel p-6 shadow-2xl shadow-black/40">
        <h1 className="mb-2 text-lg font-semibold">Login to NepsisCGN</h1>
        <p className="mb-4 text-xs text-nepsis-muted">
          Passwordless login. Enter your email and we’ll send you a one-time code.
        </p>

        {step === "email" ? (
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs">Email</label>
              <input
                className="w-full rounded-lg border border-nepsis-border bg-black/30 px-3 py-2 text-sm focus:border-nepsis-accent focus:outline-none"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
            </div>
            <button
              disabled={loading || !email}
              onClick={sendCode}
              className="w-full rounded-full bg-nepsis-accent py-2 text-sm font-medium text-black transition hover:bg-nepsis-accentSoft disabled:opacity-60"
            >
              {loading ? "Sending..." : "Send code"}
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-nepsis-muted">
              We’ve sent a code to <span className="font-mono">{email}</span>.
            </p>
            <div>
              <label className="mb-1 block text-xs">Code</label>
              <input
                className="w-full rounded-lg border border-nepsis-border bg-black/30 px-3 py-2 text-center text-sm font-mono tracking-[0.3em] focus:border-nepsis-accent focus:outline-none"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="123456"
              />
            </div>
            <button
              disabled={loading || code.length === 0}
              onClick={verifyCode}
              className="w-full rounded-full bg-nepsis-accent py-2 text-sm font-medium text-black transition hover:bg-nepsis-accentSoft disabled:opacity-60"
            >
              {loading ? "Verifying..." : "Verify & continue"}
            </button>
          </div>
        )}

        {message && (
          <p className="mt-3 text-xs text-nepsis-muted" role="status">
            {message}
          </p>
        )}
      </div>
    </div>
  );
}
