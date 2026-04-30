import Link from "next/link";

const navLinks = [
  { label: "Registry", href: "/" },
  { label: "Submit", href: "/submit" },
  { label: "Issues", href: "/issues" },
  { label: "Methodology", href: "/methodology" },
  { label: "API Docs", href: "/api-docs" },
];

export default function Nav() {
  return (
    <header className="sticky top-0 z-50 w-full bg-white border-b border-slate-200">
      <div className="mx-auto max-w-7xl px-6 lg:px-8">
        <div className="flex h-14 items-center justify-between">
          <Link
            href="/"
            className="text-base font-bold tracking-tight text-slate-900 hover:text-green-600 transition-colors"
          >
            OnlyBots
          </Link>

          <nav className="flex items-center gap-1">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="px-3 py-1.5 text-sm font-medium text-slate-600 rounded hover:text-slate-900 hover:bg-slate-50 transition-colors"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </header>
  );
}
