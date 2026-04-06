"use client";

import { useState, useEffect, useCallback } from "react";
import type { Service } from "@/lib/types";
import ServiceCard from "@/components/service-card";
import { cn } from "@/lib/utils";
import { Search } from "lucide-react";

const CATEGORIES = ["All", "Communication", "Execution", "Hosting"] as const;
type Category = (typeof CATEGORIES)[number];

interface ServiceGridProps {
  initialServices: Service[];
}

export default function ServiceGrid({ initialServices }: ServiceGridProps) {
  const [services, setServices] = useState<Service[]>(initialServices);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<Category>("All");
  const [loading, setLoading] = useState(false);

  const fetchServices = useCallback(async (q: string, cat: Category) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (q.trim()) params.set("q", q.trim());
      if (cat !== "All") params.set("category", cat);

      const res = await fetch(`/api/services?${params.toString()}`);
      if (!res.ok) throw new Error("Fetch failed");
      const data: Service[] = await res.json();
      setServices(data);
    } catch {
      // silently retain previous results on error
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Debounce query changes
    const timer = setTimeout(() => {
      fetchServices(query, category);
    }, 300);
    return () => clearTimeout(timer);
  }, [query, category, fetchServices]);

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-4">
        {/* Search */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 pointer-events-none" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search services..."
            className={cn(
              "w-full pl-9 pr-4 py-2 text-sm rounded-md",
              "border border-slate-200 bg-white text-slate-900 placeholder-slate-400",
              "focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent",
              "transition"
            )}
          />
        </div>

        {/* Category filters */}
        <div className="flex items-center gap-2 flex-wrap">
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              className={cn(
                "px-3 py-2 text-sm font-medium rounded-md border transition-colors",
                category === cat
                  ? "bg-green-600 text-white border-green-600"
                  : "bg-white text-slate-600 border-slate-200 hover:border-slate-300 hover:text-slate-900"
              )}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Grid */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <span className="text-sm text-slate-400">Loading...</span>
        </div>
      ) : services.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <p className="text-slate-500 text-sm">No services found.</p>
          <p className="text-slate-400 text-xs mt-1">
            Try adjusting your search or category filter.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {services.map((service) => (
            <ServiceCard key={service.id} service={service} />
          ))}
        </div>
      )}
    </div>
  );
}
