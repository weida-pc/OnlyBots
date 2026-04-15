import { MetadataRoute } from "next";
import { getServices } from "@/lib/db";

const BASE_URL =
  process.env.NEXT_PUBLIC_BASE_URL || "http://34-28-191-224.sslip.io";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const services = await getServices();

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
