import Link from "next/link";
import { getServices } from "@/lib/db";
import ServiceGrid from "@/components/service-grid";
import type { Service } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const services: Service[] = await getServices();

  const total = services.length;
  const verified = services.filter((s) => s.status === "verified").length;
  const failed = services.filter((s) => s.status === "failed").length;
  const pending = services.filter((s) => s.status === "pending").length;

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Hero */}
      <section className="max-w-4xl mx-auto text-center py-16">
        <h1 className="text-4xl font-bold text-slate-900 mb-4">
          Trust Registry for Agent-First Services
        </h1>
        <p className="text-xl text-slate-600 mb-8">
          Which services can an AI agent actually sign up for, own, and operate?
        </p>
        <div className="flex flex-wrap gap-3 justify-center">
          <a
            href="#registry"
            className="inline-flex items-center px-5 py-2.5 rounded-md border border-slate-300 text-sm font-semibold text-slate-700 bg-white hover:bg-slate-50 hover:border-slate-400 transition-colors"
          >
            Browse Registry
          </a>
          <Link
            href="/submit"
            className="inline-flex items-center px-5 py-2.5 rounded-md text-sm font-semibold text-white bg-green-600 hover:bg-green-700 transition-colors"
          >
            Submit a Service
          </Link>
        </div>
      </section>

      {/* Stats bar */}
      <section className="mb-12">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="bg-white border border-slate-200 rounded-lg p-5 text-center">
            <div className="text-3xl font-bold text-slate-900">{total}</div>
            <div className="text-sm text-slate-500 mt-1">Total Services</div>
          </div>
          <div className="bg-white border border-slate-200 rounded-lg p-5 text-center">
            <div className="text-3xl font-bold text-green-600">{verified}</div>
            <div className="text-sm text-slate-500 mt-1">Verified</div>
          </div>
          <div className="bg-white border border-slate-200 rounded-lg p-5 text-center">
            <div className="text-3xl font-bold text-red-600">{failed}</div>
            <div className="text-sm text-slate-500 mt-1">Failed</div>
          </div>
          <div className="bg-white border border-slate-200 rounded-lg p-5 text-center">
            <div className="text-3xl font-bold text-amber-600">{pending}</div>
            <div className="text-sm text-slate-500 mt-1">Pending</div>
          </div>
        </div>
      </section>

      {/* Registry */}
      <section id="registry" className="mb-16">
        <h2 className="text-xl font-semibold text-slate-900 mb-6">Registry</h2>
        <ServiceGrid initialServices={services} />
      </section>

      {/* Discovery links */}
      <section className="border-t border-slate-200 pt-8 text-center">
        <p className="text-sm text-slate-400 mb-2">Machine-readable endpoints</p>
        <div className="flex flex-wrap gap-x-4 gap-y-1 justify-center text-sm text-slate-400">
          <a href="/api/services" className="hover:text-slate-600 transition-colors font-mono">
            /api/services
          </a>
          <span className="select-none">&middot;</span>
          <a href="/api/schema" className="hover:text-slate-600 transition-colors font-mono">
            /api/schema
          </a>
          <span className="select-none">&middot;</span>
          <a href="/.well-known/onlybots.json" className="hover:text-slate-600 transition-colors font-mono">
            /.well-known/onlybots.json
          </a>
          <span className="select-none">&middot;</span>
          <Link href="/methodology" className="hover:text-slate-600 transition-colors">
            Methodology
          </Link>
        </div>
      </section>
    </div>
  );
}
