import type { NextConfig } from "next";

const githubPages = process.env.GITHUB_PAGES === "true";
const pagesBasePath = githubPages ? (process.env.PAGES_BASE_PATH ?? "") : "";

const nextConfig: NextConfig = {
  output: githubPages ? "export" : "standalone",
  basePath: pagesBasePath,
  assetPrefix: pagesBasePath || undefined,
  trailingSlash: githubPages,
  images: { unoptimized: githubPages },
  poweredByHeader: false,
  reactStrictMode: true
};

if (!githubPages) {
  nextConfig.headers = async () => [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          {
            key: "Content-Security-Policy",
            value: "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https: http://localhost:* http://127.0.0.1:*"
          }
        ]
      }
    ];
}

export default nextConfig;
