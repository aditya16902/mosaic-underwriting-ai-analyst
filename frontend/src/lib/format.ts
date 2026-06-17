export function formatGbp(value: number | string | null | undefined): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
    maximumFractionDigits: 0,
  }).format(n);
}

export function formatPct(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(decimals)}%`;
}

export function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

export function formatWeekLabel(weekEnding: string): string {
  return new Date(weekEnding).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function severityColor(severity: string): { text: string; bg: string; rail: string } {
  switch (severity) {
    case "HIGH":
      return { text: "text-clay", bg: "bg-clay/8", rail: "bg-clay" };
    case "MEDIUM":
      return { text: "text-clay/80", bg: "bg-clay/6", rail: "bg-clay/60" };
    case "OPPORTUNITY":
      return { text: "text-olive", bg: "bg-olive/8", rail: "bg-olive" };
    default:
      return { text: "text-warmgray", bg: "bg-warmgray/8", rail: "bg-warmgray" };
  }
}
