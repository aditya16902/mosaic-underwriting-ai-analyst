import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from "recharts";
import type { WeeklySeriesPoint } from "@/lib/types";
import { formatWeekLabel, formatPct } from "@/lib/format";

interface GwpTrendChartProps {
  weeklySeries: WeeklySeriesPoint[];
}

// Fixed palette so each LoB keeps a consistent colour across charts/sessions,
// rather than Recharts picking arbitrary colours per render.
const LOB_COLORS: Record<string, string> = {
  "Cyber": "#3D5A6C",
  "Excess Casualty": "#B5482F",
  "Environmental": "#5C7A3D",
  "Political Violence": "#8B8478",
  "Financial Institutions": "#A8763E",
  "Political Risk": "#6B4C7A",
  "Professional Lines": "#3E7A6F",
  "Transactional Liability": "#7A5C3D",
};

export function GwpTrendChart({ weeklySeries }: GwpTrendChartProps) {
  const weeks = Array.from(new Set(weeklySeries.map((p) => p.week_ending))).sort();
  const lobs = Array.from(new Set(weeklySeries.map((p) => p.lob))).sort();

  const chartData = weeks.map((week) => {
    const row: Record<string, string | number | null> = { week };
    for (const lob of lobs) {
      const point = weeklySeries.find((p) => p.week_ending === week && p.lob === lob);
      row[lob] = point?.gwp_vs_plan_ratio ?? null;
    }
    return row;
  });

  return (
    <div className="border border-line rounded-lg p-4">
      <h3 className="text-sm font-medium text-ink mb-1">GWP vs plan by line of business</h3>
      <p className="text-xs text-warmgray mb-3">12-week trend, ratio to plan</p>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          {/*
            Y-axis labels can reach 4 characters ("150%") when a LoB runs well
            above plan. The axis needs real width to render that without the
            leading digit getting clipped off — a previous version used
            width={42} with a -8 left margin, which silently truncated any
            label >= 100% (e.g. "140%" rendered as "40%", "105%" as "05%"),
            making the axis look broken/non-monotonic. width=56 + margin
            left=4 gives every label room to render in full.
          */}
          <LineChart data={chartData} margin={{ top: 4, right: 12, left: 4, bottom: 0 }}>
            <XAxis
              dataKey="week"
              tickFormatter={formatWeekLabel}
              tick={{ fontSize: 11, fill: "#8B8478" }}
              axisLine={{ stroke: "#E3DFD5" }}
              tickLine={false}
            />
            <YAxis
              domain={[0, "auto"]}
              tick={{ fontSize: 11, fill: "#8B8478" }}
              axisLine={false}
              tickLine={false}
              width={56}
              tickFormatter={(v) => formatPct(v, 0)}
            />
            <ReferenceLine y={1} stroke="#8B8478" strokeDasharray="3 3" />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 6, borderColor: "#E3DFD5" }}
              labelFormatter={formatWeekLabel}
              formatter={(v: number, name: string) => [formatPct(v, 1), name]}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} iconSize={8} />
            {lobs.map((lob) => (
              <Line
                key={lob}
                type="monotone"
                dataKey={lob}
                stroke={LOB_COLORS[lob] ?? "#8B8478"}
                strokeWidth={1.75}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
