import { MetadataRoute } from "next";
import { getServices } from "@/lib/db";

const BASE_URL =
  process.env.NEXT_PUBLIC_BASE_URL || "http://34-28-191-224.sslip.io";

// Disable static generation — this route depends on runtime DB state. When
// the DB isn't reachable at build time (local dev without Postgres, or a
// deploy that builds the frontend on a box that can't see the production
// DB), prerender would otherwise hard-fail the whole build.
export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  let services: Awaited<ReturnType<typeof getServices>> = [];
  try {
    services = await getServices();
  } catch {
    // DB unreachable at sitemap generation time — emit the static entries
    // so at least the core pages are indexable. Service pages will come
    // back on the next regeneration tick.
  }

  const serviceUrls: MetadataRoute.Sitemap = services.map((s) => ({
    url: `${BASE_URL}/services/${s.slug}`,
    lastModified: new Date(s.updated_at),
    changeFrequency: "weekly",
    priority: s.status === "verified" ? 0.8 : 0.5,
  }));

  return [
    { url: BASE_URL, lastModified: new Date(), changeFrequency: "daily", priority: 1 },
    { url: `${BASE_URL}/submit`, lastModified: new Date(), changeFrequency: "monthly", priority: 0.6 },
    { url: `${BASE_URL}/methodology`, lastModified: new Date(), changeFrequency: "monthly", priority: 0.7 },
    { url: `${BASE_URL}/api-docs`, lastModified: new Date(), changeFrequency: "monthly", priority: 0.6 },
    { url: `${BASE_URL}/terms`, lastModified: new Date(), changeFrequency: "yearly", priority: 0.3 },
    { url: `${BASE_URL}/privacy`, lastModified: new Date(), changeFrequency: "yearly", priority: 0.3 },
    ...serviceUrls,
  ];
}
