import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import type { ConcernDetail, OpportunityDetail } from "@/lib/types";
import { formatGbp, formatPct, severityColor } from "@/lib/format";

interface ConcernCardProps {
  rank?: number;
  detail: ConcernDetail | OpportunityDetail;
  rationale: string;
}

function isOpportunity(d: ConcernDetail | OpportunityDetail): d is OpportunityDetail {
  return "health_verdict" in d;
}

export function ConcernCard({ rank, detail, rationale }: ConcernCardProps) {
  const [expanded, setExpanded] = useState(false);
  const colors = severityColor(detail.severity);
  const opp = isOpportunity(detail) ? detail : null;

  const chartData =
    opp?.gwp_lr_paired_weekly?.map((p) => ({
      week: p.week_ending,
      gwp: p.gwp_vs_plan_ratio,
      lr: p.attritional_loss_ratio_ytd,
    })) ??
    (detail.loss_ratio_history ?? detail.hit_rate_history ?? detail.weekly_ratios)?.map((v, i) => ({
      week: `wk ${i + 1}`,
      value: v,
    })) ??
    [];

  return (
    <div className="flex bg-white border border-line rounded-lg overflow-hidden">
      <div className={`w-1.5 flex-shrink-0 ${colors.rail}`} />
      <div className="flex-1 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            {rank !== undefined && (
              <span className="tabular text-xs text-warmgray mt-0.5">#{rank}</span>
            )}
            <div>
              <div className="flex items-center gap-2">
                <span className="font-medium text-sm text-ink">{detail.lob}</span>
                <span
                  className={`text-[10px] uppercase tracking-wide font-medium px-1.5 py-0.5 rounded ${colors.bg} ${colors.text}`}
                >
                  {detail.severity}
                </span>
              </div>
              <span className="text-xs text-warmgray">{detail.signal_name}</span>
            </div>
          </div>
          <span className="tabular text-sm font-medium text-ink flex-shrink-0">
            {formatGbp(detail.impact_score)}
          </span>
        </div>

        <p className="text-sm text-ink/85 leading-relaxed mt-2.5">{rationale}</p>

        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1 text-xs text-house font-medium mt-3 hover:underline"
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {expanded ? "Hide detail" : "Show detail"}
        </button>

        {expanded && (
          <div className="mt-3 pt-3 border-t border-line space-y-3">
            {detail.root_cause_detail ? (
              <p className="text-xs text-warmgray leading-relaxed">
                <span className="font-medium text-ink">
                  {detail.root_cause?.replace(/_/g, " ")}:{" "}
                </span>
                {detail.root_cause_detail}
              </p>
            ) : (
              <p className="text-xs text-warmgray leading-relaxed italic">
                No additional root-cause detail available for this signal.
              </p>
            )}
            {opp?.health_note && (
              <p className="text-xs text-warmgray leading-relaxed">
                <span className="font-medium text-ink">{opp.health_verdict?.replace(/_/g, " ")}: </span>
                {opp.health_note}
              </p>
            )}

            {chartData.length > 0 && (
              <div className="h-28">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                    <XAxis dataKey="week" tick={{ fontSize: 10, fill: "#8B8478" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: "#8B8478" }} axisLine={false} tickLine={false} width={36} />
                    <Tooltip
                      contentStyle={{ fontSize: 12, borderRadius: 6, borderColor: "#E3DFD5" }}
                      formatter={(v: number) => formatPct(v, 1)}
                    />
                    {opp ? (
                      <>
                        <Line type="monotone" dataKey="gwp" stroke="#5C7A3D" strokeWidth={2} dot={false} name="GWP vs plan" />
                        <Line type="monotone" dataKey="lr" stroke="#3D5A6C" strokeWidth={2} dot={false} name="Loss ratio" />
                      </>
                    ) : (
                      <>
                        {detail.loss_ratio_target && (
                          <ReferenceLine y={detail.loss_ratio_target} stroke="#8B8478" strokeDasharray="3 3" />
                        )}
                        <Line type="monotone" dataKey="value" stroke="#B5482F" strokeWidth={2} dot={false} />
                      </>
                    )}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            <div className="grid grid-cols-2 gap-2 text-xs">
              {detail.ytd_actual_gwp !== undefined && (
                <DetailStat label="YTD actual" value={formatGbp(detail.ytd_actual_gwp)} />
              )}
              {detail.ytd_plan_gwp !== undefined && (
                <DetailStat label="YTD plan" value={formatGbp(detail.ytd_plan_gwp)} />
              )}
              {detail.gwp_at_risk !== undefined && (
                <DetailStat label="GWP at risk" value={formatGbp(detail.gwp_at_risk)} />
              )}
              {detail.open_pipeline_gwp !== undefined && (
                <DetailStat label="Open pipeline GWP" value={formatGbp(detail.open_pipeline_gwp)} />
              )}
              {opp?.gwp_surplus !== undefined && (
                <DetailStat label="GWP surplus" value={formatGbp(opp.gwp_surplus)} />
              )}
              {detail.final_loss_ratio !== undefined && (
                <DetailStat label="Loss ratio" value={formatPct(detail.final_loss_ratio, 1)} />
              )}
              {detail.combined_ratio_ytd !== undefined && (
                <DetailStat label="Combined ratio" value={formatPct(detail.combined_ratio_ytd, 1)} />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function DetailStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between bg-panel rounded px-2.5 py-1.5">
      <span className="text-warmgray">{label}</span>
      <span className="tabular font-medium text-ink">{value}</span>
    </div>
  );
}
