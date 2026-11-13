import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

vi.stubEnv("VITE_SCOUT_AUTH_MODE", "development");

Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
  value: vi.fn(() => null),
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});
