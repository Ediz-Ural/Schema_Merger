import type { Columns, Mapping, MappingEntry, SourceMatch } from "../types";
import MappingCard from "./MappingCard";

export interface MappingReviewProps {
  mapping: Mapping;
  columns: Columns | null;
  dirty: boolean;
  busy: boolean;
  onChange: (entryIndex: number, sourceIndex: number, next: SourceMatch) => void;
  onSave: () => void;
  onApply: () => void;
}

/** Phase 1 approval screen: every proposal as a card, then the merge button.
 *
 * The button is disabled while a single match is still `review`, which is the
 * same guard the backend answers `409` with -- shown here so the user sees why.
 */
export function MappingReview({
  mapping,
  columns,
  dirty,
  busy,
  onChange,
  onSave,
  onApply,
}: MappingReviewProps) {
  const { counts } = mapping;
  const blocked = counts.review > 0;
  const columnsFor = (file: string) =>
    columns?.files.find((item) => item.file === file)?.columns ?? [];

  return (
    <section className="panel review">
      <header className="panel__head">
        <div>
          <h2>Planı onaylayın</h2>
          <p className="panel__sub">
            Sarı kartlar karar bekliyor, kırmızı kartlarda eşleşme yok. Doğru kaynak sütunu seçin ya
            da sütunu boş bırakın.
          </p>
        </div>
        <span className="pill">adım 2</span>
      </header>

      <ul className="counts">
        <li className="counts__item counts__item--auto">{counts.auto} otomatik</li>
        <li className="counts__item counts__item--review">{counts.review} onay bekliyor</li>
        <li className="counts__item counts__item--unmatched">{counts.unmatched} eşleşmedi</li>
      </ul>

      <div className="review__cards">
        {mapping.entries.map((entry: MappingEntry, entryIndex) =>
          entry.sources.map((source, sourceIndex) => (
            <MappingCard
              key={`${entry.target_column}::${source.file}`}
              targetColumn={entry.target_column}
              source={source}
              columns={columnsFor(source.file)}
              disabled={busy}
              onChange={(next) => onChange(entryIndex, sourceIndex, next)}
            />
          )),
        )}
      </div>

      <footer className="review__actions">
        <button type="button" className="button" onClick={onSave} disabled={busy || !dirty}>
          Planı kaydet
        </button>
        <button
          type="button"
          className="button button--primary"
          onClick={onApply}
          disabled={busy || blocked}
          title={blocked ? "Önce onay bekleyen eşleştirmeleri çözün." : undefined}
        >
          Birleştir
        </button>
        {blocked ? (
          <p className="review__blocked" role="status">
            {counts.review} eşleştirme hâlâ onay bekliyor; kör birleştirme yapılmaz.
          </p>
        ) : null}
      </footer>
    </section>
  );
}

export default MappingReview;
