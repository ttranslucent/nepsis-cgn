import { engineErrorResponse, proxyEngineRequest, proxyJsonResponse } from "@/lib/engineApi";

export const runtime = "nodejs";

export async function GET() {
  try {
    const upstream = await proxyEngineRequest("/v1/health", { method: "GET" });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return engineErrorResponse(error);
  }
}
