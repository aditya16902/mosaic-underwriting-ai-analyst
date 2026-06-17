import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { api } from "@/lib/api";
import type { ScheduleConfig } from "@/lib/types";

const DAYS: { value: string; label: string }[] = [
  { value: "mon", label: "Monday" },
  { value: "tue", label: "Tuesday" },
  { value: "wed", label: "Wednesday" },
  { value: "thu", label: "Thursday" },
  { value: "fri", label: "Friday" },
  { value: "sat", label: "Saturday" },
  { value: "sun", label: "Sunday" },
];

export function SettingsPage() {
  const [config, setConfig] = useState<ScheduleConfig | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get<ScheduleConfig>("/schedule").then(setConfig);
  }, []);

  async function save() {
    if (!config) return;
    setSaving(true);
    setSaved(false);
    await api.put("/schedule", {
      enabled: !!config.enabled,
      day_of_week: config.day_of_week,
      hour: config.hour,
      minute: config.minute,
    });
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  if (!config) return null;

  return (
    <div className="max-w-xl mx-auto px-8 py-10">
      <h1 className="font-display text-2xl text-ink mb-1">Schedule settings</h1>
      <p className="text-sm text-warmgray mb-8 leading-relaxed">
        Controls the automated weekly report. While running locally this fires from
        the API process itself; in production this maps to a scheduled trigger.
      </p>

      <div className="bg-panel border border-line rounded-lg p-5 space-y-5">
        <label className="flex items-center justify-between cursor-pointer">
          <span className="text-sm font-medium text-ink">Automated weekly report</span>
          <button
            onClick={() => setConfig({ ...config, enabled: config.enabled ? 0 : 1 })}
            className={`relative w-10 h-5.5 rounded-full transition-colors ${
              config.enabled ? "bg-house" : "bg-warmgray/40"
            }`}
            style={{ height: 22 }}
          >
            <span
              className="absolute top-0.5 left-0.5 w-4.5 h-4.5 bg-white rounded-full transition-transform shadow-sm"
              style={{
                width: 18,
                height: 18,
                transform: config.enabled ? "translateX(18px)" : "translateX(0)",
              }}
            />
          </button>
        </label>

        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-1">
            <label className="text-xs text-warmgray block mb-1.5">Day</label>
            <select
              value={config.day_of_week}
              onChange={(e) => setConfig({ ...config, day_of_week: e.target.value })}
              disabled={!config.enabled}
              className="w-full border border-line rounded-md px-2.5 py-2 text-sm bg-white disabled:opacity-50"
            >
              {DAYS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>
          <div className="col-span-1">
            <label className="text-xs text-warmgray block mb-1.5">Hour (UTC)</label>
            <select
              value={config.hour}
              onChange={(e) => setConfig({ ...config, hour: Number(e.target.value) })}
              disabled={!config.enabled}
              className="w-full border border-line rounded-md px-2.5 py-2 text-sm tabular bg-white disabled:opacity-50"
            >
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>
                  {String(h).padStart(2, "0")}:00
                </option>
              ))}
            </select>
          </div>
          <div className="col-span-1">
            <label className="text-xs text-warmgray block mb-1.5">Minute</label>
            <select
              value={config.minute}
              onChange={(e) => setConfig({ ...config, minute: Number(e.target.value) })}
              disabled={!config.enabled}
              className="w-full border border-line rounded-md px-2.5 py-2 text-sm tabular bg-white disabled:opacity-50"
            >
              {[0, 15, 30, 45].map((m) => (
                <option key={m} value={m}>
                  :{String(m).padStart(2, "0")}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <button
            onClick={save}
            disabled={saving}
            className="bg-ink text-page text-sm font-medium px-4 py-2 rounded-md hover:bg-house transition-colors disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save schedule"}
          </button>
          {saved && (
            <span className="flex items-center gap-1 text-sm text-olive">
              <Check size={14} /> Saved
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
