"use client";

const BREADCRUMB_NODE_IDS: Record<string, string> = {
  Source: "source",
  RED: "red",
  STILL: "still",
  BLUE: "blue",
  Collapse: "collapse",
  Validation: "validation",
  Output: "output",
};

export function ProvenanceBreadcrumbs({
  breadcrumbs,
  activeNodeId,
  onFocusNode,
}: {
  breadcrumbs: string[];
  activeNodeId: string | null;
  onFocusNode: (nodeId: string) => void;
}) {
  return (
    <nav
      aria-label="Provenance breadcrumbs"
      className="overflow-x-auto border-b border-slate-800/80 pb-3"
    >
      <ol className="flex min-w-max items-center gap-1 whitespace-nowrap text-xs">
        {breadcrumbs.map((breadcrumb, index) => {
          const nodeId = BREADCRUMB_NODE_IDS[breadcrumb] ?? breadcrumb.toLowerCase();
          const selected = activeNodeId === nodeId;
          return (
            <li key={breadcrumb} className="flex items-center gap-1">
              {index > 0 ? <span className="text-slate-600">&gt;</span> : null}
              <button
                type="button"
                aria-label={`Focus ${breadcrumb}`}
                aria-current={selected ? "step" : undefined}
                onClick={() => onFocusNode(nodeId)}
                className={`scroll-mt-40 rounded-md border px-2.5 py-1.5 font-mono uppercase tracking-[0.12em] transition focus:outline-none focus:ring-2 focus:ring-sky-300/50 ${
                  selected
                    ? "border-sky-300/55 bg-sky-400/10 text-sky-100"
                    : "border-transparent text-slate-400 hover:border-slate-600 hover:text-slate-100"
                }`}
              >
                {breadcrumb}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
