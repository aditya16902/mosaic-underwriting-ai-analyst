/**
 * Types mirroring the actual backend response shapes.
 * Source of truth: backend/report/snapshot.py (_write_dashboard_json),
 * backend/api/routes.py (list_reports, chat), and live dashboard_data.json
 * inspected from a real run.
 */

export type Severity = "HIGH" | "MEDIUM" | "LOW" | "OPPORTUNITY";

export interface PortfolioSummary {
  report_week: string;
  total_weeks_analysed: number;
  week_range_start: string;
  week_range_end: string;
  total_ytd_actual_gwp: number;
  total_ytd_plan_gwp: number | string;
  portfolio_ytd_gwp_ratio: number;
  lob_count: number;
}

export interface LobSnapshotRow {
  lob: string;
  latest_week: string;
  actual_gwp: number;
  plan_gwp: number | string;
  gwp_vs_plan_ratio: number;
  ytd_actual: number;
  ytd_plan: number | string;
  ytd_gwp_vs_plan: number;
  hit_rate: number | null;
  loss_ratio_ytd: number;
  combined_ratio_ytd: number;
  avg_pipeline_days: number;
}

/** One row per (lob, week) — the full time series behind the GWP trend chart and hit-rate heatmap. */
export interface WeeklySeriesPoint {
  week_ending: string;
  lob: string;
  gwp_vs_plan_ratio: number | null;
  hit_rate: number | null;
}

export interface TopConcern {
  rank: number;
  signal_id: string;
  lob: string;
  signal_name: string;
  one_line_rationale: string;
  severity: Severity;
  impact_score: number;
}

export interface TopOpportunity {
  signal_id: string;
  lob: string;
  signal_name: string;
  one_line_rationale: string;
  severity: Severity;
  impact_score: number;
}

export interface WeeklyGwpLrPoint {
  week_ending: string;
  gwp_vs_plan_ratio: number;
  attritional_loss_ratio_ytd: number;
}

export interface ConcernDetail {
  signal_id: string;
  signal_name: string;
  lob: string;
  severity: Severity;
  impact_score: number;
  root_cause?: string;
  root_cause_detail?: string;
  weekly_ratios?: number[];
  loss_ratio_history?: number[];
  hit_rate_history?: number[];
  ytd_actual_gwp?: number;
  ytd_plan_gwp?: number | string;
  gwp_at_risk?: number;
  open_pipeline_gwp?: number;
  final_loss_ratio?: number;
  loss_ratio_target?: number;
  combined_ratio_ytd?: number;
  est_underwriting_loss?: number;
  // S1: which recent window the root_cause_detail averages cover
  recent_window_weeks?: number;
  recent_window_start?: string;
  recent_window_end?: string;
  // S2: explicit baseline vs recent window date ranges
  baseline_window_weeks?: number;
  baseline_window_start?: string;
  baseline_window_end?: string;
  // S3: full trend period covered by the regression
  trend_period_weeks?: number;
  trend_period_start?: string;
  trend_period_end?: string;
  [key: string]: unknown;
}

export interface OpportunityDetail extends ConcernDetail {
  health_verdict?: string;
  health_note?: string;
  gwp_surplus?: number;
  gwp_lr_paired_weekly?: WeeklyGwpLrPoint[];
}

export interface AnomalyItem {
  type: string;
  lob: string;
  week_ending: string;
  note: string;
  [key: string]: unknown;
}

export interface DashboardData {
  portfolio_summary: PortfolioSummary;
  lob_snapshot: LobSnapshotRow[];
  weekly_series: WeeklySeriesPoint[];
  top_concerns: TopConcern[];
  top_opportunity: TopOpportunity | null;
  all_concerns: ConcernDetail[];
  all_opportunities: OpportunityDetail[];
  anomalies: {
    claims_spikes: AnomalyItem[];
    stalled_pipeline: AnomalyItem[];
    funnel_divergence: AnomalyItem[];
    missing_data: AnomalyItem[];
  };
  pipeline_friction: unknown[];
  analyst_notes: string;
  session_id: string;
}

export type ReportSource = "manual" | "automated";

export interface ReportListItem {
  run_id: string;
  created_at: string;
  week_start: string | null;
  week_end: string | null;
  total_weeks: number;
  status: string;
  source: ReportSource;
  signals_json: string;
}

export interface GenerateReportResponse {
  run_id: string;
  status: string;
  total_weeks: number;
  report_week: string;
  signal_counts: Record<string, number>;
  top_concerns: TopConcern[];
  top_opportunity: TopOpportunity | null;
  analyst_notes: string;
  session_id: string;
}

export interface DataBounds {
  min_week: string;
  max_week: string;
}

export interface ScheduleConfig {
  id: number;
  enabled: 0 | 1;
  day_of_week: string;
  hour: number;
  minute: number;
  updated_at: string;
}

export interface ChatResponse {
  answer: string;
  sql: string | null;
  rows: Record<string, unknown>[];
  columns: string[];
  row_count: number;
  success: boolean;
  error: string | null;
  session_id: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sql?: string | null;
  rows?: Record<string, unknown>[];
  columns?: string[];
  pending?: boolean;
  error?: string | null;
}
