import { useState } from "react";

import { downloadArtifact } from "../api";
import type { ApplyResult } from "../types";

export interface ResultPanelProps {
  sessionId: string;
  result: ApplyResult;
  onRestart: () => void;
}

/** Step 3: what the deterministic merge produced, with both downloads.
 *
 * The artifacts sit behind the same bearer token as every other route, so they
 * are fetched and handed to the browser rather than linked directly.
 */
export function ResultPanel({ sessionId, result, onRestart }: ResultPanelProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = async (artifact: "merged" | "report", fileName: string) => {
    setBusy(artifact);
    setError(null);
    try {
      const blob = await downloadArtifact(sessionId, artifact);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="panel result">
      <header className="panel__head">
        <div>
          <h2>Birleştirme tamamlandı</h2>
          <p className="panel__sub">Çıktı deterministik olarak yazıldı; bu adımda LLM kullanılmadı.</p>
        </div>
        <span className="pill pill--ok">bitti</span>
      </header>

      <ul className="stats">
        <li>
          <strong>{result.row_count}</strong>
          <span>satır yazıldı</span>
        </li>
        <li>
          <strong>{result.null_cell_count}</strong>
          <span>boş hücre</span>
        </li>
        <li>
          <strong>{result.conversion_error_count}</strong>
          <span>dönüşüm hatası</span>
        </li>
      </ul>

      <div className="result__links">
        <button
          type="button"
          className="button button--primary"
          onClick={() => save("merged", result.merged_file)}
          disabled={busy !== null}
        >
          {busy === "merged" ? "Hazırlanıyor…" : `${result.merged_file} indir`}
        </button>
        <button
          type="button"
          className="button"
          onClick={() => save("report", result.report_file)}
          disabled={busy !== null}
        >
          {busy === "report" ? "Hazırlanıyor…" : `${result.report_file} indir`}
        </button>
      </div>

      {error ? (
        <p className="banner banner--error" role="alert">
          {error}
        </p>
      ) : null}

      {result.skipped_sheets.length > 0 ? (
        <p className="note">Atlanan sheet'ler: {result.skipped_sheets.join(", ")}</p>
      ) : null}

      {result.warnings.length > 0 ? (
        <div className="warnings">
          <h3>Validator uyarıları</h3>
          <ul>
            {result.warnings.map((finding, index) => (
              <li key={`${finding.check}-${index}`}>{finding.description}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <button type="button" className="button button--ghost" onClick={onRestart}>
        Yeni birleştirme
      </button>
    </section>
  );
}

export default ResultPanel;
