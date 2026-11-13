import { describe, expect, it } from "vitest";

import { listQuery, readDashboardState } from "./query";

describe("dashboard query state", () => {
  it("parses only allow-listed shareable filters", () => {
    expect(readDashboardState("?disposition=review&min_score=75&lead=lead-1")).toEqual({
      filters: { disposition: "review", minScore: "75" },
      leadId: "lead-1",
      view: "leads",
    });
    expect(readDashboardState("?disposition=owned&min_score=999")).toEqual({
      filters: { disposition: "", minScore: "" },
      leadId: null,
      view: "leads",
    });
    expect(readDashboardState("?view=reviews").view).toBe("reviews");
  });

  it("builds cursor requests without losing active filters", () => {
    const query = new URLSearchParams(
      listQuery({ disposition: "qualified", minScore: "60" }, "opaque-cursor"),
    );
    expect(Object.fromEntries(query)).toEqual({
      limit: "25",
      disposition: "qualified",
      min_score: "60",
      cursor: "opaque-cursor",
    });
  });
});
