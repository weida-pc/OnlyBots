import Link from "next/link";

const footerLinks = [
  { label: "Methodology", href: "/methodology" },
  { label: "API Docs", href: "/api-docs" },
  { label: "GitHub", href: "https://github.com/weida-pc/OnlyBots" },
  { label: "Terms", href: "/terms" },
  { label: "Privacy", href: "/privacy" },
];

export default function Footer() {
  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="mx-auto max-w-7xl px-6 lg:px-8 py-8">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <p className="text-sm text-slate-500">
            OnlyBots &mdash; Trust Registry for Agent-First Services
          </p>

          <nav className="flex items-center gap-5">
            {footerLinks.map((link) => (
              <Link
                key={link.label}
                href={link.href}
                className="text-sm text-slate-400 hover:text-slate-600 transition-colors"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </footer>
  );
}
