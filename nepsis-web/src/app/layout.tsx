import "./globals.css";
import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { IBM_Plex_Mono, Space_Grotesk } from "next/font/google";

const nepsisSans = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-nepsis-sans",
  display: "swap",
  weight: ["400", "500", "600", "700"],
});

const nepsisMono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--font-nepsis-mono",
  display: "swap",
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "NepsisCGN",
  description: "Constraint Geometry Navigation for LLMs",
  icons: {
    icon: "/nepsis-logo.png",
  },
};

const navLinks = [
  { href: "/", label: "Overview" },
  { href: "/engine", label: "Engine" },
  { href: "/playground", label: "Playground" },
  { href: "/settings", label: "Settings" },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${nepsisSans.variable} ${nepsisMono.variable}`}>
      <body className="min-h-screen bg-nepsis-bg text-nepsis-text antialiased">
        <div className="flex min-h-screen flex-col">
          <header className="sticky top-0 z-30 border-b border-nepsis-border/70 bg-nepsis-bg/90 backdrop-blur">
            <div className="mx-auto flex w-full max-w-[1380px] flex-wrap items-center justify-between gap-3 px-4 py-3 md:px-6">
              <Link href="/" className="group flex items-center gap-2.5">
                <Image
                  src="/nepsis-logo.png"
                  alt="Nepsis logo"
                  width={34}
                  height={34}
                  className="h-[34px] w-[34px] rounded-md border border-nepsis-border/80 object-cover"
                  priority
                />
                <div>
                  <div className="text-[10px] font-semibold tracking-[0.22em] text-nepsis-muted">NEPSISCGN</div>
                  <div className="text-xs text-nepsis-muted/90 transition group-hover:text-nepsis-text">
                    Consequence-aware reasoning workspace
                  </div>
                </div>
              </Link>

              <nav className="flex flex-wrap items-center gap-1.5 text-sm">
                {navLinks.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="rounded-full border border-transparent px-3 py-1.5 text-nepsis-muted transition hover:border-nepsis-border hover:bg-nepsis-panel hover:text-nepsis-text"
                  >
                    {link.label}
                  </Link>
                ))}
                <Link
                  href="/login"
                  className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs font-semibold transition hover:border-nepsis-accent hover:text-nepsis-accent"
                >
                  Login
                </Link>
              </nav>
            </div>
          </header>

          <main className="flex-1">{children}</main>

          <footer className="border-t border-nepsis-border/70 bg-nepsis-bg/80 px-6 py-3 text-xs text-nepsis-muted">
            <div className="mx-auto flex w-full max-w-[1380px] items-center justify-between gap-2">
              <div>NepsisCGN · Constraint Geometry Navigation</div>
              <div>{new Date().getFullYear()}</div>
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}
