import { FileDown, ExternalLink } from "lucide-react";
import type { PortfolioSummary } from "@/lib/types";
import { formatGbp, formatPct } from "@/lib/format";

interface PortfolioHeaderProps {
  summary: PortfolioSummary;
  runId: string;
  onViewNarrative: () => void;
  onDownloadSnapshot: () => void;
}

export function PortfolioHeader({
  summary,
  onViewNarrative,
  onDownloadSnapshot,
}: PortfolioHeaderProps) {
  const onPlan = summary.portfolio_ytd_gwp_ratio >= 0.95;

  return (
    <div className="border-b border-line px-8 py-7">
      <div className="flex items-start justify-between gap-6">
        <div>
          <span className="text-xs font-medium text-warmgray uppercase tracking-wide">
            Week ending {new Date(summary.report_week).toLocaleDateString("en-GB", {
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </span>
          <h1 className="font-display text-3xl text-ink mt-1.5 tracking-tight">
            Portfolio at {formatPct(summary.portfolio_ytd_gwp_ratio, 1)} of plan
          </h1>
          <p className="text-sm text-warmgray mt-1.5">
            {summary.total_weeks_analysed} weeks analysed · {summary.lob_count} lines of business ·{" "}
            {new Date(summary.week_range_start).toLocaleDateString("en-GB", {
              day: "numeric",
              month: "short",
            })}{" "}
            –{" "}
            {new Date(summary.week_range_end).toLocaleDateString("en-GB", {
              day: "numeric",
              month: "short",
            })}
          </p>
        </div>

        <div className="flex gap-2 flex-shrink-0">
          <button
            onClick={onViewNarrative}
            className="flex items-center gap-1.5 text-sm font-medium text-ink border border-line px-3.5 py-2 rounded-md hover:bg-panel transition-colors"
          >
            <ExternalLink size={14} />
            Full narrative
          </button>
          <button
            onClick={onDownloadSnapshot}
            className="flex items-center gap-1.5 text-sm font-medium text-ink border border-line px-3.5 py-2 rounded-md hover:bg-panel transition-colors"
          >
            <FileDown size={14} />
            Download snapshot
          </button>
        </div>
      </div>

      <div className="flex gap-8 mt-6">
        <Stat label="YTD actual GWP" value={formatGbp(summary.total_ytd_actual_gwp)} />
        <Stat label="YTD plan GWP" value={formatGbp(summary.total_ytd_plan_gwp)} />
        <Stat
          label="vs plan"
          value={formatPct(summary.portfolio_ytd_gwp_ratio, 1)}
          accent={onPlan ? "olive" : "clay"}
        />
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "olive" | "clay";
}) {
  return (
    <div>
      <span className="text-xs text-warmgray block mb-0.5">{label}</span>
      <span
        className={`tabular text-xl font-medium ${
          accent === "olive" ? "text-olive" : accent === "clay" ? "text-clay" : "text-ink"
        }`}
      >
        {value}
      </span>
    </div>
  );
}
