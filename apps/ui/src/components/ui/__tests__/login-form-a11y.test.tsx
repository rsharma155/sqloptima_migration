import { render } from "@testing-library/react";
import { axe, toHaveNoViolations } from "jest-axe";
import { describe, expect, it } from "vitest";

expect.extend(toHaveNoViolations);

function LoginFormStub() {
  return (
    <main>
      <h1>Sign in</h1>
      <form aria-label="Sign in form">
        <label htmlFor="username">Username</label>
        <input id="username" name="username" type="text" autoComplete="username" />
        <label htmlFor="password">Password</label>
        <input id="password" name="password" type="password" autoComplete="current-password" />
        <button type="submit">Sign in</button>
      </form>
    </main>
  );
}

describe("login form accessibility", () => {
  it("has no axe violations on representative login markup", async () => {
    const { container } = render(<LoginFormStub />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
