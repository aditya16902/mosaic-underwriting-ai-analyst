import type { LobSnapshotRow } from "@/lib/types";
import { formatGbp, formatPct, formatRatio } from "@/lib/format";
import clsx from "clsx";

interface LobTableProps {
  rows: LobSnapshotRow[];
}

export function LobTable({ rows }: LobTableProps) {
  const sorted = [...rows].sort((a, b) => a.gwp_vs_plan_ratio - b.gwp_vs_plan_ratio);

  return (
    <div className="border border-line rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-panel border-b border-line">
            <Th align="left">Line of business</Th>
            <Th>Actual GWP</Th>
            <Th>Plan GWP</Th>
            <Th>vs plan</Th>
            <Th>Hit rate</Th>
            <Th>Loss ratio YTD</Th>
            <Th>Combined ratio</Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            // Compare against the same rounded value being displayed (2dp), not the
            // raw float — otherwise two rows that both display "1.10x" can end up
            // coloured differently depending on which side of 1.1 their unrounded
            // value actually falls, which reads as an inconsistent/arbitrary bug.
            const displayedRatio = Math.round(row.gwp_vs_plan_ratio * 100) / 100;
            const underPlan = displayedRatio < 0.95;
            const overPlan = displayedRatio > 1.1;
            const highLoss = row.combined_ratio_ytd > 1.0;

            return (
              <tr key={row.lob} className="border-b border-line last:border-0 hover:bg-panel/50 transition-colors">
                <td className="px-4 py-3 font-medium text-ink">{row.lob}</td>
                <Td>{formatGbp(row.actual_gwp)}</Td>
                <Td>{formatGbp(row.plan_gwp)}</Td>
                <Td>
                  <span
                    className={clsx(
                      "tabular font-medium",
                      underPlan ? "text-clay" : overPlan ? "text-olive" : "text-ink",
                    )}
                  >
                    {formatRatio(row.gwp_vs_plan_ratio)}x
                  </span>
                </Td>
                <Td>{row.hit_rate !== null ? formatPct(row.hit_rate, 1) : "—"}</Td>
                <Td>{formatPct(row.loss_ratio_ytd, 1)}</Td>
                <Td>
                  <span className={clsx("tabular font-medium", highLoss ? "text-clay" : "text-ink")}>
                    {formatPct(row.combined_ratio_ytd, 1)}
                  </span>
                </Td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Th({ children, align = "right" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <th
      className={clsx(
        "px-4 py-2.5 text-xs font-medium text-warmgray uppercase tracking-wide",
        align === "left" ? "text-left" : "text-right",
      )}
    >
      {children}
    </th>
  );
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-4 py-3 text-right tabular text-ink">{children}</td>;
}
