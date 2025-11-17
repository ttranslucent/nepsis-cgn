import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "NepsisCGN",
  description: "Constraint Geometry Navigation for LLMs",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-nepsis-bg text-nepsis-text">
        <div className="flex min-h-screen flex-col">
          <header className="flex items-center justify-between border-b border-nepsis-border px-6 py-3">
            <div className="flex items-center gap-2">
              <div className="h-7 w-7 rounded-full bg-gradient-to-tr from-nepsis-accent to-nepsis-accentSoft" />
              <span className="text-xs font-semibold tracking-[0.18em] text-nepsis-muted">
                NEPSISCGN
              </span>
            </div>
            <div className="flex items-center gap-4 text-sm">
              <a href="/playground" className="hover:text-nepsis-accent">
                Playground
              </a>
              <a href="/proto-puzzle" className="hover:text-nepsis-accent">
                Proto Puzzle
              </a>
              <a href="/settings" className="hover:text-nepsis-accent">
                Settings
              </a>
              <a
                href="/login"
                className="rounded-full border border-nepsis-border px-3 py-1 text-xs hover:border-nepsis-accent"
              >
                Login
              </a>
            </div>
          </header>
          <main className="flex-1">{children}</main>
          <footer className="border-t border-nepsis-border px-6 py-3 text-xs text-nepsis-muted">
            NepsisCGN · Constraint Geometry Navigation · 2025
          </footer>
        </div>
      </body>
    </html>
  );
}
