import Link from "next/link";
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Avito Automation Operator",
  description: "Internal operator console"
};

const links = [
  ["/", "Dashboard"],
  ["/products", "Products"],
  ["/imports", "Imports"],
  ["/onboarding", "Onboarding"],
  ["/review", "Review"],
  ["/publication", "Publication"],
  ["/suppliers", "Suppliers"],
  ["/sources", "Sources"],
  ["/inventory", "Inventory"],
  ["/pricing", "Pricing"],
  ["/alerts", "Alerts"],
  ["/audit", "Audit"],
  ["/settings", "Settings"]
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <nav className="nav" aria-label="Operator navigation">
            <p className="brand">avito-automation</p>
            {links.map(([href, label]) => (
              <Link key={href} href={href}>
                {label}
              </Link>
            ))}
            <Link href="/login">Login</Link>
          </nav>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
