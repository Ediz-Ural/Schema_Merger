/** The flow a non-technical user walks, with the backend mocked.
 *
 * These tests guard the rules the screen must never break: no one reaches the
 * flow without signing in, "Birleştir" stays disabled while anything is still
 * `review`, and the user's API key is sent to the
 * server without ever being kept in the browser.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import * as api from "./api";
import type { Columns, Mapping, ProviderInfo, User } from "./types";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    getToken: vi.fn(),
    setToken: vi.fn(),
    register: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    me: vi.fn(),
    getProvider: vi.fn(),
    saveProvider: vi.fn(),
    forgetKey: vi.fn(),
    upload: vi.fn(),
    analyze: vi.fn(),
    putMapping: vi.fn(),
    getColumns: vi.fn(),
    apply: vi.fn(),
    downloadArtifact: vi.fn(),
  };
});

const mocked = {
  getToken: vi.mocked(api.getToken),
  setToken: vi.mocked(api.setToken),
  register: vi.mocked(api.register),
  login: vi.mocked(api.login),
  logout: vi.mocked(api.logout),
  me: vi.mocked(api.me),
  getProvider: vi.mocked(api.getProvider),
  saveProvider: vi.mocked(api.saveProvider),
  forgetKey: vi.mocked(api.forgetKey),
  upload: vi.mocked(api.upload),
  analyze: vi.mocked(api.analyze),
  putMapping: vi.mocked(api.putMapping),
  getColumns: vi.mocked(api.getColumns),
  apply: vi.mocked(api.apply),
  downloadArtifact: vi.mocked(api.downloadArtifact),
};

const USER: User = {
  id: 1,
  email: "kullanici@example.com",
  provider: "openai",
  model: "gpt-5-nano",
  key_configured: true,
};

const CONFIGURED: ProviderInfo = {
  provider: "openai",
  embedding_provider: "openai",
  model: "gpt-5-nano",
  configured: true,
};

const NO_KEY: ProviderInfo = { ...CONFIGURED, configured: false, detail: "API anahtarı girilmedi." };

function plan(priceStatus: "auto" | "review" | "unmatched"): Mapping {
  const entries: Mapping["entries"] = [
    {
      target_column: "product_name",
      sources: [
        {
          file: "sales_tr.csv",
          column: "urun",
          confidence: 0.95,
          status: "auto",
          reason: "Adlar örtüşüyor.",
        },
      ],
    },
    {
      target_column: "unit_price",
      sources: [
        {
          file: "sales_tr.csv",
          column: priceStatus === "unmatched" ? null : "fiyat",
          confidence: priceStatus === "auto" ? 0.97 : 0.55,
          status: priceStatus,
          reason: "Emin değilim.",
        },
      ],
    },
  ];
  const counts = { auto: 0, review: 0, unmatched: 0 };
  entries.forEach((entry) => entry.sources.forEach((item) => (counts[item.status] += 1)));
  return { entries, counts };
}

const COLUMNS: Columns = {
  files: [
    {
      file: "sales_tr.csv",
      row_count: 3,
      columns: [
        { name: "urun", inferred_type: "string", samples: ["Kalem"], unique_count: 3, null_ratio: 0 },
        { name: "fiyat", inferred_type: "decimal", samples: ["12,50"], unique_count: 3, null_ratio: 0 },
      ],
    },
  ],
  target_columns: [
    { name: "product_name", type: "string", required: true },
    { name: "unit_price", type: "decimal", required: true },
  ],
};

/** Render an already signed-in app sitting on the upload step. */
async function signedIn(provider: ProviderInfo = CONFIGURED) {
  mocked.getToken.mockReturnValue("token-123");
  mocked.me.mockResolvedValue(USER);
  mocked.getProvider.mockResolvedValue(provider);
  render(<App />);
  await screen.findByRole("heading", { name: "Dosyaları yükleyin" });
}

async function reachReview(initial: Mapping) {
  await signedIn();
  mocked.upload.mockResolvedValue({
    session_id: "s1",
    inputs: ["sales_tr.csv"],
    target_schema: "schema.yaml",
    state: "uploaded",
  });
  mocked.analyze.mockResolvedValue(initial);
  mocked.getColumns.mockResolvedValue(COLUMNS);

  await userEvent.upload(
    screen.getByLabelText("Kaynak tablolar"),
    new File(["urun;fiyat\nKalem;12,50\n"], "sales_tr.csv", { type: "text/csv" }),
  );
  await userEvent.upload(
    screen.getByLabelText("Hedef şema"),
    new File(["target_columns: []\n"], "schema.yaml", { type: "application/x-yaml" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Analiz et" }));
  await screen.findByRole("heading", { name: "Planı onaylayın" });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getToken.mockReturnValue(null);
});

describe("accounts", () => {
  it("shows the sign-in form when nobody is signed in", async () => {
    render(<App />);

    expect(await screen.findByRole("button", { name: "Giriş yap" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Dosyaları yükleyin" })).toBeNull();
  });

  it("signs in and lands on the upload step", async () => {
    mocked.login.mockResolvedValue(USER);
    mocked.getProvider.mockResolvedValue(CONFIGURED);
    render(<App />);

    await userEvent.type(screen.getByLabelText("E-posta"), USER.email);
    await userEvent.type(screen.getByLabelText("Parola"), "parola1234");
    await userEvent.click(screen.getByRole("button", { name: "Giriş yap" }));

    await screen.findByRole("heading", { name: "Dosyaları yükleyin" });
    expect(mocked.login).toHaveBeenCalledWith(USER.email, "parola1234");
    expect(screen.getByText(USER.email)).toBeInTheDocument();
  });

  it("registers a new account through the same form", async () => {
    mocked.register.mockResolvedValue(USER);
    mocked.getProvider.mockResolvedValue(NO_KEY);
    render(<App />);

    await userEvent.click(screen.getByRole("tab", { name: "Hesap oluştur" }));
    await userEvent.type(screen.getByLabelText("E-posta"), "yeni@example.com");
    await userEvent.type(screen.getByLabelText("Parola"), "parola1234");
    await userEvent.click(screen.getByRole("button", { name: "Hesap oluştur" }));

    await screen.findByRole("heading", { name: "Dosyaları yükleyin" });
    expect(mocked.register).toHaveBeenCalledWith("yeni@example.com", "parola1234");
  });

  it("reports a refused sign-in in the backend's own words", async () => {
    mocked.login.mockRejectedValue(new api.ApiError(401, "E-posta ya da parola hatalı.", null));
    render(<App />);

    await userEvent.type(screen.getByLabelText("E-posta"), USER.email);
    await userEvent.type(screen.getByLabelText("Parola"), "yanlis");
    await userEvent.click(screen.getByRole("button", { name: "Giriş yap" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("E-posta ya da parola hatalı.");
  });
});

describe("provider settings", () => {
  it("blocks analysis and points at the settings until a key is entered", async () => {
    await signedIn(NO_KEY);

    expect(screen.getByRole("button", { name: "Analiz et" })).toBeDisabled();
    expect(screen.getByText(/kendi API anahtarınız gerekiyor/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /anahtar yok/ })).toBeInTheDocument();
  });

  it("sends the key to the server and never keeps it in the browser", async () => {
    await signedIn(NO_KEY);
    mocked.saveProvider.mockResolvedValue({ ...CONFIGURED, model: "gpt-4o-mini" });

    await userEvent.click(screen.getByRole("button", { name: /anahtar yok/ }));
    await userEvent.clear(screen.getByLabelText("Model"));
    await userEvent.type(screen.getByLabelText("Model"), "gpt-4o-mini");
    await userEvent.type(screen.getByLabelText("API anahtarı"), "sk-user-secret");
    await userEvent.click(screen.getByRole("button", { name: "Kaydet" }));

    await waitFor(() =>
      expect(mocked.saveProvider).toHaveBeenCalledWith({
        provider: "openai",
        model: "gpt-4o-mini",
        api_key: "sk-user-secret",
      }),
    );
    expect(JSON.stringify(window.localStorage)).not.toContain("sk-user-secret");
    expect(document.body.textContent).not.toContain("sk-user-secret");
    await waitFor(() => expect(screen.queryByText(/kendi API anahtarınız gerekiyor/)).toBeNull());
  });

  it("lets a user forget the key they entered", async () => {
    await signedIn();
    mocked.forgetKey.mockResolvedValue(NO_KEY);

    await userEvent.click(screen.getByRole("button", { name: /openai · gpt-5-nano/ }));
    await userEvent.click(screen.getByRole("button", { name: "Anahtarı unut" }));

    await waitFor(() => expect(mocked.forgetKey).toHaveBeenCalled());
  });

  it("opens the settings by itself when the server says no key is configured", async () => {
    await signedIn();
    mocked.upload.mockResolvedValue({
      session_id: "s1",
      inputs: ["sales_tr.csv"],
      target_schema: "schema.yaml",
      state: "uploaded",
    });
    mocked.analyze.mockRejectedValue(
      new api.ApiError(503, "Sağlayıcı anahtarın tanımlı değil.", {
        error: "llm_not_configured",
        message: "Sağlayıcı anahtarın tanımlı değil.",
      }),
    );
    mocked.getColumns.mockResolvedValue(COLUMNS);

    await userEvent.upload(
      screen.getByLabelText("Kaynak tablolar"),
      new File(["a;b\n1;2\n"], "sales_tr.csv", { type: "text/csv" }),
    );
    await userEvent.upload(
      screen.getByLabelText("Hedef şema"),
      new File(["target_columns: []\n"], "schema.yaml", { type: "application/x-yaml" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Analiz et" }));

    expect(await screen.findByRole("dialog", { name: "Sağlayıcı ayarları" })).toBeInTheDocument();
  });
});

describe("the review flow", () => {
  it("paints one card per proposal with the status colour the plan carries", async () => {
    await reachReview(plan("review"));

    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveAttribute("data-status", "auto");
    expect(cards[1]).toHaveAttribute("data-status", "review");
    expect(within(cards[1]).getByText("Onayınız gerekiyor")).toBeInTheDocument();
  });

  it("keeps 'Birleştir' disabled until the last review is resolved", async () => {
    await reachReview(plan("review"));

    expect(screen.getByRole("button", { name: "Birleştir" })).toBeDisabled();
    expect(screen.getByText(/onay bekliyor; kör birleştirme yapılmaz/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Onayla" }));

    expect(screen.getByRole("button", { name: "Birleştir" })).toBeEnabled();
  });

  it("enables the merge button for a plan that arrives clean", async () => {
    await reachReview(plan("auto"));

    expect(screen.getByRole("button", { name: "Birleştir" })).toBeEnabled();
  });

  it("sends a dropdown correction to the backend as a plan update", async () => {
    mocked.putMapping.mockResolvedValue(plan("auto"));
    await reachReview(plan("unmatched"));

    await userEvent.selectOptions(
      screen.getByLabelText("unit_price için kaynak sütun (sales_tr.csv)"),
      "fiyat",
    );
    await userEvent.click(screen.getByRole("button", { name: "Planı kaydet" }));

    await waitFor(() => expect(mocked.putMapping).toHaveBeenCalledTimes(1));
    const [sessionId, entries] = mocked.putMapping.mock.calls[0];
    expect(sessionId).toBe("s1");
    expect(entries[1].sources[0]).toMatchObject({ column: "fiyat", status: "auto" });
  });

  it("offers both artifacts once apply has written the output", async () => {
    mocked.putMapping.mockImplementation(async (_id, entries) => {
      const counts = { auto: 0, review: 0, unmatched: 0 };
      entries.forEach((entry) => entry.sources.forEach((item) => (counts[item.status] += 1)));
      return { entries, counts };
    });
    mocked.apply.mockResolvedValue({
      row_count: 3,
      null_cell_count: 0,
      conversion_error_count: 0,
      output_format: "csv",
      merged_file: "merged.csv",
      report_file: "merge_report.xlsx",
      skipped_sheets: [],
      warnings: [],
    });
    await reachReview(plan("review"));

    await userEvent.click(screen.getByRole("button", { name: "Onayla" }));
    await userEvent.click(screen.getByRole("button", { name: "Birleştir" }));

    await screen.findByRole("heading", { name: "Birleştirme tamamlandı" });
    expect(screen.getByRole("button", { name: "merged.csv indir" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "merge_report.xlsx indir" })).toBeInTheDocument();
  });

  it("explains a refused apply and writes nothing", async () => {
    mocked.apply.mockRejectedValue(
      new api.ApiError(409, "2 eşleştirme hâlâ onay bekliyor (review).", {
        error: "review_pending",
        message: "2 eşleştirme hâlâ onay bekliyor (review).",
        pending: [
          { target_column: "unit_price", file: "sales_tr.csv", column: "fiyat", confidence: 0.55 },
        ],
        written: false,
      }),
    );
    await reachReview(plan("auto"));

    await userEvent.click(screen.getByRole("button", { name: "Birleştir" }));

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("onay bekliyor");
    expect(banner).toHaveTextContent("Hiçbir dosya yazılmadı.");
    expect(screen.queryByRole("heading", { name: "Birleştirme tamamlandı" })).toBeNull();
  });

  it("returns to the sign-in form when the session expires mid-flow", async () => {
    await reachReview(plan("auto"));
    mocked.apply.mockRejectedValue(new api.ApiError(401, "Giriş gerekli.", null));

    await userEvent.click(screen.getByRole("button", { name: "Birleştir" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Oturumun süresi doldu");
    expect(mocked.setToken).toHaveBeenCalledWith(null);
  });
});
