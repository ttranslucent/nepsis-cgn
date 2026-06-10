export function formatTelemetryDensity(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "0";
  }
  return value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}
