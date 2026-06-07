/**
 * Module: app/migrations/[jobId]/__tests__/phase-timeline.test.ts
 * Purpose: Unit tests for phase derivation logic
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { derivePhase, type Phase } from '../phase-timeline';

describe('derivePhase', () => {
  describe('discovery phase', () => {
    it('returns discovery for PENDING status', () => {
      expect(derivePhase('PENDING', 0)).toBe('discovery');
    });

    it('returns discovery for QUEUED status', () => {
      expect(derivePhase('QUEUED', 0)).toBe('discovery');
    });

    it('returns discovery for STARTING status', () => {
      expect(derivePhase('STARTING', 0)).toBe('discovery');
    });
  });

  describe('schema phase', () => {
    it('returns schema when IN_PROGRESS with 0% progress', () => {
      expect(derivePhase('IN_PROGRESS', 0)).toBe('schema');
    });

    it('returns schema when IN_PROGRESS with <20% progress', () => {
      expect(derivePhase('IN_PROGRESS', 15)).toBe('schema');
    });
  });

  describe('data phase', () => {
    it('returns data when IN_PROGRESS with 20-94% progress', () => {
      expect(derivePhase('IN_PROGRESS', 20)).toBe('data');
      expect(derivePhase('IN_PROGRESS', 50)).toBe('data');
      expect(derivePhase('IN_PROGRESS', 94)).toBe('data');
    });
  });

  describe('validation phase', () => {
    it('returns validation when IN_PROGRESS with >=95% progress', () => {
      expect(derivePhase('IN_PROGRESS', 95)).toBe('validation');
      expect(derivePhase('IN_PROGRESS', 99)).toBe('validation');
    });

    it('returns validation for COMPLETED status', () => {
      expect(derivePhase('COMPLETED', 100)).toBe('validation');
    });
  });

  describe('error states', () => {
    it('returns discovery fallback for FAILED status', () => {
      expect(derivePhase('FAILED', 50)).toBe('discovery');
    });

    it('returns discovery fallback for STOPPED status', () => {
      expect(derivePhase('STOPPED', 50)).toBe('discovery');
    });

    it('returns discovery fallback for PAUSED status', () => {
      expect(derivePhase('PAUSED', 50)).toBe('discovery');
    });
  });

  describe('case insensitivity', () => {
    it('handles lowercase status strings', () => {
      expect(derivePhase('pending', 0)).toBe('discovery');
      expect(derivePhase('running', 50)).toBe('data');
      expect(derivePhase('completed', 100)).toBe('validation');
    });
  });
});
