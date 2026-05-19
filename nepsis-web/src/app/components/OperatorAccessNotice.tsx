type OperatorAccessNoticeProps = {
  title?: string;
  message?: string;
  checking?: boolean;
};

export function OperatorAccessNotice({
  title = "Operator access required",
  message = "This area is for signed-in NepsisCGN operators. The public deterministic MVP demo remains available without login or model keys.",
  checking = false,
}: OperatorAccessNoticeProps) {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-10 md:px-6 md:py-16">
      <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-6 md:p-7">
        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-nepsis-muted">
          {checking ? "Checking access" : "Public site mode"}
        </div>
        <h1 className="mt-3 text-2xl font-semibold">{checking ? "Checking operator access..." : title}</h1>
        <p className="mt-3 text-sm leading-6 text-nepsis-muted">{message}</p>
        <div className="mt-5 flex flex-wrap gap-2">
          <a
            href="/mvp"
            className="rounded-full bg-nepsis-accent px-4 py-2 text-sm font-semibold text-black transition hover:bg-nepsis-accentSoft"
          >
            Run MVP Demo
          </a>
          <a
            href="/login"
            className="rounded-full border border-nepsis-border px-4 py-2 text-sm transition hover:border-nepsis-accent"
          >
            Operator Login
          </a>
          <a
            href="/status"
            className="rounded-full border border-nepsis-border px-4 py-2 text-sm transition hover:border-nepsis-accent"
          >
            System Status
          </a>
        </div>
      </section>
    </div>
  );
}
