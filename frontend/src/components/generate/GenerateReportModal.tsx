import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { X, Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { notifyReportsChanged } from "@/lib/reportEvents";
import type { DataBounds, GenerateReportResponse } from "@/lib/types";

interface GenerateReportModalProps {
  onClose: () => void;
}

type Mode = "full" | "custom";

export function GenerateReportModal({ onClose }: GenerateReportModalProps) {
  const navigate = useNavigate();
  const [bounds, setBounds] = useState<DataBounds | null>(null);
  const [mode, setMode] = useState<Mode>("full");
  const [weekStart, setWeekStart] = useState("");
  const [weekEnd, setWeekEnd] = useState("");
  const [status, setStatus] = useState<"idle" | "running" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    api.get<DataBounds>("/data/bounds").then((b) => {
      setBounds(b);
      setWeekStart(b.min_week);
      setWeekEnd(b.max_week);
    });
  }, []);

  async function handleGenerate() {
    setStatus("running");
    setErrorMsg(null);
    try {
      const body =
        mode === "full" ? {} : { week_start: weekStart, week_end: weekEnd };
      const res = await api.post<GenerateReportResponse>("/reports/generate", body);
      notifyReportsChanged(); // tell the sidebar's history list to refetch immediately
      onClose();
      navigate(`/reports/${res.run_id}`);
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof ApiError ? err.message : "Something went wrong generating the report.");
    }
  }

  return (
    <div className="fixed inset-0 bg-ink/40 flex items-center justify-center z-30 px-4">
      <div className="bg-page rounded-lg shadow-xl w-full max-w-md border border-line">
        <header className="flex items-center justify-between px-5 py-4 border-b border-line">
          <h2 className="font-display text-lg text-ink">Generate report</h2>
          <button
            onClick={onClose}
            className="text-warmgray hover:text-ink transition-colors"
            disabled={status === "running"}
          >
            <X size={18} />
          </button>
        </header>

        <div className="px-5 py-5 space-y-4">
          <div className="space-y-2">
            <RadioRow
              checked={mode === "full"}
              onSelect={() => setMode("full")}
              label="Full latest data"
              description="Uses every available week up to the most recent."
            />
            <RadioRow
              checked={mode === "custom"}
              onSelect={() => setMode("custom")}
              label="Custom range"
              description="Choose a specific week range to analyse."
            />
          </div>

          {mode === "custom" && bounds && (
            <div className="grid grid-cols-2 gap-3 pt-1">
              <div>
                <label className="text-xs text-warmgray block mb-1">From</label>
                <input
                  type="date"
                  value={weekStart}
                  min={bounds.min_week}
                  max={weekEnd || bounds.max_week}
                  onChange={(e) => setWeekStart(e.target.value)}
                  className="w-full border border-line rounded-md px-2.5 py-1.5 text-sm tabular bg-white"
                />
              </div>
              <div>
                <label className="text-xs text-warmgray block mb-1">To</label>
                <input
                  type="date"
                  value={weekEnd}
                  min={weekStart || bounds.min_week}
                  max={bounds.max_week}
                  onChange={(e) => setWeekEnd(e.target.value)}
                  className="w-full border border-line rounded-md px-2.5 py-1.5 text-sm tabular bg-white"
                />
              </div>
              <p className="col-span-2 text-xs text-warmgray">
                Data available {bounds.min_week} to {bounds.max_week}.
              </p>
            </div>
          )}

          {errorMsg && (
            <p className="text-sm text-clay bg-clay/8 px-3 py-2 rounded-md">{errorMsg}</p>
          )}
        </div>

        <footer className="flex justify-end gap-2 px-5 py-4 border-t border-line">
          <button
            onClick={onClose}
            disabled={status === "running"}
            className="text-sm text-warmgray hover:text-ink px-3 py-2 rounded-md transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleGenerate}
            disabled={status === "running"}
            className="flex items-center gap-2 bg-ink text-page text-sm font-medium px-4 py-2 rounded-md hover:bg-house transition-colors disabled:opacity-60"
          >
            {status === "running" && <Loader2 size={14} className="animate-spin" />}
            {status === "running" ? "Generating…" : "Generate"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function RadioRow({
  checked,
  onSelect,
  label,
  description,
}: {
  checked: boolean;
  onSelect: () => void;
  label: string;
  description: string;
}) {
  return (
    <button
      onClick={onSelect}
      className={`w-full text-left flex items-start gap-3 p-3 rounded-md border transition-colors ${
        checked ? "border-house bg-house/8" : "border-line hover:bg-panel"
      }`}
    >
      <span
        className={`mt-0.5 w-3.5 h-3.5 rounded-full border flex-shrink-0 flex items-center justify-center ${
          checked ? "border-house" : "border-warmgray"
        }`}
      >
        {checked && <span className="w-1.5 h-1.5 rounded-full bg-house" />}
      </span>
      <span>
        <span className="block text-sm font-medium text-ink">{label}</span>
        <span className="block text-xs text-warmgray mt-0.5">{description}</span>
      </span>
    </button>
  );
}
