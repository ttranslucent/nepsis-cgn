"use client";

import { useEffect, useState } from "react";

import { consumeConnectedNotice, hasStoredOpenAiKey } from "@/lib/clientStorage";

export default function HomePage() {
  const [hasKey, setHasKey] = useState(false);
  const [showConnectedMessage, setShowConnectedMessage] = useState(false);

  useEffect(() => {
    const connectedFromQuery =
      typeof window !== "undefined" && new URLSearchParams(window.location.search).get("connected") === "1";
    const connectedFromNotice = consumeConnectedNotice();
    setShowConnectedMessage(connectedFromQuery || connectedFromNotice);
    setHasKey(hasStoredOpenAiKey());
  }, []);

  const primaryHref = hasKey ? "/engine" : "/settings";
  const primaryLabel = hasKey ? "Open Engine Workspace" : "Connect Model Key";

  return (
    <div className="mx-auto w-full max-w-[1380px] px-4 py-8 md:px-6 md:py-12">
      {showConnectedMessage && (
        <div className="mb-5 rounded-2xl border border-emerald-400/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">
          LLM connected successfully. Nepsis Engine is ready.
        </div>
      )}

      <section className="grid gap-5 lg:grid-cols-[1.25fr_0.95fr]">
        <article className="overflow-hidden rounded-3xl border border-nepsis-border bg-nepsis-panel p-6 md:p-8">
          <div className="inline-flex items-center gap-2 rounded-full border border-nepsis-border bg-black/20 px-3 py-1 text-[11px] uppercase tracking-[0.16em] text-nepsis-muted">
            Frontier model workflow
          </div>
          <h1 className="mt-4 text-3xl font-semibold leading-tight md:text-5xl">
            Build decisions, not just answers.
          </h1>
          <p className="mt-4 max-w-2xl text-sm text-nepsis-muted md:text-base">
            NepsisCGN guides users through Priors, Interpretation, and Threshold gating so high-risk reasoning remains
            explicit, auditable, and reversible.
          </p>

          <div className="mt-6 flex flex-wrap gap-3">
            <a
              href={primaryHref}
              className="rounded-full bg-nepsis-accent px-5 py-2.5 text-sm font-semibold text-black transition hover:bg-nepsis-accentSoft"
            >
              {primaryLabel}
            </a>
            <a
              href="/playground"
              className="rounded-full border border-nepsis-border px-5 py-2.5 text-sm text-nepsis-text transition hover:border-nepsis-accent"
            >
              Open Playground
            </a>
            <a
              href="/engine"
              className="rounded-full border border-nepsis-border px-5 py-2.5 text-sm text-nepsis-text transition hover:border-nepsis-accent"
            >
              Engine Console
            </a>
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-nepsis-border bg-black/20 p-3">
              <div className="text-[11px] uppercase tracking-[0.14em] text-nepsis-muted">Frame Contract</div>
              <div className="mt-1 text-sm">Require priors, risks, objectives, and uncertainty.</div>
            </div>
            <div className="rounded-xl border border-nepsis-border bg-black/20 p-3">
              <div className="text-[11px] uppercase tracking-[0.14em] text-nepsis-muted">Interpretation Pass</div>
              <div className="mt-1 text-sm">Force evidence linkage and contradiction declaration.</div>
            </div>
            <div className="rounded-xl border border-nepsis-border bg-black/20 p-3">
              <div className="text-[11px] uppercase tracking-[0.14em] text-nepsis-muted">Threshold Gate</div>
              <div className="mt-1 text-sm">Apply red/blue policy before action recommendations.</div>
            </div>
          </div>
        </article>

        <aside className="rounded-3xl border border-nepsis-border bg-nepsis-panel p-6 md:p-7">
          <h2 className="text-lg font-semibold">MVP Readiness</h2>
          <p className="mt-2 text-sm text-nepsis-muted">
            Current build includes backend stage-audit policy enforcement, timeline lineage, and adversarial gate tests.
          </p>

          <div className="mt-5 space-y-3">
            <div className="rounded-xl border border-nepsis-border bg-black/20 p-3">
              <div className="text-xs text-nepsis-muted">Gate workflow tests</div>
              <div className="mt-1 font-mono text-sm text-nepsis-accent">PASS</div>
            </div>
            <div className="rounded-xl border border-nepsis-border bg-black/20 p-3">
              <div className="text-xs text-nepsis-muted">Adversarial scenarios</div>
              <div className="mt-1 font-mono text-sm text-nepsis-accent">Vague / Contradiction / Red-override</div>
            </div>
            <div className="rounded-xl border border-nepsis-border bg-black/20 p-3">
              <div className="text-xs text-nepsis-muted">Policy tag</div>
              <div className="mt-1 font-mono text-sm text-nepsis-accent">nepsis_cgn.stage_audit@2026-03-10</div>
            </div>
          </div>

          <a
            href="/engine"
            className="mt-5 inline-flex rounded-full border border-nepsis-border px-4 py-2 text-sm transition hover:border-nepsis-accent"
          >
            Run Engine QA
          </a>
        </aside>
      </section>
    </div>
  );
}
