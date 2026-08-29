import { useMemo, useState } from "react";

import type { MappingStatus, SourceColumn, SourceMatch } from "../types";

/** Colour code of the review screen (spec sections 6 and 12). */
const STATUS_LABEL: Record<MappingStatus, string> = {
  auto: "Otomatik eşleşti",
  review: "Onayınız gerekiyor",
  unmatched: "Eşleşme yok",
};

const EMPTY_OPTION = "__unmatched__";

export interface MappingCardProps {
  targetColumn: string;
  source: SourceMatch;
  /** Columns that really exist in `source.file`; the dropdown offers these. */
  columns: SourceColumn[];
  onChange: (next: SourceMatch) => void;
  disabled?: boolean;
}

/** One target column as seen in one source file: green, yellow or red.
 *
 * The card only edits the plan the backend sent; it never decides what a match
 * means.  Picking a column marks that choice as the user's (`auto`), and
 * "boş bırak" states the column is deliberately unmatched.
 */
export function MappingCard({
  targetColumn,
  source,
  columns,
  onChange,
  disabled = false,
}: MappingCardProps) {
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("tr");
    if (!needle) return columns;
    return columns.filter((column) => column.name.toLocaleLowerCase("tr").includes(needle));
  }, [columns, query]);

  const selected = columns.find((column) => column.name === source.column) ?? null;
  const samples = selected?.samples ?? (source.samples ?? []).map((value) => String(value));

  const select = (value: string) => {
    if (value === EMPTY_OPTION) {
      onChange({ ...source, column: null, status: "unmatched", confidence: 0, reason: "Kullanıcı boş bırakmayı seçti." });
      return;
    }
    onChange({ ...source, column: value, status: "auto", confidence: 1, reason: "Kullanıcı seçti." });
  };

  const approve = () => onChange({ ...source, status: "auto", confidence: 1, reason: source.reason ?? null });

  return (
    <article
      className={`card card--${source.status}`}
      data-status={source.status}
      data-target={targetColumn}
      data-file={source.file}
      aria-label={`${targetColumn} ← ${source.file}`}
    >
      <header className="card__head">
        <div>
          <h3 className="card__title">{targetColumn}</h3>
          <p className="card__file">{source.file}</p>
        </div>
        <span className="card__badge">{STATUS_LABEL[source.status]}</span>
      </header>

      <label className="card__field">
        <span>Kaynak sütun</span>
        <select
          value={source.column ?? EMPTY_OPTION}
          onChange={(event) => select(event.target.value)}
          disabled={disabled}
          aria-label={`${targetColumn} için kaynak sütun (${source.file})`}
        >
          <option value={EMPTY_OPTION}>(boş bırak)</option>
          {visible.map((column) => (
            <option key={column.name} value={column.name}>
              {column.name} — {column.inferred_type}
            </option>
          ))}
          {source.column && !visible.some((column) => column.name === source.column) ? (
            <option value={source.column}>{source.column}</option>
          ) : null}
        </select>
      </label>

      {columns.length > 6 ? (
        <label className="card__field card__field--search">
          <span>Sütun ara</span>
          <input
            type="search"
            value={query}
            placeholder="ör. fiyat"
            onChange={(event) => setQuery(event.target.value)}
            disabled={disabled}
            aria-label={`${targetColumn} için sütun ara (${source.file})`}
          />
        </label>
      ) : null}

      <dl className="card__meta">
        <div>
          <dt>Güven</dt>
          <dd>{Math.round(source.confidence * 100)}%</dd>
        </div>
        {selected ? (
          <div>
            <dt>Tür</dt>
            <dd>{selected.inferred_type}</dd>
          </div>
        ) : null}
      </dl>

      {source.reason ? <p className="card__reason">{source.reason}</p> : null}

      {samples.length > 0 ? (
        <p className="card__samples">
          <span>Örnek değerler:</span> {samples.slice(0, 4).join(" · ")}
        </p>
      ) : null}

      {source.status === "review" ? (
        <button type="button" className="button button--approve" onClick={approve} disabled={disabled}>
          Onayla
        </button>
      ) : null}
    </article>
  );
}

export default MappingCard;
