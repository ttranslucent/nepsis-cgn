function envValue(name: string): string {
  if (name === "NEXT_PUBLIC_NEPSIS_PUBLIC_SITE") {
    return process.env.NEXT_PUBLIC_NEPSIS_PUBLIC_SITE?.trim().toLowerCase() ?? "";
  }
  if (name === "NEXT_PUBLIC_NEPSIS_OPERATOR_SITE") {
    return process.env.NEXT_PUBLIC_NEPSIS_OPERATOR_SITE?.trim().toLowerCase() ?? "";
  }
  return process.env[name]?.trim().toLowerCase() ?? "";
}

export function envFlag(name: string): boolean {
  const value = envValue(name);
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

function envFalse(name: string): boolean {
  const value = envValue(name);
  return value === "0" || value === "false" || value === "no" || value === "off";
}

export function operatorSiteMode(): boolean {
  return envValue("NEPSIS_DEPLOYMENT_MODE") === "operator" || envFlag("NEXT_PUBLIC_NEPSIS_OPERATOR_SITE");
}

export function publicSiteMode(): boolean {
  if (operatorSiteMode()) {
    return false;
  }
  if (envFlag("NEXT_PUBLIC_NEPSIS_PUBLIC_SITE")) {
    return true;
  }
  if (envFalse("NEXT_PUBLIC_NEPSIS_PUBLIC_SITE")) {
    return false;
  }
  return process.env.NODE_ENV === "production";
}

export function liveOperatorEnabled(): boolean {
  return operatorSiteMode() || envFlag("NEPSIS_LIVE_OPERATOR_ENABLED");
}

export function modelRoutesEnabled(): boolean {
  if (publicSiteMode()) {
    return false;
  }
  return liveOperatorEnabled() && envFlag("NEPSIS_MODEL_ROUTES_ENABLED");
}
