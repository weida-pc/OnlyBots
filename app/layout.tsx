import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Nav from "@/components/nav";
import Footer from "@/components/footer";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const BASE_URL =
  process.env.NEXT_PUBLIC_BASE_URL || "http://34-28-191-224.sslip.io";

export const metadata: Metadata = {
  metadataBase: new URL(BASE_URL),
  title: "OnlyBots — Trust Registry for Agent-First Services",
  description:
    "Verified directory of services AI agents can autonomously sign up for, own, and operate.",
  openGraph: {
    title: "OnlyBots — Trust Registry for Agent-First Services",
    description:
      "Verified directory of services AI agents can autonomously sign up for, own, and operate.",
    url: BASE_URL,
    siteName: "OnlyBots",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "OnlyBots — Trust Registry for Agent-First Services",
    description:
      "Verified directory of services AI agents can autonomously sign up for, own, and operate.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-slate-50 text-slate-900 min-h-screen flex flex-col`}
      >
        <Nav />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
