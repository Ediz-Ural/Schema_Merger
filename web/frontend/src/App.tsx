import { useEffect, useState } from "react";

import * as api from "./api";
import { ApiError } from "./api";
import MappingReview from "./components/MappingReview";
import ResultPanel from "./components/ResultPanel";
import UploadPanel from "./components/UploadPanel";
import type {
  ApplyResult,
  Columns,
  Mapping,
  ProviderInfo,
  ReviewGuardDetail,
  SourceMatch,
} from "./types";

/** The whole two-phase flow, in the order the user walks it.
 *
 * Nothing here re-implements a rule: analyze proposes, the user approves, and
 * apply merges only when the backend lets it.  A refused apply (409) is shown
 * with its own message and the plan stays exactly as it was.
 */
export default function App() {
  const [provider, setProvider] = useState<ProviderInfo | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [columns, setColumns] = useState<Columns | null>(null);
  const [result, setResult] = useState<ApplyResult | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [guard, setGuard] = useState<ReviewGuardDetail | null>(null);

  useEffect(() => {
    api.getProvider().then(setProvider).catch(() => setProvider(null));
  }, []);

  const fail = (problem: unknown) => {
    if (problem instanceof ApiError) {
      setError(problem.message);
      setGuard(problem.guard);
      return;
    }
    setError(problem instanceof Error ? problem.message : String(problem));
    setGuard(null);
  };

  const clearError = () => {
    setError(null);
    setGuard(null);
  };

  const start = async (files: File[], schema: File) => {
    setBusy(true);
    clearError();
    try {
      const session = await api.upload(files, schema);
      setSessionId(session.session_id);
      const [plan, available] = await Promise.all([
        api.analyze(session.session_id),
        api.getColumns(session.session_id),
      ]);
      setMapping(plan);
      setColumns(available);
      setDirty(false);
    } catch (problem) {
      fail(problem);
    } finally {
      setBusy(false);
    }
  };

  const change = (entryIndex: number, sourceIndex: number, next: SourceMatch) => {
    setMapping((current) => {
      if (!current) return current;
      const entries = current.entries.map((entry, index) => {
        if (index !== entryIndex) return entry;
        return {
          ...entry,
          sources: entry.sources.map((source, position) =>
            position === sourceIndex ? next : source,
          ),
        };
      });
      return { entries, counts: countStatuses(entries) };
    });
    setDirty(true);
  };

  const save = async () => {
    if (!sessionId || !mapping) return;
    setBusy(true);
    clearError();
    try {
      setMapping(await api.putMapping(sessionId, mapping.entries));
      setDirty(false);
    } catch (problem) {
      fail(problem);
    } finally {
      setBusy(false);
    }
  };

  const merge = async () => {
    if (!sessionId || !mapping) return;
    setBusy(true);
    clearError();
    try {
      if (dirty) {
        setMapping(await api.putMapping(sessionId, mapping.entries));
        setDirty(false);
      }
      setResult(await api.apply(sessionId));
    } catch (problem) {
      fail(problem);
    } finally {
      setBusy(false);
    }
  };

  const restart = () => {
    setSessionId(null);
    setMapping(null);
    setColumns(null);
    setResult(null);
    setDirty(false);
    clearError();
  };

  return (
    <main className="app">
      <header className="app__head">
        <h1>Schema Merger</h1>
        <p className="app__tagline">
          Önce plan onaylanır, sonra birleştirilir. Onaysız hiçbir sütun birleştirilmez.
        </p>
        {provider ? (
          <p className="app__provider">
            Sağlayıcı: <strong>{provider.provider}</strong> ({provider.model || "model yok"}) —{" "}
            {provider.configured ? "anahtar yapılandırılmış" : "anahtar yok"}
          </p>
        ) : null}
      </header>

      {error ? (
        <div className="banner banner--error" role="alert">
          <p>{error}</p>
          {guard?.pending?.length ? (
            <ul>
              {guard.pending.map((item, index) => (
                <li key={`${item.target_column}-${item.file}-${index}`}>
                  {item.target_column} ← {item.file}
                  {item.column ? ` (${item.column})` : ""}
                </li>
              ))}
            </ul>
          ) : null}
          {guard?.findings?.length ? (
            <ul>
              {guard.findings.map((item, index) => (
                <li key={`${item.check}-${index}`}>{item.description}</li>
              ))}
            </ul>
          ) : null}
          {guard ? <p>Hiçbir dosya yazılmadı.</p> : null}
        </div>
      ) : null}

      {result && sessionId ? (
        <ResultPanel sessionId={sessionId} result={result} onRestart={restart} />
      ) : mapping ? (
        <MappingReview
          mapping={mapping}
          columns={columns}
          dirty={dirty}
          busy={busy}
          onChange={change}
          onSave={save}
          onApply={merge}
        />
      ) : (
        <UploadPanel busy={busy} onStart={start} />
      )}
    </main>
  );
}

/** Recount locally so the merge button reacts to an edit before it is saved. */
function countStatuses(entries: Mapping["entries"]): Mapping["counts"] {
  const counts = { auto: 0, review: 0, unmatched: 0 };
  entries.forEach((entry) => entry.sources.forEach((source) => (counts[source.status] += 1)));
  return counts;
}
