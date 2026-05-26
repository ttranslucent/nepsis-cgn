import {
  engineControlOwner,
  engineErrorResponse,
  proxyEngineRequest,
  proxyJsonResponse,
  requireEngineControlAuth,
} from "@/lib/engineApi";

export const runtime = "nodejs";

type RouteParams = { params: Promise<{ tool: string[] }> };

function operatorPacketPath(tool: string[]): string {
  return `/v1/operator-packet/${tool.map((part) => encodeURIComponent(part)).join("/")}`;
}

export async function POST(req: Request, { params }: RouteParams) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const owner = engineControlOwner(req);
  const { tool } = await params;
  const body = await req.text();
  try {
    const upstream = await proxyEngineRequest(
      operatorPacketPath(tool),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      },
      { owner },
    );
    return proxyJsonResponse(upstream);
  } catch (error) {
    return engineErrorResponse(error);
  }
}
