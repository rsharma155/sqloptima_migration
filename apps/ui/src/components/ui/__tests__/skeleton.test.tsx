/**
 * Module: components/ui/__tests__/skeleton.test.tsx
 * Purpose: Unit tests for Skeleton loader component
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { render } from '@testing-library/react';
import { Skeleton } from '../skeleton';

describe('Skeleton', () => {
  it('renders with default classes', () => {
    const { container } = render(<Skeleton />);
    const element = container.firstChild as HTMLElement;
    expect(element).toHaveClass('animate-pulse');
    expect(element).toHaveClass('rounded-md');
    expect(element).toHaveClass('bg-muted');
  });

  it('merges custom className with defaults', () => {
    const { container } = render(<Skeleton className="h-8 w-32" />);
    const element = container.firstChild as HTMLElement;
    expect(element).toHaveClass('h-8');
    expect(element).toHaveClass('w-32');
    expect(element).toHaveClass('animate-pulse');
  });

  it('accepts HTML attributes', () => {
    const { container } = render(
      <Skeleton data-testid="loader" aria-label="Loading" />
    );
    const element = container.querySelector('[data-testid="loader"]');
    expect(element).toBeInTheDocument();
    expect(element).toHaveAttribute('aria-label', 'Loading');
  });
});
