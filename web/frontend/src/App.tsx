import { useCallback, useEffect, useState } from "react";

import * as api from "./api";
import { ApiError } from "./api";
import AppHeader from "./components/AppHeader";
import AuthPanel, { type AuthMode } from "./components/AuthPanel";
import MappingReview from "./components/MappingReview";
import ResultPanel from "./components/ResultPanel";
import SettingsPanel from "./components/SettingsPanel";
import StepBar from "./components/StepBar";
import UploadPanel from "./components/UploadPanel";
import type {
  ApplyResult,
  Columns,
  Mapping,
  ProviderInfo,
  ProviderSettings,
  ReviewGuardDetail,
  SourceMatch,
  User,
} from "./types";

/** The whole product: sign in, bring your own key, then the two-phase flow.
 *
 * Nothing here re-implements a rule.  Analyze proposes, the user approves, and
 * apply merges only when the backend lets it; a refused apply (409) is shown
 * with its own message and the plan stays exactly as it was.
 */
export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(api.getToken() !== null);
  const [authError, setAuthError] = useState<string | null>(null);

  const [provider, setProvider] = useState<ProviderInfo | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [columns, setColumns] = useState<Columns | null>(null);
  const [result, setResult] = useState<ApplyResult | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [guard, setGuard] = useState<ReviewGuardDetail | null>(null);

  const signOutLocally = useCallback(() => {
    api.setToken(null);
    setUser(null);
    setProvider(null);
    setSessionId(null);
    setMapping(null);
    setColumns(null);
    setResult(null);
  }, []);

  const loadProvider = useCallback(() => {
    api
      .getProvider()
      .then(setProvider)
      .catch(() => setProvider(null));
  }, []);

  useEffect(() => {
    if (api.getToken() === null) {
      return;
    }
    api
      .me()
      .then((account) => {
        setUser(account);
        loadProvider();
      })
      .catch(() => signOutLocally())
      .finally(() => setChecking(false));
  }, [loadProvider, signOutLocally]);

  const fail = (problem: unknown) => {
    if (problem instanceof ApiError) {
      if (problem.unauthorized) {
        signOutLocally();
        setAuthError("Oturumun süresi doldu, tekrar giriş yap.");
        return;
      }
      setError(problem.message);
      setGuard(problem.guard);
      if (problem.missingKey) {
        setSettingsOpen(true);
      }
      return;
    }
    setError(problem instanceof Error ? problem.message : String(problem));
    setGuard(null);
  };

  const clearError = () => {
    setError(null);
    setGuard(null);
  };

  /* -- accounts -------------------------------------------------------- */

  const authenticate = async (mode: AuthMode, email: string, password: string) => {
    setBusy(true);
    setAuthError(null);
    try {
      const account = mode === "login" ? await api.login(email, password) : await api.register(email, password);
      setUser(account);
      loadProvider();
    } catch (problem) {
      setAuthError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    try {
      await api.logout();
    } finally {
      signOutLocally();
    }
  };

  /* -- provider settings ------------------------------------------------ */

  const saveSettings = async (settings: ProviderSettings) => {
    setBusy(true);
    setSettingsError(null);
    try {
      setProvider(await api.saveProvider(settings));
      setSettingsOpen(false);
    } catch (problem) {
      setSettingsError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  };

  const forgetKey = async () => {
    setBusy(true);
    setSettingsError(null);
    try {
      setProvider(await api.forgetKey());
    } catch (problem) {
      setSettingsError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  };

  /* -- the flow --------------------------------------------------------- */

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

  /* -- render ----------------------------------------------------------- */

  if (checking) {
    return (
      <main className="app app--center">
        <p className="loading">Oturum kontrol ediliyor…</p>
      </main>
    );
  }

  if (!user) {
    return <AuthPanel busy={busy} error={authError} onSubmit={authenticate} />;
  }

  const step = result ? "done" : mapping ? "review" : "upload";

  return (
    <main className="app">
      <AppHeader
        user={user}
        provider={provider}
        onOpenSettings={() => {
          setSettingsError(null);
          setSettingsOpen(true);
        }}
        onLogout={signOut}
      />

      <StepBar current={step} />

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
        <UploadPanel
          busy={busy}
          ready={provider?.configured ?? false}
          onStart={start}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      )}

      {settingsOpen ? (
        <SettingsPanel
          provider={provider}
          busy={busy}
          error={settingsError}
          onSave={saveSettings}
          onForget={forgetKey}
          onClose={() => setSettingsOpen(false)}
        />
      ) : null}
    </main>
  );
}

/** Recount locally so the merge button reacts to an edit before it is saved. */
function countStatuses(entries: Mapping["entries"]): Mapping["counts"] {
  const counts = { auto: 0, review: 0, unmatched: 0 };
  entries.forEach((entry) => entry.sources.forEach((source) => (counts[source.status] += 1)));
  return counts;
}
