import { Fragment, useMemo } from "react";
import type { WeeklySeriesPoint } from "@/lib/types";
import { formatWeekLabel, formatPct } from "@/lib/format";

interface HitRateHeatmapProps {
  weeklySeries: WeeklySeriesPoint[];
}

/**
 * Hit rate heatmap, LoB x week. Built as a plain CSS grid rather than forcing
 * Recharts (which has no native heatmap primitive) — cell colour intensity is
 * the signal here, so direct control over the colour scale matters more than
 * reusing a charting library.
 */
export function HitRateHeatmap({ weeklySeries }: HitRateHeatmapProps) {
  const { weeks, lobs, cellFor } = useMemo(() => {
    const weeks = Array.from(new Set(weeklySeries.map((p) => p.week_ending))).sort();
    const lobs = Array.from(new Set(weeklySeries.map((p) => p.lob))).sort();
    const lookup = new Map<string, number | null>();
    for (const p of weeklySeries) {
      lookup.set(`${p.lob}__${p.week_ending}`, p.hit_rate);
    }
    return {
      weeks,
      lobs,
      cellFor: (lob: string, week: string) => lookup.get(`${lob}__${week}`) ?? null,
    };
  }, [weeklySeries]);

  // Hit rate cell shading: low hit rate reads as concerning (clay), high as healthy (olive).
  // Scale is fixed to a reasonable underwriting hit-rate range rather than min/max of the
  // data, so colour intensity is comparable across different reports/weeks.
  function cellStyle(value: number | null): React.CSSProperties {
    if (value === null) return { backgroundColor: "#F3F1EC" };
    const clamped = Math.max(0, Math.min(1, value));
    // 0.10 -> deep clay, 0.30 -> neutral, 0.50+ -> deep olive
    const t = Math.max(0, Math.min(1, (clamped - 0.1) / 0.4));
    const r = Math.round(181 - t * (181 - 92));
    const g = Math.round(72 + t * (122 - 72));
    const b = Math.round(47 + t * (61 - 47));
    return { backgroundColor: `rgb(${r}, ${g}, ${b})` };
  }

  return (
    <div className="border border-line rounded-lg p-4 overflow-x-auto">
      <h3 className="text-sm font-medium text-ink mb-1">Hit rate heatmap</h3>
      <p className="text-xs text-warmgray mb-3">Line of business vs week</p>

      <div className="min-w-[640px]">
        <div
          className="grid gap-1"
          style={{ gridTemplateColumns: `140px repeat(${weeks.length}, 1fr)` }}
        >
          <div />
          {weeks.map((w) => (
            <div key={w} className="text-[10px] text-warmgray text-center pb-1">
              {formatWeekLabel(w)}
            </div>
          ))}

          {lobs.map((lob) => (
            <Fragment key={lob}>
              <div className="text-xs text-ink py-1.5 pr-2 truncate">{lob}</div>
              {weeks.map((w) => {
                const value = cellFor(lob, w);
                return (
                  <div
                    key={`${lob}-${w}`}
                    title={`${lob}, ${formatWeekLabel(w)}: ${value !== null ? formatPct(value, 1) : "no data"}`}
                    className="h-7 rounded-sm flex items-center justify-center"
                    style={cellStyle(value)}
                  >
                    <span
                      className="text-[9px] tabular"
                      style={{ color: value !== null && value > 0.3 ? "#FAFAF8" : "#14171C" }}
                    >
                      {value !== null ? formatPct(value, 0) : "—"}
                    </span>
                  </div>
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2 mt-3 text-[10px] text-warmgray">
        <span>Lower hit rate</span>
        <div className="flex h-2 w-24 rounded-sm overflow-hidden">
          {Array.from({ length: 10 }, (_, i) => (
            <div key={i} className="flex-1" style={cellStyle(0.1 + (i / 9) * 0.4)} />
          ))}
        </div>
        <span>Higher hit rate</span>
      </div>
    </div>
  );
}
