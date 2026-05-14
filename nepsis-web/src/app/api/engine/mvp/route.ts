import { engineErrorResponse, proxyEngineRequest, proxyJsonResponse } from "@/lib/engineApi";

export const runtime = "nodejs";

export async function POST(req: Request) {
  const body = await req.text();
  try {
    const upstream = await proxyEngineRequest("/v1/mvp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return engineErrorResponse(error);
  }
}
