import { useState } from "react";

export interface UploadPanelProps {
  busy: boolean;
  onStart: (files: File[], targetSchema: File) => void;
}

/** Step 1: pick the sources and the target schema, then run Phase 1. */
export function UploadPanel({ busy, onStart }: UploadPanelProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [schema, setSchema] = useState<File | null>(null);

  const ready = files.length > 0 && schema !== null;

  return (
    <section className="upload">
      <h2>1. Dosyaları yükleyin</h2>
      <label className="upload__field">
        <span>Kaynak tablolar (.csv, .xlsx)</span>
        <input
          type="file"
          multiple
          accept=".csv,.xlsx"
          aria-label="Kaynak tablolar"
          onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
        />
      </label>
      <label className="upload__field">
        <span>Hedef şema (schema.yaml)</span>
        <input
          type="file"
          accept=".yaml,.yml"
          aria-label="Hedef şema"
          onChange={(event) => setSchema(event.target.files?.[0] ?? null)}
        />
      </label>
      <button
        type="button"
        className="button button--primary"
        disabled={!ready || busy}
        onClick={() => schema && onStart(files, schema)}
      >
        {busy ? "Analiz ediliyor…" : "Analiz et"}
      </button>
      <p className="upload__hint">
        Analiz yalnızca sütun profillerini kullanır; satır verisi sağlayıcıya gitmez ve
        hiçbir şey birleştirilmez.
      </p>
    </section>
  );
}

export default UploadPanel;
