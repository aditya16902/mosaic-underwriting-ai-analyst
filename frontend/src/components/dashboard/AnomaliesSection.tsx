import { AlertTriangle } from "lucide-react";
import type { DashboardData } from "@/lib/types";

interface AnomaliesSectionProps {
  anomalies: DashboardData["anomalies"];
}

export function AnomaliesSection({ anomalies }: AnomaliesSectionProps) {
  const all = [
    ...anomalies.claims_spikes,
    ...anomalies.stalled_pipeline,
    ...anomalies.funnel_divergence,
    ...anomalies.missing_data,
  ];

  if (all.length === 0) return null;

  return (
    <div>
      <h3 className="text-xs font-medium text-warmgray uppercase tracking-wide mb-2.5">
        Anomalies detected — not flagged as concerns
      </h3>
      <div className="space-y-2">
        {all.map((a, i) => (
          <div
            key={i}
            className="flex items-start gap-2.5 bg-panel border border-line rounded-md px-3.5 py-2.5"
          >
            <AlertTriangle size={14} className="text-warmgray mt-0.5 flex-shrink-0" />
            <p className="text-xs text-ink/80 leading-relaxed">{a.note}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
