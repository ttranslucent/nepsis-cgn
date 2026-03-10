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

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col items-center justify-center gap-4 px-4 py-14 text-center">
      {showConnectedMessage && (
        <div className="w-full rounded-xl border border-green-500/40 bg-green-500/10 px-4 py-3 text-sm text-green-200">
          LLM connected successfully. You can start in the Engine workspace now.
        </div>
      )}
      <h1 className="mb-4 text-3xl font-semibold md:text-4xl">
        NepsisCGN · Constraint Geometry Navigation
      </h1>
      <p className="mb-8 max-w-2xl text-nepsis-muted">
        Bring your own model key, frame a problem, run structured reports, and iterate priors with
        a guided Nepsis workflow.
      </p>
      <div className="flex flex-wrap items-center justify-center gap-4">
        <a
          href={hasKey ? "/engine" : "/settings"}
          className="rounded-full bg-nepsis-accent px-5 py-2 text-sm font-medium text-black hover:bg-nepsis-accentSoft"
        >
          {hasKey ? "Open Engine Workspace" : "Connect LLM"}
        </a>
        <a
          href="/playground"
          className="rounded-full border border-nepsis-border px-5 py-2 text-sm hover:border-nepsis-accent"
        >
          Open Playground
        </a>
        <a
          href="/engine"
          className="rounded-full border border-nepsis-border px-5 py-2 text-sm hover:border-nepsis-accent"
        >
          Open Engine Console
        </a>
      </div>
    </div>
  );
}
