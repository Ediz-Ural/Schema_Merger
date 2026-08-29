# Schema Merger — Web UI

The visual approval screen for non-technical users. React + TypeScript + Vite, with no business
logic of its own: every decision goes through `web/backend` to the same core.

> The interface itself is in Turkish; this document is in English, like the
> [top-level README](../../README.md).

## Running it

Two processes: the backend and the frontend.

```bash
# 1) Backend (from the project root)
pip install -e ".[web]"
uvicorn web.backend.main:app --reload        # http://127.0.0.1:8000

# 2) Frontend (from this folder)
npm install
npm run dev                                  # http://localhost:5173
```

The Vite dev server proxies `/api/*` to `http://127.0.0.1:8000`, so the browser sees a single
origin. When the backend lives somewhere else:

```bash
VITE_API_TARGET=http://127.0.0.1:9000 npm run dev   # dev proxy target
VITE_API_BASE=https://api.example.com npm run build # built deployment
```

For a built deployment, remember to add the frontend's origin to the backend's
`SCHEMA_MERGER_CORS_ORIGINS`.

## Account and API key

The first screen is the gate: **create an account** (e-mail + a password of at least 8
characters) or **sign in**. After signing in, the provider chip in the top bar opens the
settings, where the user enters **their own provider, model and API key** (`PUT /provider`).

The key is **never stored in the browser**: it is sent to the server once and held there in
process memory only. No response ever returns it, which is why the settings field looks empty —
leaving it empty means "keep the key you already hold". `localStorage` holds the session token
and nothing else. Signing out or restarting the server forgets the key, and it is entered again.

While no key is configured, "Analiz et" is disabled and the screen points at the settings; if
the server answers `503 llm_not_configured`, the settings dialog opens by itself.

## The flow

1. **Upload** — source tables (`.csv`, `.xlsx`) + `schema.yaml` → `POST /upload`.
2. **Analyze** — `POST /analyze` produces the plan (the only place an LLM runs), and
   `GET /columns` fetches the real columns that fill the correction dropdown.
3. **Approve** — the plan is shown as cards:

   | Card | Status | Meaning |
   | --- | --- | --- |
   | 🟢 green | `auto` | Matched automatically, approved. |
   | 🟡 amber | `review` | Your call; **it blocks the merge**. |
   | 🔴 red | `unmatched` | No match; pick a column or leave it empty. |

   Each card shows the target column, the source file, the confidence, the reason and sample
   values. Corrections come from a dropdown whose options are the columns that **actually
   exist** in that file; `(boş bırak)` means deliberately leaving it unmatched. Edits are
   written with `PUT /mapping`.
4. **Merge** — `POST /apply`. The button is enabled **only when no `review` remains**; the
   backend enforces the same rule with `409`, and when that answer arrives the screen shows why
   and states that nothing was written.
5. **Download** — `merged.<fmt>` and `merge_report.xlsx`.

## Invariants

- The screen makes no matching decision; profiling, matching, validation and deduplication stay
  in the core behind the backend.
- Every request carries `Authorization: Bearer <token>`; when the session drops (401) the screen
  returns to the sign-in form and the token is cleared. Artifacts are fetched with the same
  token, which is why they are buttons rather than links.
- "Birleştir" is disabled while a review remains (no blind merge), and the two-phase flow is
  visible on screen: approval first, merging second.
- The API key is not stored in the browser and never comes back from the server.
  `GET /provider` reports only the provider, the model, and whether a key is held.
- Entity resolution (`cluster`) is not part of this screen; it is done from the CLI or the API,
  and `apply` still applies approved clusters.

## Tests

```bash
npm test          # vitest + Testing Library (the backend is mocked)
npm run build     # tsc --noEmit + vite build
```

The tests never reach the network: `src/api.ts` is mocked. They cover the sign-in and
registration flow and how a refused sign-in reaches the user, analysis being blocked until a key
is entered, the entered key going to the server without staying in the browser, the card
colours, "Birleştir" disabled while a review remains and enabled once resolved, a dropdown
correction turning into a `PUT /mapping` call, the download buttons after apply, the `409`
answer being explained, and the return to the sign-in form when the session expires.
