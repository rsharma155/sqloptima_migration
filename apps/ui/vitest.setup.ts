/**
 * Module: vitest.setup.ts
 * Purpose: Global test setup — registers @testing-library/jest-dom matchers with Vitest's
 *          expect and clears the DOM/mocks between tests.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
