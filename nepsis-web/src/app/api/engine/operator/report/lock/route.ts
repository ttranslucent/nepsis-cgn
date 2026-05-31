import {
  engineControlOwner,
  engineErrorResponse,
  proxyEngineRequest,
  proxyJsonResponse,
  requireEngineControlAuth,
} from "@/lib/engineApi";
import { requireCsrfToken } from "@/lib/requestSecurity";

export const runtime = "nodejs";

export async function POST(req: Request) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const csrfFailure = requireCsrfToken(req);
  if (csrfFailure) {
    return csrfFailure;
  }
  const owner = engineControlOwner(req);
  try {
    const upstream = await proxyEngineRequest("/v1/operator/report/lock", { method: "POST" }, { owner });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return engineErrorResponse(error);
  }
}
