"""Accounts, sign-in, and each user's own provider credentials.

A public deployment cannot use the operator's key for everyone, so every user
brings their own.  Two storage rules follow from that promise and are the
whole point of this module:

* What is **not** secret is persisted: the account (e-mail, password hash) and
  the provider/model choice live in a SQLite file.
* The **API key is never written anywhere**.  It is held in this process's
  memory for as long as the user is signed in, is never returned by any
  endpoint, and disappears when the server restarts.  There is no code path
  that puts it in the database, in a session workspace, or in a log line.

Passwords are stored as scrypt hashes with a per-user salt (standard library,
no extra dependency), and repeated failed sign-ins for one address are slowed
down so a public instance is not a free password oracle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import threading

from core.llm import LLMConfig


#: How long a sign-in stays valid before the user has to sign in again.
TOKEN_TTL = timedelta(hours=12)

#: Failed sign-ins tolerated for one address before it is paused briefly.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=1)

#: scrypt work factors: slow enough for an attacker, fast enough for a login.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32

MIN_PASSWORD_LENGTH = 8
PROVIDERS = ("openai", "anthropic", "ollama")

#: Model used when a user picks a provider without naming a model.
DEFAULT_MODELS = {
    "openai": "gpt-5-nano",
    "anthropic": "claude-3-5-haiku-latest",
    "ollama": "llama3.1",
}
DEFAULT_EMBEDDING_MODELS = {
    "openai": "text-embedding-3-small",
    "anthropic": "",
    "ollama": "nomic-embed-text",
}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(ValueError):
    """The request is refused for an account reason (bad input, wrong password)."""


@dataclass(frozen=True)
class User:
    """An account as stored; the password hash never leaves this module."""

    id: int
    email: str
    provider: str = "openai"
    model: str = ""
    embedding_model: str = ""


@dataclass
class ProviderCredentials:
    """One user's live provider settings; ``api_key`` stays in memory only."""

    provider: str = "openai"
    model: str = ""
    embedding_model: str = ""
    api_key: str | None = None

    def to_config(self) -> LLMConfig:
        """Build a core config from this user's own choice of provider."""

        provider = self.provider
        model = self.model or DEFAULT_MODELS.get(provider, "")
        embedding = self.embedding_model or DEFAULT_EMBEDDING_MODELS.get(provider, "")
        return LLMConfig(
            provider=provider,
            openai_api_key=self.api_key if provider == "openai" else None,
            anthropic_api_key=self.api_key if provider == "anthropic" else None,
            openai_model=model if provider == "openai" else DEFAULT_MODELS["openai"],
            anthropic_model=model if provider == "anthropic" else DEFAULT_MODELS["anthropic"],
            ollama_model=model if provider == "ollama" else DEFAULT_MODELS["ollama"],
            ollama_base_url="http://localhost:11434",
            embedding_provider=provider,
            openai_embedding_model=embedding or DEFAULT_EMBEDDING_MODELS["openai"],
            ollama_embedding_model=embedding or DEFAULT_EMBEDDING_MODELS["ollama"],
        )

    @property
    def configured(self) -> bool:
        """Ollama runs locally and needs no key; the others do."""

        return self.provider == "ollama" or bool(self.api_key)


class UserStore:
    """Accounts in SQLite, keys in memory.

    The database holds only what is safe at rest.  ``_keys`` is a plain dict on
    the running process and is the single place an API key ever lives.
    """

    def __init__(self, database: Path | None = None) -> None:
        self._path = Path(database) if database is not None else None
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(
            str(self._path) if self._path is not None else ":memory:",
            check_same_thread=False,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._create_schema()
        self._tokens: dict[str, tuple[int, datetime]] = {}
        self._keys: dict[int, str] = {}
        self._failures: dict[str, tuple[int, datetime]] = {}

    def _create_schema(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash BLOB NOT NULL,
                salt BLOB NOT NULL,
                provider TEXT NOT NULL DEFAULT 'openai',
                model TEXT NOT NULL DEFAULT '',
                embedding_model TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )

    # -- accounts ---------------------------------------------------------

    def register(self, email: str, password: str) -> User:
        """Create an account, or refuse a taken address or a weak password."""

        address = _clean_email(email)
        _check_password(password)
        salt = secrets.token_bytes(SALT_BYTES)
        with self._lock:
            if self._row_for(address) is not None:
                raise AuthError("Bu e-posta zaten kayıtlı. Giriş yapmayı deneyin.")
            cursor = self._connection.execute(
                "INSERT INTO users (email, password_hash, salt, provider, model, embedding_model,"
                " created_at) VALUES (?, ?, ?, 'openai', '', '', ?)",
                (address, _derive(password, salt), salt, datetime.now(timezone.utc).isoformat()),
            )
        return self.user(int(cursor.lastrowid))

    def authenticate(self, email: str, password: str) -> User:
        """Return the account when the password matches, else refuse."""

        address = _clean_email(email)
        self._check_lockout(address)
        row = self._row_for(address)
        if row is None or not hmac.compare_digest(
            bytes(row["password_hash"]), _derive(password, bytes(row["salt"]))
        ):
            self._record_failure(address)
            raise AuthError("E-posta ya da parola hatalı.")
        self._failures.pop(address, None)
        return _to_user(row)

    def user(self, user_id: int) -> User:
        row = self._connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise AuthError("Kullanıcı bulunamadı.")
        return _to_user(row)

    # -- sign-in tokens ---------------------------------------------------

    def issue_token(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = (user.id, datetime.now(timezone.utc) + TOKEN_TTL)
        return token

    def user_for_token(self, token: str) -> User | None:
        entry = self._tokens.get(token)
        if entry is None:
            return None
        user_id, expires_at = entry
        if expires_at <= datetime.now(timezone.utc):
            self.revoke(token)
            return None
        try:
            return self.user(user_id)
        except AuthError:
            return None

    def revoke(self, token: str) -> None:
        """Sign out: the token dies, and with the last one so does the key."""

        entry = self._tokens.pop(token, None)
        if entry is None:
            return
        user_id = entry[0]
        if not any(owner == user_id for owner, _ in self._tokens.values()):
            self._keys.pop(user_id, None)

    # -- provider settings ------------------------------------------------

    def credentials(self, user: User) -> ProviderCredentials:
        """This user's provider choice, plus the in-memory key if one is set."""

        return ProviderCredentials(
            provider=user.provider,
            model=user.model,
            embedding_model=user.embedding_model,
            api_key=self._keys.get(user.id),
        )

    def set_provider(
        self,
        user: User,
        *,
        provider: str,
        model: str | None = None,
        embedding_model: str | None = None,
        api_key: str | None = None,
    ) -> User:
        """Store the choice on disk and the key in memory only.

        ``api_key=None`` leaves whatever key the process already holds, so a
        user can switch models without retyping it; an empty string clears it.
        """

        if provider not in PROVIDERS:
            raise AuthError(f"Sağlayıcı '{provider}' desteklenmiyor: {', '.join(PROVIDERS)}.")
        chosen_model = (model or "").strip() or DEFAULT_MODELS[provider]
        chosen_embedding = (embedding_model or "").strip() or DEFAULT_EMBEDDING_MODELS.get(provider, "")
        with self._lock:
            self._connection.execute(
                "UPDATE users SET provider = ?, model = ?, embedding_model = ? WHERE id = ?",
                (provider, chosen_model, chosen_embedding, user.id),
            )
            if api_key is not None:
                key = api_key.strip()
                if key:
                    self._keys[user.id] = key
                else:
                    self._keys.pop(user.id, None)
        return self.user(user.id)

    def clear_key(self, user: User) -> None:
        self._keys.pop(user.id, None)

    # -- internals --------------------------------------------------------

    def _row_for(self, email: str) -> sqlite3.Row | None:
        return self._connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    def _check_lockout(self, email: str) -> None:
        entry = self._failures.get(email)
        if entry is None:
            return
        count, last = entry
        if count >= MAX_FAILED_ATTEMPTS and datetime.now(timezone.utc) - last < LOCKOUT:
            raise AuthError("Çok fazla başarısız deneme. Bir dakika sonra tekrar deneyin.")

    def _record_failure(self, email: str) -> None:
        now = datetime.now(timezone.utc)
        count, last = self._failures.get(email, (0, now))
        if now - last >= LOCKOUT:
            count = 0
        self._failures[email] = (count + 1, now)


def _to_user(row: sqlite3.Row) -> User:
    return User(
        id=int(row["id"]),
        email=str(row["email"]),
        provider=str(row["provider"]),
        model=str(row["model"]),
        embedding_model=str(row["embedding_model"]),
    )


def _clean_email(email: str) -> str:
    address = (email or "").strip().lower()
    if not _EMAIL.match(address):
        raise AuthError("Geçerli bir e-posta adresi girin.")
    return address


def _check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Parola en az {MIN_PASSWORD_LENGTH} karakter olmalı.")


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        (password or "").encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_BYTES,
    )
