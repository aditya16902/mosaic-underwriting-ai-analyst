"""
Business Semantic Schema
Describes the merged_metrics table in terms the LLM and the CUO understand.
This is injected into the SQL generation prompt so the agent knows what
each column means, what valid values are, and how computed metrics were derived.
"""

SCHEMA_DESCRIPTION = """
## Table: merged_metrics

This table contains 12 weeks of underwriting performance data across 8 lines of business (LoB),
with all metrics pre-computed by the MosAIc pipeline. One row = one LoB for one week.

### Key Identifiers
- week_ending       : TEXT  — Date of week end (Sunday), format 'YYYY-MM-DD'. 12 distinct values.
- lob               : TEXT  — Line of Business. Valid values:
                               'Cyber', 'Transactional Liability', 'Environmental',
                               'Political Risk', 'Political Violence', 'Financial Institutions',
                               'Professional Lines', 'Excess Casualty'
- week_num          : INTEGER — Ordinal week number within the dataset (1 = earliest, 12 = latest)

### Premium / Revenue Columns
- actual_gwp        : REAL  — Gross Written Premium actually written this week (£)
- plan_gwp          : REAL  — Planned/budgeted GWP for this week (£)
- ytd_actual        : REAL  — Year-to-date cumulative actual GWP up to this week (£)
- ytd_plan          : REAL  — Year-to-date cumulative planned GWP up to this week (£)

### Computed GWP Ratios
- gwp_vs_plan_ratio      : REAL — actual_gwp / plan_gwp. 1.0 = on plan. <0.75 = concerning underperformance.
- ytd_gwp_vs_plan_ratio  : REAL — ytd_actual / ytd_plan. YTD version of the above.

### Submission Funnel Columns (how business flows through the pipeline)
- submissions_count : INTEGER — Total submissions received from brokers this week
- quoted_count      : INTEGER — Submissions we provided a price/quote for
- bound_count       : INTEGER — Quotes that converted to live policies (bound = sold)
- declined_count    : INTEGER — Submissions we declined to quote (outside appetite)
- ntu_count         : INTEGER — Not Taken Up — we quoted but broker/client chose competitor

### Computed Submission Metrics
- hit_rate          : REAL  — bound / (bound + quoted + declined + ntu). Conversion rate. Target: ~0.25-0.35.
- decline_rate      : REAL  — declined / submissions. High = too selective.
- ntu_rate          : REAL  — ntu / submissions. High = losing to price / competitors.

### Pipeline Columns (open quotes not yet bound or declined)
- open_quotes_count   : INTEGER — Number of quotes currently sitting with brokers
- open_quotes_gwp_est : REAL    — Estimated GWP value of open quotes (£). 'Ghost premium' if stalling.
- avg_days_in_pipeline: REAL    — Average days open quotes have been with brokers. >30 = friction.

### Loss / Claims Columns
- new_claims_count         : INTEGER — New claims reported this week
- new_claims_incurred_est  : REAL    — Estimated value of new claims this week (£)
- attritional_loss_ratio_ytd: REAL   — YTD cumulative loss ratio (claims / premium). TARGET: <0.55-0.60 depending on LoB.
                                       This is a RUNNING TOTAL — it accumulates across weeks.

### Computed Loss Metrics
- assumed_expense_ratio    : REAL — Fixed expense ratio assumption per LoB (e.g. 0.28 for Cyber)
- loss_ratio_target        : REAL — LoB-specific target loss ratio (e.g. 0.55 for Environmental)
- combined_ratio_ytd       : REAL — attritional_loss_ratio_ytd + assumed_expense_ratio.
                                    <1.0 = underwriting profit. >1.0 = underwriting loss.
- loss_ratio_velocity      : REAL — Week-on-week change in attritional_loss_ratio_ytd.
                                    Positive = worsening. Negative = improving.

### SQL Notes
- Always filter by lob and/or week_ending when comparing specific lines
- For trends, ORDER BY week_ending ASC
- loss_ratio_velocity is NULL for week_num=1 (no previous week to diff against)
- Use week_num for ordinal comparisons (e.g. "last 4 weeks" = week_num > 8 when total=12)
- Monetary values (gwp, claims) are in GBP (£)
"""

LOB_PROFILES_CONTEXT = """
### LoB-Specific Context
| LoB                    | Expense Ratio | Loss Ratio Target | Key Characteristic |
|------------------------|--------------|-------------------|-------------------|
| Cyber                  | 28%          | 60%               | Fastest-growing line. Ransomware, data breaches. |
| Transactional Liability| 42%          | 50%               | M&A deal insurance. Highest expense ratio. |
| Environmental          | 35%          | 55%               | Pollution / contamination. Slow-burn claims. |
| Political Risk         | 35%          | 55%               | Emerging market expropriation risk. |
| Political Violence     | 32%          | 55%               | Terrorism, riots. Currently outperforming. |
| Financial Institutions | 33%          | 55%               | Bank fraud, D&O, cyber. |
| Professional Lines     | 34%          | 55%               | Negligence / E&O for professionals. |
| Excess Casualty        | 30%          | 60%               | Large liability above primary limits. Currently underperforming. |
"""


def get_full_schema() -> str:
    return SCHEMA_DESCRIPTION + "\n" + LOB_PROFILES_CONTEXT
