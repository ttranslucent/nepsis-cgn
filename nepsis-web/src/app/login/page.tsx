"use client";

import { FormEvent, useEffect, useState } from "react";

type LoginStatusPayload = {
  auth?: {
    loginConfigured: boolean;
    authSecretConfigured?: boolean;
    authSecretMode?: "configured" | "development-fallback" | "missing";
    emailConfigured?: boolean;
    previewCodesEnabled: boolean;
    operatorLoginReady?: boolean;
  };
  mvp?: {
    available?: boolean;
    noLoginRequired?: boolean;
    schemaId?: string | null;
  };
};

function envFlagValue(value: string | undefined): boolean {
  const normalized = value?.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

function envFalseValue(value: string | undefined): boolean {
  const normalized = value?.trim().toLowerCase();
  return normalized === "0" || normalized === "false" || normalized === "no" || normalized === "off";
}

const PUBLIC_SITE_VALUE = process.env.NEXT_PUBLIC_NEPSIS_PUBLIC_SITE;
const OPERATOR_SITE_MODE = envFlagValue(process.env.NEXT_PUBLIC_NEPSIS_OPERATOR_SITE);
const PUBLIC_SITE_MODE =
  !OPERATOR_SITE_MODE &&
  (envFlagValue(PUBLIC_SITE_VALUE) || (!envFalseValue(PUBLIC_SITE_VALUE) && process.env.NODE_ENV === "production"));

function operatorLoginReady(status: LoginStatusPayload | null): boolean {
  const auth = status?.auth;
  if (!auth) {
    return false;
  }
  return auth.operatorLoginReady ?? (auth.loginConfigured && (Boolean(auth.emailConfigured) || auth.previewCodesEnabled));
}

function ReadinessNotice({
  status,
  error,
}: {
  status: LoginStatusPayload | null;
  error: string | null;
}) {
  if (!status && !error) {
    return (
      <div className="mb-4 border-l-2 border-nepsis-border pl-3 text-xs leading-5 text-nepsis-muted">
        Checking operator sign-in readiness...
      </div>
    );
  }

  if (error) {
    return (
      <div className="mb-4 border-l-2 border-amber-400/70 pl-3 text-xs leading-5 text-amber-100">
        <p className="font-semibold text-nepsis-text">Operator sign-in readiness could not be checked.</p>
        <p>The server will still enforce whether code delivery is available.</p>
      </div>
    );
  }

  const auth = status?.auth;
  const emailConfigured = Boolean(auth?.emailConfigured);
  const previewCodesEnabled = Boolean(auth?.previewCodesEnabled);
  const ready = operatorLoginReady(status);

  if (!ready) {
    return (
      <div className="mb-4 border-l-2 border-amber-400/70 pl-3 text-xs leading-5 text-amber-100">
        <p className="font-semibold text-nepsis-text">
          {PUBLIC_SITE_MODE
            ? "Operator sign-in is intentionally unavailable on this public deployment."
            : "Operator sign-in is not ready in this environment."}
        </p>
        {!emailConfigured && !previewCodesEnabled && (
          <p>Real login emails are not configured, and local preview-code mode is disabled here.</p>
        )}
        {auth && !auth.loginConfigured && <p>Auth cookies are not configured for operator sessions.</p>}
        <p>The frozen /mvp demo remains available without login or model keys.</p>
        <a className="inline-flex text-nepsis-accent transition hover:text-nepsis-accentSoft" href="/mvp">
          Run frozen MVP demo
        </a>
      </div>
    );
  }

  if (emailConfigured) {
    return (
      <div className="mb-4 border-l-2 border-emerald-400/70 pl-3 text-xs leading-5 text-emerald-100">
        <p className="font-semibold text-nepsis-text">Real email delivery is configured.</p>
        <p>Operator codes will be sent to the email address you enter.</p>
        <p>
          {previewCodesEnabled
            ? "Local preview-code mode is enabled only as a fallback if email delivery fails."
            : "Local preview-code mode is off."}
        </p>
      </div>
    );
  }

  return (
    <div className="mb-4 border-l-2 border-sky-400/70 pl-3 text-xs leading-5 text-sky-100">
      <p className="font-semibold text-nepsis-text">Local preview-code mode is enabled.</p>
      <p>No email will be sent; this page will show the one-time code after Send code.</p>
    </div>
  );
}

export default function LoginPage() {
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [delivery, setDelivery] = useState<"email" | "preview" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [status, setStatus] = useState<LoginStatusPayload | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const trimmedEmail = email.trim();
  const checkingStatus = !status && !statusError;
  const signInUnavailable = Boolean(status) && !operatorLoginReady(status);
  const emailInputDisabled = loading || checkingStatus || signInUnavailable;
  const sendDisabled = emailInputDisabled || !trimmedEmail;

  useEffect(() => {
    let cancelled = false;
    async function loadStatus() {
      try {
        const response = await fetch("/api/status", { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`Status check failed (${response.status}).`);
        }
        const payload = (await response.json()) as LoginStatusPayload;
        if (!cancelled) {
          setStatus(payload);
          setStatusError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setStatusError((err as Error)?.message ?? "Status check failed.");
        }
      }
    }
    void loadStatus();
    return () => {
      cancelled = true;
    };
  }, []);

  async function sendCode() {
    if (!trimmedEmail || checkingStatus || signInUnavailable) {
      return;
    }
    setLoading(true);
    setMessage(null);
    setDelivery(null);
    try {
      const res = await fetch("/api/auth/request-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: trimmedEmail }),
      });
      const data = await res.json();
      if (res.ok) {
        setEmail(trimmedEmail);
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

  function handleEmailSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendCode();
  }

  function handleCodeSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void verifyCode();
  }

  return (
    <div className="flex items-center justify-center py-16">
      <div className="w-full max-w-sm rounded-xl border border-nepsis-border bg-nepsis-panel p-6 shadow-2xl shadow-black/40">
        <h1 className="mb-2 text-lg font-semibold">Login to NepsisCGN</h1>
        <p className="mb-4 text-xs text-nepsis-muted">
          Passwordless operator login uses the deployment&apos;s configured code-delivery mode.
        </p>
        <ReadinessNotice status={status} error={statusError} />

        {step === "email" ? (
          <form className="space-y-3" onSubmit={handleEmailSubmit}>
            <div>
              <label className="mb-1 block text-xs" htmlFor="nepsis-login-email">
                Email
              </label>
              <input
                id="nepsis-login-email"
                className="w-full rounded-lg border border-nepsis-border bg-black/30 px-3 py-2 text-sm focus:border-nepsis-accent focus:outline-none"
                type="email"
                autoComplete="email"
                value={email}
                disabled={emailInputDisabled}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
            </div>
            <button
              type="submit"
              disabled={sendDisabled}
              className="w-full rounded-full bg-nepsis-accent py-2 text-sm font-medium text-black transition hover:bg-nepsis-accentSoft disabled:opacity-60"
            >
              {loading ? "Sending..." : checkingStatus ? "Checking..." : "Send code"}
            </button>
          </form>
        ) : (
          <form className="space-y-3" onSubmit={handleCodeSubmit}>
            <p className="text-xs text-nepsis-muted">
              {delivery === "preview" ? "Use the preview code for" : "We’ve sent a code to"}{" "}
              <span className="font-mono">{email}</span>.
            </p>
            <div>
              <label className="mb-1 block text-xs" htmlFor="nepsis-login-code">
                Code
              </label>
              <input
                id="nepsis-login-code"
                className="w-full rounded-lg border border-nepsis-border bg-black/30 px-3 py-2 text-center text-sm font-mono tracking-[0.3em] focus:border-nepsis-accent focus:outline-none"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="123456"
                autoComplete="one-time-code"
                inputMode="numeric"
                maxLength={6}
              />
            </div>
            <button
              type="submit"
              disabled={loading || code.trim().length === 0}
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
          </form>
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
