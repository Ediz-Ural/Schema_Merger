/** The flow a non-technical user walks, with the backend mocked.
 *
 * These tests guard the one rule the screen must never break: "Birleştir" stays
 * disabled while anything is still `review`, so no blind merge can start here
 * either (spec sections 5 and 14).
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import * as api from "./api";
import type { Columns, Mapping } from "./types";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    getProvider: vi.fn(),
    upload: vi.fn(),
    analyze: vi.fn(),
    getMapping: vi.fn(),
    putMapping: vi.fn(),
    getColumns: vi.fn(),
    apply: vi.fn(),
  };
});

const mocked = {
  getProvider: vi.mocked(api.getProvider),
  upload: vi.mocked(api.upload),
  analyze: vi.mocked(api.analyze),
  putMapping: vi.mocked(api.putMapping),
  getColumns: vi.mocked(api.getColumns),
  apply: vi.mocked(api.apply),
};

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

async function reachReview(initial: Mapping) {
  mocked.upload.mockResolvedValue({
    session_id: "s1",
    inputs: ["sales_tr.csv"],
    target_schema: "schema.yaml",
    state: "uploaded",
  });
  mocked.analyze.mockResolvedValue(initial);
  mocked.getColumns.mockResolvedValue(COLUMNS);

  render(<App />);
  await userEvent.upload(
    screen.getByLabelText("Kaynak tablolar"),
    new File(["urun;fiyat\nKalem;12,50\n"], "sales_tr.csv", { type: "text/csv" }),
  );
  await userEvent.upload(
    screen.getByLabelText("Hedef şema"),
    new File(["target_columns: []\n"], "schema.yaml", { type: "application/x-yaml" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Analiz et" }));
  await screen.findByRole("heading", { name: "2. Planı onaylayın" });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getProvider.mockResolvedValue({
    provider: "openai",
    embedding_provider: "openai",
    model: "gpt-4o-mini",
    configured: true,
  });
});

describe("App", () => {
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

    const merge = screen.getByRole("button", { name: "Birleştir" });
    expect(merge).toBeDisabled();
    expect(screen.getByText(/onay bekliyor; kör birleştirme yapılmaz/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Onayla" }));

    expect(screen.getByRole("button", { name: "Birleştir" })).toBeEnabled();
  });

  it("never shows an enabled merge button for a plan that arrives clean", async () => {
    await reachReview(plan("auto"));

    expect(screen.getByRole("button", { name: "Birleştir" })).toBeEnabled();
  });

  it("sends a dropdown correction to the backend as a plan update", async () => {
    const corrected = plan("auto");
    mocked.putMapping.mockResolvedValue(corrected);
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

  it("shows both download links once apply has written the output", async () => {
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

    await screen.findByRole("heading", { name: "3. Birleştirme tamamlandı" });
    expect(screen.getByRole("link", { name: "merged.csv indir" })).toHaveAttribute(
      "href",
      expect.stringContaining("/download/s1/merged"),
    );
    expect(screen.getByRole("link", { name: "merge_report.xlsx indir" })).toHaveAttribute(
      "href",
      expect.stringContaining("/download/s1/report"),
    );
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
    expect(screen.queryByRole("heading", { name: "3. Birleştirme tamamlandı" })).toBeNull();
  });

  it("reports the configured provider without ever showing a key", async () => {
    await reachReview(plan("auto"));

    expect(screen.getByText(/Sağlayıcı:/)).toHaveTextContent("openai");
    expect(document.body.textContent).not.toMatch(/sk-|api[_-]?key/i);
  });
});
