export function envFlag(name: string): boolean {
  const value = process.env[name]?.trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

export function publicSiteMode(): boolean {
  const publicSite = process.env.NEXT_PUBLIC_NEPSIS_PUBLIC_SITE?.trim().toLowerCase();
  return (
    process.env.NODE_ENV === "production" ||
    publicSite === "1" ||
    publicSite === "true" ||
    publicSite === "yes" ||
    publicSite === "on"
  );
}

export function modelRoutesEnabled(): boolean {
  if (publicSiteMode()) {
    return false;
  }
  return process.env.NODE_ENV !== "production" || envFlag("NEPSIS_MODEL_ROUTES_ENABLED");
}
