import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import MappingCard from "./MappingCard";
import type { MappingStatus, SourceColumn, SourceMatch } from "../types";

const COLUMNS: SourceColumn[] = [
  { name: "urun", inferred_type: "string", samples: ["Kalem"], unique_count: 3, null_ratio: 0 },
  { name: "fiyat", inferred_type: "decimal", samples: ["12,50"], unique_count: 3, null_ratio: 0 },
];

function source(overrides: Partial<SourceMatch> = {}): SourceMatch {
  return {
    file: "sales_tr.csv",
    column: "fiyat",
    confidence: 0.97,
    status: "auto",
    reason: "Ondalık örnekler örtüşüyor.",
    ...overrides,
  };
}

function renderCard(match: SourceMatch, onChange = vi.fn()) {
  render(
    <MappingCard
      targetColumn="unit_price"
      source={match}
      columns={COLUMNS}
      onChange={onChange}
    />,
  );
  return onChange;
}

describe("MappingCard", () => {
  it.each<[MappingStatus, string]>([
    ["auto", "card--auto"],
    ["review", "card--review"],
    ["unmatched", "card--unmatched"],
  ])("paints a %s match with its own colour class", (status, className) => {
    renderCard(source({ status }));

    const card = screen.getByRole("article");
    expect(card).toHaveAttribute("data-status", status);
    expect(card.className).toContain(className);
  });

  it("shows the target column, the file, the confidence and the reason", () => {
    renderCard(source());

    expect(screen.getByRole("heading", { name: "unit_price" })).toBeInTheDocument();
    expect(screen.getByText("sales_tr.csv")).toBeInTheDocument();
    expect(screen.getByText("97%")).toBeInTheDocument();
    expect(screen.getByText("Ondalık örnekler örtüşüyor.")).toBeInTheDocument();
    expect(screen.getByText(/12,50/)).toBeInTheDocument();
  });

  it("reports a dropdown correction as the user's own approved choice", async () => {
    const onChange = renderCard(source({ column: null, status: "unmatched", confidence: 0 }));

    await userEvent.selectOptions(screen.getByRole("combobox"), "fiyat");

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ column: "fiyat", status: "auto", confidence: 1 }),
    );
  });

  it("turns '(boş bırak)' into a deliberate unmatched column", async () => {
    const onChange = renderCard(source());

    await userEvent.selectOptions(screen.getByRole("combobox"), "__unmatched__");

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ column: null, status: "unmatched" }),
    );
  });

  it("offers an approve button only while the match waits for review", async () => {
    const onChange = vi.fn();
    const { unmount } = render(
      <MappingCard targetColumn="unit_price" source={source({ status: "review", confidence: 0.6 })} columns={COLUMNS} onChange={onChange} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Onayla" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ status: "auto" }));
    unmount();

    renderCard(source());
    expect(screen.queryByRole("button", { name: "Onayla" })).not.toBeInTheDocument();
  });
});
