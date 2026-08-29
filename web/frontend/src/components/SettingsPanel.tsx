import { useState } from "react";

import type { ProviderInfo, ProviderSettings } from "../types";

/** Suggested model per provider; the field stays free text on purpose. */
const MODEL_HINTS: Record<string, string> = {
  openai: "gpt-5-nano",
  anthropic: "claude-3-5-haiku-latest",
  ollama: "llama3.1",
};

const PROVIDERS = [
  { id: "openai", label: "OpenAI", needsKey: true },
  { id: "anthropic", label: "Anthropic", needsKey: true },
  { id: "ollama", label: "Ollama (yerel)", needsKey: false },
];

export interface SettingsPanelProps {
  provider: ProviderInfo | null;
  busy: boolean;
  error: string | null;
  onSave: (settings: ProviderSettings) => void;
  onForget: () => void;
  onClose: () => void;
}

/** Each user's own provider, model and key.
 *
 * The key input is write-only by design: the server never sends a key back, so
 * an empty field means "keep the one you already hold", not "no key".
 */
export function SettingsPanel({
  provider,
  busy,
  error,
  onSave,
  onForget,
  onClose,
}: SettingsPanelProps) {
  const [selected, setSelected] = useState(provider?.provider ?? "openai");
  const [model, setModel] = useState(provider?.model ?? "");
  const [apiKey, setApiKey] = useState("");

  const needsKey = PROVIDERS.find((item) => item.id === selected)?.needsKey ?? true;
  const configured = provider?.configured ?? false;

  const save = (event: React.FormEvent) => {
    event.preventDefault();
    onSave({
      provider: selected,
      model: model.trim() || null,
      api_key: apiKey.trim() ? apiKey.trim() : null,
    });
    setApiKey("");
  };

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label="Sağlayıcı ayarları">
      <div className="modal__card">
        <header className="modal__head">
          <h2>Sağlayıcı ayarları</h2>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Kapat">
            ✕
          </button>
        </header>

        <form onSubmit={save}>
          <label className="field">
            <span>Sağlayıcı</span>
            <select
              value={selected}
              aria-label="Sağlayıcı"
              onChange={(event) => {
                setSelected(event.target.value);
                setModel("");
              }}
            >
              {PROVIDERS.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>Model</span>
            <input
              type="text"
              value={model}
              aria-label="Model"
              placeholder={MODEL_HINTS[selected] ?? ""}
              onChange={(event) => setModel(event.target.value)}
            />
          </label>

          {needsKey ? (
            <label className="field">
              <span>
                API anahtarı{" "}
                {configured ? <em className="field__hint">— tanımlı, değiştirmek için yazın</em> : null}
              </span>
              <input
                type="password"
                value={apiKey}
                aria-label="API anahtarı"
                autoComplete="off"
                placeholder={configured ? "••••••••  (kayıtlı)" : "sk-…"}
                onChange={(event) => setApiKey(event.target.value)}
              />
            </label>
          ) : (
            <p className="note">Ollama yerelde çalışır, anahtar istemez.</p>
          )}

          {error ? (
            <p className="banner banner--error" role="alert">
              {error}
            </p>
          ) : null}

          <p className="note note--key">
            Anahtarınız yalnızca sunucunun <strong>belleğinde</strong> tutulur: veritabanına ya da
            oturum klasörüne yazılmaz, hiçbir yanıtta geri dönmez ve sunucu yeniden başlayınca
            silinir.
          </p>

          <footer className="modal__actions">
            {configured ? (
              <button type="button" className="button" onClick={onForget} disabled={busy}>
                Anahtarı unut
              </button>
            ) : null}
            <button type="submit" className="button button--primary" disabled={busy}>
              {busy ? "Kaydediliyor…" : "Kaydet"}
            </button>
          </footer>
        </form>
      </div>
    </div>
  );
}

export default SettingsPanel;
