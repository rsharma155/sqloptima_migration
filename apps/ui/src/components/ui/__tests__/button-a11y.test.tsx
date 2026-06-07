import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "../button";

describe("Button accessibility", () => {
  it("exposes accessible name via text content", () => {
    render(<Button>Start migration</Button>);
    expect(screen.getByRole("button", { name: "Start migration" })).toBeDefined();
  });

  it("supports aria-label override", () => {
    render(<Button aria-label="Pause job">⏸</Button>);
    expect(screen.getByRole("button", { name: "Pause job" })).toBeDefined();
  });
});
