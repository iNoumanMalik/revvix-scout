import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./auth", () => ({
  accessToken: vi.fn(async () => null),
  browserAuthConfigured: false,
  observeBrowserSession: vi.fn((listener: (session: null) => void) => {
    listener(null);
    return () => undefined;
  }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));

import App from "./App";
import {
  individualCandidate,
  leadDetail,
  leadPage,
  operatorSession,
  reviewQueue,
} from "./test/fixtures";

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("operator dashboard", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/v1/session") return jsonResponse(operatorSession);
      if (url === "/v1/review-queue?limit=200") return jsonResponse(reviewQueue);
      if (url === `/v1/individual-candidates/${individualCandidate.id}`) {
        return jsonResponse(individualCandidate);
      }
      if (url === `/v1/individual-candidates/${individualCandidate.id}/review`) {
        return jsonResponse({ candidate_id: individualCandidate.id, action: "link_existing" });
      }
      if (url.includes("/v1/entity-match-candidates/") && url.endsWith("/review")) {
        return jsonResponse({ status: "rejected" });
      }
      if (url.includes("opportunity-analysis-runs/latest")) {
        return jsonResponse({ detail: "Opportunity analysis run not found" }, 404);
      }
      if (url === `/v1/leads/${leadDetail.id}`) return jsonResponse(leadDetail);
      if (url.startsWith("/v1/leads?")) return jsonResponse(leadPage);
      throw new Error(`Unexpected request: ${url}`);
    });
  });

  it("filters through shareable URL state and opens evidence detail", async () => {
    const user = userEvent.setup();
    render(<App authRequired={false} />);

    expect(await screen.findByText("Fictional Alder Accounting")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Disposition"), "qualified");
    await user.type(screen.getByLabelText("Minimum score"), "60");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => {
      expect(window.location.search).toBe("?disposition=qualified&min_score=60");
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/v1/leads?limit=25&disposition=qualified&min_score=60",
        undefined,
      );
    });

    await user.click(
      screen.getByRole("button", { name: "View details for Fictional Alder Accounting" }),
    );
    expect(await screen.findByText("ICP score explanation")).toBeInTheDocument();
    expect(screen.getByText("Provider assertion")).toBeInTheDocument();
    expect(screen.getByText("Inference")).toBeInTheDocument();
    expect(screen.getByText("Hypotheses are not facts.")).toBeInTheDocument();
    expect(screen.getByText(/AI output never changes this score/i)).toBeInTheDocument();
  });

  it("does not create a broken website link when a lead has no verified domain", async () => {
    const user = userEvent.setup();
    const noDomain = {
      ...leadDetail,
      normalized_domain: null,
      company_name: "Fictional No Domain Bookkeeping",
    };
    vi.mocked(globalThis.fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/v1/session") return jsonResponse(operatorSession);
      if (url.includes("opportunity-analysis-runs/latest")) return jsonResponse({}, 404);
      if (url.startsWith("/v1/leads?")) {
        return jsonResponse({ items: [noDomain], next_cursor: null });
      }
      if (url === `/v1/leads/${noDomain.id}`) return jsonResponse(noDomain);
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<App authRequired={false} />);
    await user.click(await screen.findByRole("button", { name: /View details for Fictional No Domain/i }));
    expect(await screen.findByText("No verified domain")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "null" })).not.toBeInTheDocument();
  });

  it("has no automated serious accessibility violations in the primary view", async () => {
    const { container } = render(<App authRequired={false} />);
    await screen.findByText("Fictional Alder Accounting");
    const result = await axe.run(container);
    expect(result.violations).toEqual([]);
  });

  it("opens the unified review queue and records a duplicate decision", async () => {
    const user = userEvent.setup();
    const { container } = render(<App authRequired={false} />);
    await screen.findByText("Fictional Alder Accounting");

    await user.click(screen.getByRole("button", { name: /Review queues/i }));
    expect(await screen.findByText("Human decisions, one trail.")).toBeInTheDocument();
    expect(screen.getByText("Fictional Alder Accounting ↔ Fictional Alder Advisory")).toBeInTheDocument();
    expect((await axe.run(container)).violations).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Keep separate" }));
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/v1/entity-match-candidates/00000000-0000-4000-8000-000000000951/review",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(window.location.search).toBe("?view=reviews");
  });

  it("shows individual evidence and requires a reason before a human decision", async () => {
    const user = userEvent.setup();
    render(<App authRequired={false} />);
    await screen.findByText("Fictional Alder Accounting");
    await user.click(screen.getByRole("button", { name: /Review queues/i }));
    await user.click(await screen.findByRole("button", { name: "Inspect & decide" }));

    expect(await screen.findByText("Candidate evidence")).toBeInTheDocument();
    expect(screen.getByText("Fictional fixture")).toBeInTheDocument();
    const linkButton = screen.getByRole("button", { name: "Link possible match" });
    expect(linkButton).toBeDisabled();
    await user.type(
      screen.getByLabelText("Decision reason"),
      "Profile evidence supports the existing fictional person.",
    );
    expect(linkButton).toBeEnabled();
    await user.click(linkButton);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        `/v1/individual-candidates/${individualCandidate.id}/review`,
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("Profile evidence supports"),
        }),
      );
    });
  });

  it("supports keyboard dismissal and accessibility checks in individual review", async () => {
    const user = userEvent.setup();
    const { container } = render(<App authRequired={false} />);
    await screen.findByText("Fictional Alder Accounting");
    await user.click(screen.getByRole("button", { name: /Review queues/i }));
    const inspectButton = await screen.findByRole("button", { name: "Inspect & decide" });
    await user.click(inspectButton);

    const closeButton = await screen.findByRole("button", { name: "Close individual review" });
    expect(closeButton).toHaveFocus();
    expect(document.querySelector(".dashboard-background")).toHaveAttribute("inert");
    const dialog = screen.getByRole("dialog", { name: "Individual candidate review" });
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea:not([disabled])',
    );
    const lastFocusable = focusable.item(focusable.length - 1);
    lastFocusable.focus();
    await user.tab();
    expect(closeButton).toHaveFocus();
    await user.tab({ shift: true });
    expect(lastFocusable).toHaveFocus();
    const result = await axe.run(container);
    expect(result.violations).toEqual([]);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByText("Candidate evidence")).not.toBeInTheDocument());
    expect(inspectButton).toHaveFocus();
  });

  it("keeps lead-detail keyboard focus inside the modal", async () => {
    const user = userEvent.setup();
    const { container } = render(<App authRequired={false} />);
    const trigger = await screen.findByRole("button", {
      name: "View details for Fictional Alder Accounting",
    });
    await user.click(trigger);

    const dialog = await screen.findByRole("dialog", { name: "Lead detail" });
    const closeButton = screen.getByRole("button", { name: "Close lead detail" });
    expect(closeButton).toHaveFocus();
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled])',
    );
    const lastFocusable = focusable.item(focusable.length - 1);
    lastFocusable.focus();
    await user.tab();
    expect(closeButton).toHaveFocus();
    expect((await axe.run(container)).violations).toEqual([]);
    await user.keyboard("{Escape}");
    expect(trigger).toHaveFocus();
  });

  it("provides an accessible keyboard-ordered sign-in form", async () => {
    const user = userEvent.setup();
    const { container } = render(<App authRequired />);
    const email = await screen.findByLabelText("Email");
    const password = screen.getByLabelText("Password");
    const submit = screen.getByRole("button", { name: "Sign in" });

    await user.tab();
    expect(email).toHaveFocus();
    await user.tab();
    expect(password).toHaveFocus();
    await user.tab();
    expect(submit).toHaveFocus();
    expect((await axe.run(container)).violations).toEqual([]);
  });

  it("exposes review navigation through the mobile workspace control", async () => {
    const user = userEvent.setup();
    render(<App authRequired={false} />);
    await screen.findByText("Fictional Alder Accounting");
    await user.selectOptions(screen.getByLabelText("Mobile workspace view"), "reviews");
    expect(await screen.findByText("Human decisions, one trail.")).toBeInTheDocument();
    expect(window.location.search).toBe("?view=reviews");
  });

  it("reopens a reviewed opportunity hypothesis for correction", async () => {
    const user = userEvent.setup();
    const hypothesis = {
      id: "00000000-0000-4000-8000-000000000970",
      category: "workflow_automation",
      title: "Review fictional workflow automation",
      summary: "Advisory output grounded in fictional evidence.",
      confidence: 0.72,
      review_status: "accepted",
      citation_claim_ids: ["00000000-0000-4000-8000-000000000971"],
      missing_fields: [],
      contradictions: [],
    };
    vi.mocked(globalThis.fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/v1/session") return jsonResponse(operatorSession);
      if (url === "/v1/review-queue?limit=200") return jsonResponse(reviewQueue);
      if (url.startsWith("/v1/leads?")) return jsonResponse(leadPage);
      if (url === `/v1/leads/${leadDetail.id}`) return jsonResponse(leadDetail);
      if (url.endsWith("/opportunity-analysis-runs/latest")) {
        return jsonResponse({
          id: "00000000-0000-4000-8000-000000000972",
          hypotheses: [hypothesis],
        });
      }
      if (url === `/v1/opportunity-hypotheses/${hypothesis.id}/review/reverse`) {
        return jsonResponse({ ...hypothesis, review_status: "unreviewed" });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<App authRequired={false} />);
    await user.click(
      await screen.findByRole("button", {
        name: "View details for Fictional Alder Accounting",
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Reopen review" }));
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        `/v1/opportunity-hypotheses/${hypothesis.id}/review/reverse`,
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(await screen.findByRole("button", { name: "Accept for planning" })).toBeEnabled();
  });
});
