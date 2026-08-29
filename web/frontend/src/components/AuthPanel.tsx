import { useState } from "react";

export type AuthMode = "login" | "register";

export interface AuthPanelProps {
  busy: boolean;
  error: string | null;
  onSubmit: (mode: AuthMode, email: string, password: string) => void;
}

/** Sign in or open an account.
 *
 * The form owns nothing but its two fields: the backend decides whether an
 * address is taken, whether a password is strong enough, and whether a sign-in
 * succeeds -- and says so in its own words.
 */
export function AuthPanel({ busy, error, onSubmit }: AuthPanelProps) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const ready = email.trim().length > 0 && password.length > 0;
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (ready && !busy) {
      onSubmit(mode, email.trim(), password);
    }
  };

  return (
    <section className="gate">
      <div className="gate__card">
        <div className="gate__brand">
          <span className="gate__mark" aria-hidden="true">
            ⇉
          </span>
          <div>
            <h1>Schema Merger</h1>
            <p>Dağınık tabloları onaylı bir planla tek tabloya indirin.</p>
          </div>
        </div>

        <div className="tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "login"}
            className={`tabs__tab ${mode === "login" ? "is-active" : ""}`}
            onClick={() => setMode("login")}
          >
            Giriş yap
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "register"}
            className={`tabs__tab ${mode === "register" ? "is-active" : ""}`}
            onClick={() => setMode("register")}
          >
            Hesap oluştur
          </button>
        </div>

        <form className="gate__form" onSubmit={submit}>
          <label className="field">
            <span>E-posta</span>
            <input
              type="email"
              value={email}
              autoComplete="email"
              placeholder="siz@example.com"
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="field">
            <span>Parola</span>
            <input
              type="password"
              value={password}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              placeholder={mode === "register" ? "en az 8 karakter" : "••••••••"}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          {error ? (
            <p className="banner banner--error" role="alert">
              {error}
            </p>
          ) : null}

          <button type="submit" className="button button--primary button--block" disabled={!ready || busy}>
            {busy ? "Gönderiliyor…" : mode === "login" ? "Giriş yap" : "Hesap oluştur"}
          </button>
        </form>

        <p className="gate__note">
          API anahtarınızı giriş yaptıktan sonra kendiniz girersiniz. Anahtar yalnızca sunucunun
          belleğinde tutulur; veritabanına ya da diske <strong>yazılmaz</strong> ve hiçbir yanıtta
          geri dönmez.
        </p>
      </div>
    </section>
  );
}

export default AuthPanel;
