import {
  engineControlOwner,
  isEngineConfigurationError,
  proxyEngineRequest,
  requireEngineControlAuth,
} from "@/lib/engineApi";

export const runtime = "nodejs";

const REQUIRED_V3_ROUTES = [
  "/v1/operator-packet/v3/start",
  "/v1/operator-packet/v3/field",
  "/v1/operator-packet/v3/propose",
  "/v1/operator-packet/v3/lock",
] as const;

type RouteManifestEntry = {
  method?: unknown;
  path?: unknown;
};

type RouteProbe = {
  path: string;
  status: number | null;
  reachable: boolean;
  detail?: string;
};

function capabilityResponse(
  presentRoutes: string[],
  detail?: string,
  routeManifestStatus?: number | null,
  routeProbes: RouteProbe[] = [],
) {
  const missingRoutes = REQUIRED_V3_ROUTES.filter((route) => !presentRoutes.includes(route));
  const unreachableRoutes = routeProbes
    .filter((probe) => !probe.reachable)
    .map((probe) => probe.path);
  const available = missingRoutes.length === 0 && unreachableRoutes.length === 0;
  return Response.json({
    schema_id: "nepsis.operator_v3_backend_capability",
    schema_version: "1.0.0",
    available,
    source: "backend_route_manifest",
    required_routes: REQUIRED_V3_ROUTES,
    present_routes: presentRoutes,
    missing_routes: missingRoutes,
    unreachable_routes: unreachableRoutes,
    route_probes: routeProbes,
    checked_at: new Date().toISOString(),
    route_manifest_status: routeManifestStatus ?? null,
    detail:
      detail ??
      (available
        ? "Backend route manifest includes all operator V3 layer-loop routes and each route answered the reachability probe."
        : "Backend route manifest or route reachability probe is missing operator V3 layer-loop support."),
  });
}

async function responsePayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

async function probeBackendRoute(path: string, owner: string | null): Promise<RouteProbe> {
  try {
    const response = await proxyEngineRequest(
      path,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        cache: "no-store",
      },
      { owner },
    );
    await response.text().catch(() => "");
    return {
      path,
      status: response.status,
      reachable: response.status === 400 || response.status === 422,
    };
  } catch (error) {
    return {
      path,
      status: null,
      reachable: false,
      detail: (error as Error)?.message ?? "Route reachability probe failed.",
    };
  }
}

export async function GET(req: Request) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) return unauthorized;

  const owner = engineControlOwner(req);
  try {
    const upstream = await proxyEngineRequest(
      "/v1/routes",
      { method: "GET", cache: "no-store" },
      { owner },
    );
    const payload = await responsePayload(upstream);
    if (!upstream.ok) {
      const detail =
        typeof payload === "string"
          ? payload
          : "Backend route manifest request failed.";
      return capabilityResponse([], detail, upstream.status);
    }
    const routes =
      typeof payload === "object" &&
      payload !== null &&
      Array.isArray((payload as { routes?: unknown }).routes)
        ? ((payload as { routes: RouteManifestEntry[] }).routes)
        : [];
    const presentRoutes = REQUIRED_V3_ROUTES.filter((requiredPath) =>
      routes.some(
        (route) =>
          route.method === "POST" &&
          route.path === requiredPath,
      ),
    );
    const missingRoutes = REQUIRED_V3_ROUTES.filter((route) => !presentRoutes.includes(route));
    if (missingRoutes.length > 0) {
      return capabilityResponse(presentRoutes, undefined, upstream.status);
    }
    const routeProbes = await Promise.all(
      REQUIRED_V3_ROUTES.map((route) => probeBackendRoute(route, owner)),
    );
    return capabilityResponse(presentRoutes, undefined, upstream.status, routeProbes);
  } catch (error) {
    const detail = isEngineConfigurationError(error)
      ? error.message
      : ((error as Error)?.message ?? "Backend route manifest request failed.");
    return capabilityResponse([], detail, null);
  }
}
