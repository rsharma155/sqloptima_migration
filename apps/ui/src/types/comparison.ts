/**
 * Module: comparison.ts
 * Purpose: Next.js frontend UI
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */
export interface TreeNode {
  name: string;
  nodeType: 'database' | 'schema' | 'table' | 'view' | 'procedure' | 'function' | 'trigger' | 'column' | 'index' | 'constraint';
  status: 'exact' | 'partial' | 'source_only' | 'target_only';
  children: TreeNode[];
  properties: Record<string, any>;
}

export interface DiffEntry {
  propertyName: string;
  sourceValue: any;
  targetValue: any;
  severity: 'info' | 'warning' | 'error';
}

export interface ObjectMatch {
  sourceObject: any;
  targetObject: any;
  matchStatus: string;
  differences: DiffEntry[];
}

export interface ComparisonResult {
  sourceDatabase: string;
  targetDatabase: string;
  totalSourceObjects: number;
  totalTargetObjects: number;
  matched: number;
  sourceOnly: number;
  targetOnly: number;
  partialMatch: number;
  tree: TreeNode[];
  durationMs: number;
}

export interface ReplicationProgress {
  running: boolean;
  paused: boolean;
  eventsCaptured: number;
  tables: Record<string, { eventsCaptured: number; lastPosition: string; lastCapturedAt: string }>;
  tablesCount: number;
}

export interface MigrationProgress {
  tableName: string;
  schemaName: string;
  totalRowsEstimate: number;
  rowsMigrated: number;
  percentage: number;
  currentChunk: number;
  totalChunks: number;
  status: string;
  throughputRowsPerSec: number;
  elapsedSeconds: number;
  estimatedRemainingSeconds: number;
}
