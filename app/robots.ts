import { MetadataRoute } from "next";

const BASE_URL =
  process.env.NEXT_PUBLIC_BASE_URL || "http://34-28-191-224.sslip.io";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: "*", allow: "/", disallow: ["/api/webhook/"] },
    ],
    sitemap: `${BASE_URL}/sitemap.xml`,
  };
}
