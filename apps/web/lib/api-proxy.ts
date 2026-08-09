const hopByHopHeaders = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade"
]);

function apiBaseUrl(): URL {
  const value = process.env.API_INTERNAL_URL ?? "http://api:8000";
  const url = new URL(value);
  if (!(["http:", "https:"].includes(url.protocol)) || url.username || url.password) {
    throw new Error("API_INTERNAL_URL must be an HTTP(S) origin without credentials");
  }
  return url;
}

export async function proxyPublicGet(request: Request, pathname: string): Promise<Response> {
  const incomingUrl = new URL(request.url);
  const target = new URL(pathname, apiBaseUrl());
  target.search = incomingUrl.search;
  const requestHeaders = new Headers();
  for (const name of ["accept", "accept-encoding", "if-none-match", "last-event-id", "user-agent"]) {
    const value = request.headers.get(name);
    if (value) requestHeaders.set(name, value);
  }

  try {
    const upstream = await fetch(target, {
      cache: "no-store",
      headers: requestHeaders,
      method: request.method,
      redirect: "manual",
      signal: request.signal
    });
    const responseHeaders = new Headers();
    upstream.headers.forEach((value, name) => {
      if (!hopByHopHeaders.has(name.toLowerCase())) responseHeaders.set(name, value);
    });
    return new Response(request.method === "HEAD" ? null : upstream.body, {
      headers: responseHeaders,
      status: upstream.status,
      statusText: upstream.statusText
    });
  } catch {
    return Response.json(
      { detail: "Analytics API unavailable" },
      { status: 502, headers: { "Cache-Control": "no-store" } }
    );
  }
}
