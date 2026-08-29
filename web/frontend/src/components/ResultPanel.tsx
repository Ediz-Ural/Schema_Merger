import { downloadUrl } from "../api";
import type { ApplyResult } from "../types";

export interface ResultPanelProps {
  sessionId: string;
  result: ApplyResult;
  onRestart: () => void;
}

/** Step 3: what the deterministic merge produced, with both downloads. */
export function ResultPanel({ sessionId, result, onRestart }: ResultPanelProps) {
  return (
    <section className="result">
      <h2>3. Birleştirme tamamlandı</h2>
      <ul className="result__stats">
        <li>{result.row_count} satır yazıldı</li>
        <li>{result.null_cell_count} boş hücre</li>
        <li>{result.conversion_error_count} dönüşüm hatası</li>
      </ul>
      <div className="result__links">
        <a className="button button--primary" href={downloadUrl(sessionId, "merged")} download>
          {result.merged_file} indir
        </a>
        <a className="button" href={downloadUrl(sessionId, "report")} download>
          {result.report_file} indir
        </a>
      </div>
      {result.skipped_sheets.length > 0 ? (
        <p className="result__note">Atlanan sheet'ler: {result.skipped_sheets.join(", ")}</p>
      ) : null}
      {result.warnings.length > 0 ? (
        <div className="result__warnings">
          <h3>Validator uyarıları</h3>
          <ul>
            {result.warnings.map((finding, index) => (
              <li key={`${finding.check}-${index}`}>{finding.description}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <button type="button" className="button" onClick={onRestart}>
        Yeni birleştirme
      </button>
    </section>
  );
}

export default ResultPanel;
