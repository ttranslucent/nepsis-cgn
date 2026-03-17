"use client";

import { useState } from "react";

export default function LoginPage() {
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [delivery, setDelivery] = useState<"email" | "preview" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function sendCode() {
    setLoading(true);
    setMessage(null);
    setDelivery(null);
    try {
      const res = await fetch("/api/auth/request-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (res.ok) {
        setStep("code");
        setDelivery(data.delivery === "preview" ? "preview" : "email");
        if (data.delivery === "preview" && typeof data.previewCode === "string") {
          setCode(data.previewCode);
          setMessage(`Email delivery is not configured here. Use this one-time code: ${data.previewCode}`);
        } else {
          setCode("");
          setMessage("Code sent. Check your inbox for the one-time code.");
        }
      } else {
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
        window.location.href = "/engine";
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
          Passwordless login. If email delivery is configured, you&apos;ll receive a one-time code. In non-production
          or preview deployments with code preview enabled, the code may be shown directly instead.
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
              {delivery === "preview" ? "Use the preview code for" : "We’ve sent a code to"}{" "}
              <span className="font-mono">{email}</span>.
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
            <button
              type="button"
              onClick={() => {
                setStep("email");
                setCode("");
                setDelivery(null);
                setMessage(null);
              }}
              className="w-full rounded-full border border-nepsis-border py-2 text-sm transition hover:border-nepsis-accent"
            >
              Use a different email
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
