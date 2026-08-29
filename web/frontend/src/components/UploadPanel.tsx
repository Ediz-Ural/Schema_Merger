import { useState } from "react";

export interface UploadPanelProps {
  busy: boolean;
  /** False while this user has not entered a provider key yet. */
  ready: boolean;
  onStart: (files: File[], targetSchema: File) => void;
  onOpenSettings: () => void;
}

/** Step 1: pick the sources and the target schema, then run Phase 1. */
export function UploadPanel({ busy, ready, onStart, onOpenSettings }: UploadPanelProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [schema, setSchema] = useState<File | null>(null);

  const picked = files.length > 0 && schema !== null;

  return (
    <section className="panel upload">
      <header className="panel__head">
        <div>
          <h2>Dosyaları yükleyin</h2>
          <p className="panel__sub">
            Analiz yalnızca sütun profillerini kullanır: satır verisi sağlayıcıya gitmez ve hiçbir
            şey birleştirilmez.
          </p>
        </div>
        <span className="pill">adım 1</span>
      </header>

      {!ready ? (
        <div className="banner banner--warn">
          <p>
            Analiz için kendi API anahtarınız gerekiyor.{" "}
            <button type="button" className="linkish" onClick={onOpenSettings}>
              Sağlayıcı ayarlarını açın
            </button>
            .
          </p>
        </div>
      ) : null}

      <div className="dropzones">
        <label className="dropzone">
          <span className="dropzone__title">Kaynak tablolar</span>
          <span className="dropzone__hint">.csv veya .xlsx · birden fazla seçebilirsiniz</span>
          <input
            type="file"
            multiple
            accept=".csv,.xlsx"
            aria-label="Kaynak tablolar"
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
          />
          {files.length > 0 ? (
            <ul className="dropzone__files">
              {files.map((file) => (
                <li key={file.name}>{file.name}</li>
              ))}
            </ul>
          ) : null}
        </label>

        <label className="dropzone">
          <span className="dropzone__title">Hedef şema</span>
          <span className="dropzone__hint">schema.yaml · birleşik tablonun sütunları</span>
          <input
            type="file"
            accept=".yaml,.yml"
            aria-label="Hedef şema"
            onChange={(event) => setSchema(event.target.files?.[0] ?? null)}
          />
          {schema ? <ul className="dropzone__files">{<li>{schema.name}</li>}</ul> : null}
        </label>
      </div>

      <button
        type="button"
        className="button button--primary"
        disabled={!picked || !ready || busy}
        onClick={() => schema && onStart(files, schema)}
      >
        {busy ? "Analiz ediliyor…" : "Analiz et"}
      </button>
    </section>
  );
}

export default UploadPanel;
