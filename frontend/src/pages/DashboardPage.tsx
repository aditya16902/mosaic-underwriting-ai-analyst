import { useEffect, useState } from "react";
import { PortfolioHeader } from "@/components/dashboard/PortfolioHeader";
import { ConcernCard } from "@/components/dashboard/ConcernCard";
import { LobTable } from "@/components/dashboard/LobTable";
import { GwpTrendChart } from "@/components/dashboard/GwpTrendChart";
import { HitRateHeatmap } from "@/components/dashboard/HitRateHeatmap";
import { AnomaliesSection } from "@/components/dashboard/AnomaliesSection";
import { api, API_BASE, getToken } from "@/lib/api";
import type { DashboardData } from "@/lib/types";

interface DashboardPageProps {
  runId: string;
}

export function DashboardPage({ runId }: DashboardPageProps) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api
      .get<DashboardData>(`/reports/${runId}/dashboard`)
      .then(setData)
      .catch((err) => setError(String(err.message ?? err)));
  }, [runId]);

  function openNarrative() {
    // Narrative is served as HTML directly by the API — open in a new tab,
    // with the JWT appended so the protected route renders without a login prompt.
    const token = getToken();
    window.open(`${API_BASE}/reports/${runId}/narrative?token=${token}`, "_blank");
  }

  function downloadSnapshot() {
    const token = getToken();
    const a = document.createElement("a");
    a.href = `${API_BASE}/reports/${runId}/snapshot/zip?token=${token}`;
    a.download = `mosaic_snapshot_${runId}.zip`;
    a.click();
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center px-8">
        <div className="text-center max-w-sm">
          <h2 className="font-display text-xl text-clay mb-2">Couldn't load this report</h2>
          <p className="text-sm text-warmgray leading-relaxed">{error}</p>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const allFindings = [...data.all_concerns, ...data.all_opportunities];
  // weekly_series is undefined (not an empty array) on reports generated
  // before this field existed, since it simply won't be a key in their
  // stored dashboard_data.json — guard with ?. rather than assuming it's
  // always at least an empty array.
  const weeklySeries = data.weekly_series ?? [];

  return (
    <div>
      <PortfolioHeader
        summary={data.portfolio_summary}
        runId={runId}
        onViewNarrative={openNarrative}
        onDownloadSnapshot={downloadSnapshot}
      />

      <div className="px-8 py-7 space-y-8">
        <section>
          <h2 className="font-display text-lg text-ink mb-3">Top concerns &amp; opportunity</h2>
          <div className="space-y-3">
            {data.top_concerns.map((c) => {
              const detail = allFindings.find(
                (f) => f.signal_id === c.signal_id && f.lob === c.lob,
              );
              if (!detail) return null;
              return (
                <ConcernCard key={`${c.signal_id}-${c.lob}`} rank={c.rank} detail={detail} rationale={c.one_line_rationale} />
              );
            })}
            {data.top_opportunity && (
              <ConcernCard
                detail={
                  allFindings.find(
                    (f) =>
                      f.signal_id === data.top_opportunity!.signal_id &&
                      f.lob === data.top_opportunity!.lob,
                  )!
                }
                rationale={data.top_opportunity.one_line_rationale}
              />
            )}
          </div>
        </section>

        {data.analyst_notes && (
          <section className="bg-house/6 border border-house/15 rounded-lg px-4 py-3.5">
            <h3 className="text-xs font-medium text-house uppercase tracking-wide mb-1.5">
              Analyst notes
            </h3>
            <p className="text-sm text-ink/85 leading-relaxed">{data.analyst_notes}</p>
          </section>
        )}

        {weeklySeries.length > 0 && (
          <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <GwpTrendChart weeklySeries={weeklySeries} />
            <HitRateHeatmap weeklySeries={weeklySeries} />
          </section>
        )}

        <section>
          <h2 className="font-display text-lg text-ink mb-3">All lines of business</h2>
          <LobTable rows={data.lob_snapshot} />
        </section>

        <AnomaliesSection anomalies={data.anomalies} />
      </div>
    </div>
  );
}
