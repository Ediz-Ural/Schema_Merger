import type { ProviderInfo, User } from "../types";

export interface AppHeaderProps {
  user: User;
  provider: ProviderInfo | null;
  onOpenSettings: () => void;
  onLogout: () => void;
}

/** Brand, who is signed in, and the provider this user is spending. */
export function AppHeader({ user, provider, onOpenSettings, onLogout }: AppHeaderProps) {
  const configured = provider?.configured ?? false;
  return (
    <header className="topbar">
      <div className="topbar__brand">
        <span className="topbar__mark" aria-hidden="true">
          ⇉
        </span>
        <div>
          <h1>Schema Merger</h1>
          <p>Önce plan onaylanır, sonra birleştirilir.</p>
        </div>
      </div>

      <div className="topbar__side">
        <button
          type="button"
          className={`chip ${configured ? "chip--ok" : "chip--warn"}`}
          onClick={onOpenSettings}
          title="Sağlayıcı ayarları"
        >
          <span className="chip__dot" aria-hidden="true" />
          {provider ? `${provider.provider} · ${provider.model}` : "sağlayıcı"}
          {configured ? "" : " · anahtar yok"}
        </button>
        <span className="topbar__user" title={user.email}>
          {user.email}
        </span>
        <button type="button" className="button button--ghost" onClick={onLogout}>
          Çıkış
        </button>
      </div>
    </header>
  );
}

export default AppHeader;
