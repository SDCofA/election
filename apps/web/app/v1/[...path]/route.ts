import { proxyPublicGet } from "@/lib/api-proxy";

type Context = { params: Promise<{ path: string[] }> };

async function handler(request: Request, { params }: Context) {
  const { path } = await params;
  const safePath = path.map((segment) => encodeURIComponent(segment)).join("/");
  return proxyPublicGet(request, `/v1/${safePath}`);
}

export const dynamic = "force-dynamic";
export const GET = handler;
export const HEAD = handler;
