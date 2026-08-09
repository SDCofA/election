const apiOrigin = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
const basePath = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");

export function publicEndpoint(path: string): string {
  return apiOrigin ? `${apiOrigin}${path}` : `${basePath}/data${path}.json`;
}

export function publicAsset(path: string): string {
  return `${basePath}${path}`;
}
