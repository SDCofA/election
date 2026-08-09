import { proxyPublicGet } from "@/lib/api-proxy";

export const dynamic = "force-dynamic";

export function GET(request: Request) {
  return proxyPublicGet(request, "/docs");
}

export function HEAD(request: Request) {
  return proxyPublicGet(request, "/docs");
}
