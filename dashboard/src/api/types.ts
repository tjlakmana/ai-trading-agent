// Named aliases over the generated OpenAPI types (src/api/schema.d.ts).
// Regenerate after backend changes: python -m api.openapi_export dashboard/openapi.json && npm run gen:api
import type { components } from "./schema";

type S = components["schemas"];

export type Health = S["HealthOut"];
export type Module = S["ModuleOut"];
export type ModuleStatus = Module["status"];
export type Profile = S["ProfileOut"];
export type ConfigField = S["ConfigFieldOut"];
export type Run = S["RunOut"];
export type Counts = S["CountsOut"];
export type Freshness = S["FreshnessOut"];
export type Row = S["RowOut"];
export type RowStatus = Row["status"];
export type RowsPage = S["RowsPageOut"];
export type RowDetail = S["RowDetailOut"];
export type Check = S["CheckOut"];
export type TickerHistory = S["TickerHistoryOut"];
export type TickerObservation = S["TickerObservationOut"];
export type Replay = S["ReplayOut"];
export type ScanJob = S["ScanJobOut"];
export type ScanStatus = S["ScanStatusOut"];
export type OverrideValue = number | string | null;

export const ROW_STATUSES: readonly RowStatus[] = ["QUALIFIED", "NEAR_MISS", "FILTERED_OUT", "REJECTED"];

export type SortKey =
  | "row_number" | "ticker" | "price" | "pct_change" | "gap_pct" | "volume_vs_avg_daily"
  | "cumulative_volume" | "float_shares" | "pct_below_day_high" | "vendor_relative_volume";
