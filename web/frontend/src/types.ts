/** Transport types mirroring `web/backend/schemas.py`.
 *
 * The frontend owns no rules: a status is whatever the backend wrote, and the
 * merge button reads counts the backend computed.
 */

export type MappingStatus = "auto" | "review" | "unmatched";

export interface SourceMatch {
  file: string;
  column: string | null;
  confidence: number;
  status: MappingStatus;
  reason?: string | null;
  samples?: unknown[] | null;
}

export interface MappingEntry {
  target_column: string;
  sources: SourceMatch[];
}

export interface StatusCounts {
  auto: number;
  review: number;
  unmatched: number;
}

export interface Mapping {
  entries: MappingEntry[];
  counts: StatusCounts;
}

export interface SourceColumn {
  name: string;
  inferred_type: string;
  samples: string[];
  unique_count: number;
  null_ratio: number;
}

export interface FileColumns {
  file: string;
  row_count: number;
  columns: SourceColumn[];
}

export interface TargetColumn {
  name: string;
  type: string;
  required: boolean;
}

export interface Columns {
  files: FileColumns[];
  target_columns: TargetColumn[];
}

export interface UploadResult {
  session_id: string;
  inputs: string[];
  target_schema: string;
  state: string;
}

export interface Finding {
  check: string;
  severity: "info" | "warning" | "error";
  target_column: string;
  message: string;
  description: string;
}

export interface ApplyResult {
  row_count: number;
  null_cell_count: number;
  conversion_error_count: number;
  output_format: string;
  merged_file: string;
  report_file: string;
  skipped_sheets: string[];
  warnings: Finding[];
}

export interface PendingMatch {
  target_column: string;
  file: string;
  column: string | null;
  confidence: number;
  reason?: string | null;
}

/** 409 body of a refused apply: what blocks it, and that nothing was written. */
export interface ReviewGuardDetail {
  error: "review_pending" | "validation_failed";
  message: string;
  pending?: PendingMatch[];
  findings?: Finding[];
  written: boolean;
}

export interface ProviderInfo {
  provider: string;
  embedding_provider: string;
  model: string;
  configured: boolean;
  detail?: string | null;
}
