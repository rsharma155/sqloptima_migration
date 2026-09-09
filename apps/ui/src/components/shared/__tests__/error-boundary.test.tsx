/**
 * Module: components/shared/__tests__/error-boundary.test.tsx
 * Purpose: Unit tests for ErrorBoundary component
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { render, screen } from '@testing-library/react';
import { ErrorBoundary } from '../error-boundary';

// Suppress console.error during tests
const originalError = console.error;
beforeAll(() => {
  console.error = vi.fn();
});

afterAll(() => {
  console.error = originalError;
});

describe('ErrorBoundary', () => {
  it('renders children when there are no errors', () => {
    render(
      <ErrorBoundary>
        <div>Test content</div>
      </ErrorBoundary>
    );
    expect(screen.getByText('Test content')).toBeInTheDocument();
  });

  it('catches render errors and displays error UI', () => {
    const ThrowError = () => {
      throw new Error('Test error message');
    };

    render(
      <ErrorBoundary>
        <ThrowError />
      </ErrorBoundary>
    );

    expect(screen.getAllByText(/Something went wrong/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Test error message/i)).toBeInTheDocument();
  });

  it('displays reload button in error state', () => {
    const ThrowError = () => {
      throw new Error('Render error');
    };

    render(
      <ErrorBoundary>
        <ThrowError />
      </ErrorBoundary>
    );

    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
