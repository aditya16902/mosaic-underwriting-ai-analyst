import { NavLink, useNavigate, useParams } from "react-router-dom";
import { useEffect, useState } from "react";
import { Plus, Settings, FileText, Trash2, Check, X, LogOut } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import { logout } from "@/lib/auth";
import { onReportsChanged, notifyReportsChanged } from "@/lib/reportEvents";
import type { ReportListItem } from "@/lib/types";

interface SidebarProps {
  onGenerateClick: () => void;
  onLogout: () => void;
}

/** Derives the severity rail color for a report row from its stored signals_json. */
function severityRailColor(signalsJson: string): string {
  try {
    const counts = JSON.parse(signalsJson) as Record<string, number>;
    const highSignals =
      (counts["S1_structural_underperformance"] ?? 0) +
      (counts["S2_hit_rate_collapse"] ?? 0) +
      (counts["S3_loss_ratio_deterioration"] ?? 0);
    if (highSignals >= 2) return "bg-clay";
    if (highSignals === 1) return "bg-clay/60";
    return "bg-olive/70";
  } catch {
    return "bg-warmgray/40";
  }
}

function formatReportDate(weekEnd: string | null, createdAt: string): string {
  const d = weekEnd ? new Date(weekEnd) : new Date(createdAt);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function Sidebar({ onGenerateClick, onLogout }: SidebarProps) {
  const [reports, setReports] = useState<ReportListItem[] | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState<string | null>(null);
  const navigate = useNavigate();
  const { runId: activeRunId } = useParams<{ runId: string }>();

  function refetch() {
    api.get<ReportListItem[]>("/reports").then(setReports).catch(() => setReports([]));
  }

  useEffect(() => {
    refetch();
    const unsubscribe = onReportsChanged(refetch);
    api
      .get<{ username: string; display_name: string }>("/auth/me")
      .then((u) => setDisplayName(u.display_name))
      .catch(() => setDisplayName(null));
    return unsubscribe;
  }, []);

  function handleDeleteClick(e: React.MouseEvent, runId: string) {
    e.preventDefault();
    e.stopPropagation();
    setConfirmDeleteId(runId);
  }

  function handleCancelDelete(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setConfirmDeleteId(null);
  }

  async function handleConfirmDelete(e: React.MouseEvent, runId: string) {
    e.preventDefault();
    e.stopPropagation();
    setDeletingId(runId);
    try {
      await api.delete(`/reports/${runId}`);
      notifyReportsChanged();
      if (activeRunId === runId) {
        navigate("/");
      }
    } finally {
      setDeletingId(null);
      setConfirmDeleteId(null);
    }
  }

  function handleLogout() {
    logout();
    onLogout();
  }

  return (
    <aside className="w-72 flex-shrink-0 h-full bg-panel border-r border-line flex flex-col">
      <div className="px-5 pt-6 pb-4">
        <h1 className="font-display text-xl font-semibold text-ink tracking-tight">MosAIc</h1>
        <p className="text-xs text-warmgray mt-0.5">Underwriting performance intelligence</p>
      </div>

      <div className="px-4 pb-3">
        <button
          onClick={onGenerateClick}
          className="w-full flex items-center justify-center gap-2 bg-ink text-page text-sm font-medium py-2.5 rounded-md hover:bg-house transition-colors"
        >
          <Plus size={15} strokeWidth={2.25} />
          Generate report
        </button>
      </div>

      <div className="px-5 pt-4 pb-2">
        <span className="text-xs font-medium text-warmgray uppercase tracking-wide">
          Report history
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {reports === null && (
          <div className="px-3 py-4 text-sm text-warmgray">Loading…</div>
        )}
        {reports !== null && reports.length === 0 && (
          <div className="px-3 py-4 text-sm text-warmgray leading-relaxed">
            No reports yet. Generate the first one to see it here.
          </div>
        )}
        {reports?.map((r) => {
          const isConfirming = confirmDeleteId === r.run_id;
          const isDeleting = deletingId === r.run_id;

          return (
            <NavLink
              key={r.run_id}
              to={`/reports/${r.run_id}`}
              className={({ isActive }) =>
                clsx(
                  "flex items-stretch gap-3 rounded-md mb-1 group transition-colors",
                  isActive ? "bg-house/10" : "hover:bg-line/60",
                )
              }
            >
              <span className={clsx("w-1 rounded-full my-1.5", severityRailColor(r.signals_json))} />
              <div className="flex-1 py-2.5 pr-2 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-ink truncate">
                    {formatReportDate(r.week_end, r.created_at)}
                  </span>
                  {isConfirming ? (
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <button
                        onClick={(e) => handleConfirmDelete(e, r.run_id)}
                        disabled={isDeleting}
                        className="text-clay hover:text-clay/80 p-0.5 rounded disabled:opacity-50"
                        aria-label="Confirm delete"
                        title="Confirm delete"
                      >
                        <Check size={13} />
                      </button>
                      <button
                        onClick={handleCancelDelete}
                        disabled={isDeleting}
                        className="text-warmgray hover:text-ink p-0.5 rounded disabled:opacity-50"
                        aria-label="Cancel delete"
                        title="Cancel"
                      >
                        <X size={13} />
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={(e) => handleDeleteClick(e, r.run_id)}
                      className="opacity-0 group-hover:opacity-100 text-warmgray hover:text-clay p-0.5 rounded transition-opacity flex-shrink-0"
                      aria-label="Delete report"
                      title="Delete report"
                    >
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <FileText size={11} className="text-warmgray" />
                  <span className="text-xs text-warmgray">{r.total_weeks} wk</span>
                  <span
                    className={clsx(
                      "text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded ml-auto font-medium",
                      r.source === "automated"
                        ? "bg-house/15 text-house"
                        : "bg-warmgray/15 text-warmgray",
                    )}
                  >
                    {r.source === "automated" ? "Auto" : "Manual"}
                  </span>
                </div>
                {isConfirming && (
                  <p className="text-[11px] text-clay mt-1.5 leading-snug">
                    Delete this report and all its files? This can't be undone.
                  </p>
                )}
              </div>
            </NavLink>
          );
        })}
      </nav>

      <div className="px-2 py-2 border-t border-line">
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            clsx(
              "flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors",
              isActive ? "bg-house/10 text-house" : "text-warmgray hover:bg-line/60 hover:text-ink",
            )
          }
        >
          <Settings size={15} />
          Schedule settings
        </NavLink>

        <div className="flex items-center justify-between px-3 py-2 mt-0.5">
          <span className="text-sm text-warmgray truncate" title={displayName ?? undefined}>
            {displayName ? `Signed in as ${displayName}` : ""}
          </span>
          <button
            onClick={handleLogout}
            className="flex items-center gap-1.5 text-sm text-warmgray hover:text-clay transition-colors flex-shrink-0"
            title="Sign out"
          >
            <LogOut size={14} />
          </button>
        </div>
      </div>
    </aside>
  );
}
