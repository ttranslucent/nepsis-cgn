export default function HomePage() {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-16 text-center">
      <h1 className="mb-4 text-3xl font-semibold md:text-4xl">
        NepsisCGN · Constraint Geometry Navigation
      </h1>
      <p className="mb-8 max-w-xl text-nepsis-muted">
        Run your own LLM through NepsisCGN and see constraint geometry in action.
        Connect your model, select a manifold, and watch Nepsis evaluate and repair
        outputs in real time.
      </p>
      <div className="flex flex-wrap items-center justify-center gap-4">
        <a
          href="/playground"
          className="rounded-full bg-nepsis-accent px-5 py-2 text-sm font-medium text-black hover:bg-nepsis-accentSoft"
        >
          Open Playground
        </a>
        <a
          href="/settings"
          className="rounded-full border border-nepsis-border px-5 py-2 text-sm hover:border-nepsis-accent"
        >
          Connect LLM
        </a>
      </div>
    </div>
  );
}
