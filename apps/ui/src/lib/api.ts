/// <reference types="node" />

/**
 * Module: api.ts
 * Purpose: Next.js frontend UI
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

export function getApiBase(): string {
  if (typeof window !== "undefined") {
    return localStorage.getItem("api_endpoint") || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8508";
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8508";
}

let API_BASE = getApiBase();

interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  timeout?: number;
  /** When true, a 401 response throws normally instead of redirecting to /login.
   *  Use for the login and setup endpoints where 401 means "wrong credentials". */
  skipAuthRedirect?: boolean;
  /** Return raw response text instead of parsing JSON (reports, exports). */
  responseType?: "json" | "text";
}

function refreshApiBase(): void {
  API_BASE = getApiBase();
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  refreshApiBase();
  const url = `${API_BASE}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...options.headers,
  };

  const token = typeof window !== "undefined" ? localStorage.getItem("auth_token") : null;
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const timeout = options.timeout ?? 30000;
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  const res = await fetch(url, {
    method: options.method || "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: controller.signal,
  });
  clearTimeout(timeoutId);

  if (!res.ok) {
    // For expired/revoked sessions on protected pages, clear state and force re-login.
    // skipAuthRedirect=true skips this for the login & setup endpoints (401 = wrong password there).
    if (res.status === 401 && typeof window !== "undefined" && !options.skipAuthRedirect) {
      clearAuthCookieAndStorage();
      window.location.replace("/login");
      throw new ApiError(401, "Session expired. Please log in again.");
    }
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    const { parseApiError, formatUserMessage } = await import("./platform-errors");
    const parsed = parseApiError(error, res.status);
    throw new ApiError(res.status, formatUserMessage(parsed));
  }

  if (options.responseType === "text") {
    return res.text() as Promise<T>;
  }

  return res.json();
}

function setAuthCookie(token: string): void {
  if (typeof window === "undefined") return;
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  // Max-Age matches the 8-hour access token TTL
  document.cookie = `auth_token=${token}; path=/; SameSite=Strict; Max-Age=28800${secure}`;
}

function clearAuthCookieAndStorage(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem("auth_token");
  localStorage.removeItem("refresh_token");
  document.cookie = "auth_token=; path=/; SameSite=Strict; Max-Age=0; expires=Thu, 01 Jan 1970 00:00:01 GMT";
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export { refreshApiBase };

// ---- Health ----

export async function healthCheck(): Promise<{ status: string }> {
  return request("/health");
}

// ---- Auth ----

export async function login(username: string, password: string): Promise<{ access_token: string }> {
  const data = await request<{ access_token: string; refresh_token: string }>("/api/v1/auth/login", {
    method: "POST",
    body: { username, password },
    skipAuthRedirect: true, // 401 here means wrong password, not an expired session
  });
  localStorage.setItem("auth_token", data.access_token);
  if (data.refresh_token) localStorage.setItem("refresh_token", data.refresh_token);
  setAuthCookie(data.access_token);
  return data;
}

export function logout(): void {
  clearAuthCookieAndStorage();
}

export function getToken(): string | null {
  return typeof window !== "undefined" ? localStorage.getItem("auth_token") : null;
}

// ---- Migrations ----

export interface MigrationRequest {
  source_connection_id: string;
  target_connection_id: string;
  tables: string[];
  schema?: string;
  target_schema?: string;
  strategy?: string;
  chunk_size?: number;
  parallel_workers?: number;
  validate_after?: boolean;
  require_target_snapshot?: boolean;
  snapshot_ref?: string | null;
}

export interface MigrationResponse {
  job_id: string;
  status: string;
  created_at: string;
  updated_at?: string;
  table_count: number;
  message: string;
  error_message?: string | null;
  logs?: MigrationLogEntry[];
  source_schema?: string | null;
  target_schema?: string | null;
  source_connection_id?: string;
  target_connection_id?: string;
  tables?: Array<{
    table: string;
    strategy?: string;
    schema?: string;
    target_schema?: string;
    status?: string;
    rows_migrated?: number;
    row_count_estimate?: number;
  }>;
}

export interface MigrationLogEntry {
  timestamp: string;
  level: "info" | "success" | "warning" | "error" | string;
  message: string;
}

export interface ProgressResponse {
  job_id: string;
  status: string;
  overall_percentage: number;
  tables_progress: Record<string, unknown>;
  elapsed_seconds: number;
  estimated_remaining_seconds: number;
  throughput_rows_per_sec: number;
  total_rows_migrated: number;
  total_rows_estimate: number;
}

export async function startMigration(req: MigrationRequest): Promise<MigrationResponse> {
  return request("/api/v1/migrations", { method: "POST", body: req });
}

export async function getMigrations(): Promise<MigrationResponse[]> {
  return request("/api/v1/migrations");
}

export async function getMigration(jobId: string): Promise<MigrationResponse> {
  return request(`/api/v1/migrations/${jobId}`);
}

export async function getMigrationLogs(
  jobId: string,
): Promise<{ job_id: string; logs: MigrationLogEntry[] }> {
  return request(`/api/v1/migrations/${jobId}/logs`);
}

export async function getMigrationProgress(jobId: string): Promise<ProgressResponse> {
  return request(`/api/v1/migrations/${jobId}/progress`);
}

export async function pauseMigration(jobId: string): Promise<{ job_id: string; status: string }> {
  return request(`/api/v1/migrations/${jobId}/pause`, { method: "POST" });
}

export async function resumeMigration(jobId: string): Promise<{ job_id: string; status: string }> {
  return request(`/api/v1/migrations/${jobId}/resume`, { method: "POST" });
}

export async function stopMigration(jobId: string): Promise<{ job_id: string; status: string }> {
  return request(`/api/v1/migrations/${jobId}/stop`, { method: "POST" });
}

export async function provisionMigrationTables(
  jobId: string,
): Promise<{ job_id: string; created_tables: string[]; message: string }> {
  return request(`/api/v1/migrations/${jobId}/provision-tables`, { method: "POST" });
}

// ---- SQL Conversion ----

export interface ConvertRequest {
  sql: string;
  object_type?: string;
  object_name?: string;
  schema?: string;
  parameters?: Array<{ name: string; type: string }>;
}

export interface PostgresSyntaxIssue {
  message: string;
  line?: number | null;
  position?: number | null;
}

export interface AppliedRepair {
  fixer: string;
  description: string;
  line?: number | null;
}

export interface ConvertResponse {
  converted_sql: string;
  success: boolean;
  warnings: string[];
  errors: string[];
  postgres_syntax_valid: boolean;
  postgres_syntax_errors: PostgresSyntaxIssue[];
  postgres_syntax_warnings: string[];
  repairs_applied: AppliedRepair[];
  repair_exhausted: boolean;
  parse_unblockers_applied: string[];
  body_transform_fallback: boolean;
  manual_review_required: boolean;
}

export async function convertSql(req: ConvertRequest): Promise<ConvertResponse> {
  return request("/api/v1/convert", { method: "POST", body: req });
}

// ---- Schema Discovery ----

export interface DiscoveryResult {
  connection_id: string;
  objects: number;
  items: unknown[];
}

export async function discoverSchema(
  connectionId: string,
  schema = "dbo",
  connectionType?: "source" | "target",
): Promise<DiscoveryResult> {
  return request("/api/v1/discover", {
    method: "POST",
    body: { connection_id: connectionId, schema, connection_type: connectionType ?? "source" },
  });
}

export async function listSchemas(
  connectionId: string,
  fallback?: Pick<ConnectionConfig, "type" | "host" | "port" | "database" | "username" | "password">,
): Promise<string[]> {
  const res = await request<{ schemas: string[] }>("/api/v1/list-schemas", {
    method: "POST",
    body: {
      connection_id: connectionId,
      connection_type: fallback?.type,
      host: fallback?.host ?? "",
      port: fallback?.port ?? 0,
      database: fallback?.database ?? "",
      username: fallback?.username ?? "",
      password: fallback?.password ?? "",
    },
  });
  return res.schemas;
}

export interface ObjectDefinitionResult {
  definition: string;
  object_type: string;
  schema: string;
  name: string;
}

export async function getObjectDefinition(
  connectionId: string,
  schema: string,
  name: string,
  objectType: string,
): Promise<ObjectDefinitionResult> {
  return request("/api/v1/object-definition", {
    method: "POST",
    body: { connection_id: connectionId, schema, name, object_type: objectType },
    timeout: 30000,
  });
}

// ---- Database / Schema listing ----

export async function listDatabases(connectionId: string): Promise<string[]> {
  const res = await request<{ databases: string[] }>("/api/v1/list-databases", {
    method: "POST",
    body: { connection_id: connectionId },
  });
  return res.databases;
}

// ---- Dependency Graph ----

export interface GraphNode {
  id: string;
  label: string;
  schema: string;
  type: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
}

export interface DependencyGraphResponse {
  connection_id: string;
  schema: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  node_count: number;
  edge_count: number;
}

export async function getDependencyGraph(
  connectionId: string,
  schema = "dbo",
): Promise<DependencyGraphResponse> {
  return request(`/api/v1/connections/${connectionId}/dependency-graph`, {
    method: "POST",
    body: { schema },
    timeout: 60000,
  });
}

// ---- Schema Comparison ----

export interface CompareRequest {
  source_connection_id: string;
  target_connection_id: string;
  source_schema?: string;
  target_schema?: string;
}

export interface CompareResponse {
  comparison_id: string;
  summary: Record<string, unknown>;
  tree: unknown[];
  source_tree: unknown[];
  target_tree: unknown[];
  duration_ms: number;
}

export async function compareDatabases(req: CompareRequest): Promise<CompareResponse> {
  return request("/api/comparison/compare", { method: "POST", body: req, timeout: 120000 });
}

// ---- Validation ----

export interface ValidationRequest {
  job_id: string;
  source_connection_id: string;
  target_connection_id: string;
  tables: Array<{ name: string; schema?: string; source_columns?: unknown[]; target_columns?: unknown[] }>;
}

export async function validateMigration(req: ValidationRequest): Promise<unknown> {
  return request("/api/v1/validate", { method: "POST", body: req });
}

// ---- Connections ----

export interface ConnectionConfig {
  id?: string;
  name: string;
  type: "source" | "target";
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  trust_server_certificate?: boolean;
}

export interface ConnectionResponse {
  id: string;
  name: string;
  type: "source" | "target";
  host: string;
  port: number;
  database: string;
  username: string;
  trust_server_certificate?: boolean;
  status: "connected" | "disconnected" | "error";
  created_at: string;
}

export async function getConnections(): Promise<ConnectionResponse[]> {
  return request("/api/v1/connections");
}

export async function createConnection(config: ConnectionConfig): Promise<ConnectionResponse> {
  return request("/api/v1/connections", { method: "POST", body: config });
}

export async function updateConnection(id: string, config: Partial<ConnectionConfig>): Promise<ConnectionResponse> {
  return request(`/api/v1/connections/${id}`, { method: "PUT", body: config });
}

export async function deleteConnection(id: string): Promise<{ message: string }> {
  return request(`/api/v1/connections/${id}`, { method: "DELETE" });
}

export async function testConnection(id: string): Promise<{ status: string; message: string }> {
  return request(`/api/v1/connections/${id}/test`, { method: "POST" });
}

export async function testRawConnection(config: ConnectionConfig): Promise<{ status: string; message: string }> {
  return request("/api/v1/connections/test-raw", { method: "POST", body: config });
}

// ---- Projects ----

export interface Project {
  id: string;
  name: string;
  description: string | null;
  source_connection_id: string | null;
  target_connection_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreateRequest {
  name: string;
  description?: string;
  source_connection_id?: string;
  target_connection_id?: string;
}

export async function getProjects(): Promise<Project[]> {
  return request("/api/v1/projects");
}

export async function createProject(req: ProjectCreateRequest): Promise<Project> {
  return request("/api/v1/projects", { method: "POST", body: req });
}

export async function updateProject(id: string, req: Partial<ProjectCreateRequest>): Promise<Project> {
  return request(`/api/v1/projects/${id}`, { method: "PUT", body: req });
}

export async function deleteProject(id: string): Promise<void> {
  return request(`/api/v1/projects/${id}`, { method: "DELETE" });
}

// ---- Assessment ----

export interface TableAssessment {
  table_name: string;
  schema_name: string;
  migration_tier: "SAFE" | "WARNING" | "BLOCKER";
  complexity_score: number;
  estimated_minutes: number;
  row_count_estimate: number;
  lob_columns: string[];
  ci_collation_columns: string[];
  blocker_types: string[];
  blockers: string[];
  warnings: string[];
  prerequisites: string[];
}

export interface DatabaseAssessment {
  database_name: string;
  overall_tier: "SAFE" | "WARNING" | "BLOCKER";
  total_tables: number;
  safe_count: number;
  warning_count: number;
  blocker_count: number;
  estimated_total_minutes: number;
  cdc_enabled_db: boolean;
  global_prerequisites: string[];
  linked_server_refs: unknown[];
  tables: TableAssessment[];
}

export interface AssessmentRequest {
  connection_id: string;
  database?: string;
  schema?: string;
}

export async function assessDatabase(req: AssessmentRequest): Promise<DatabaseAssessment> {
  return request("/api/v1/assess", { method: "POST", body: req });
}

// ---- Leveled Validation ----

export interface LeveledValidationRequest {
  source_connection_id: string;
  target_connection_id: string;
  tables: Array<{ name: string; schema?: string; target_schema?: string }>;
  levels?: number[];
  pk_column?: string;
  sample_pct?: number;
  chunks?: [unknown, unknown][];
}

export interface ValidationRunSummary {
  run_id: string;
  level: number;
  status: string;
  pass_count: number;
  fail_count: number;
  started_at: string | null;
  completed_at: string | null;
}

export async function runValidationLevels(
  jobId: string,
  req: LeveledValidationRequest,
): Promise<ValidationRunSummary[]> {
  return request(`/api/v1/jobs/${jobId}/validate`, { method: "POST", body: req });
}

export async function getValidationRuns(jobId: string): Promise<ValidationRunSummary[]> {
  return request(`/api/v1/jobs/${jobId}/validation-runs`);
}

export interface ValidationReportResult {
  validation_id: string;
  object_name: string;
  category: string;
  status: string;
  source_count?: number | null;
  target_count?: number | null;
  duration_ms?: number;
  issues?: Array<{
    message?: string;
    severity?: string;
    source_value?: unknown;
    target_value?: unknown;
    details?: Record<string, unknown>;
  }>;
  details?: Record<string, unknown>;
}

export interface RowSampleRequest {
  source_connection_id: string;
  target_connection_id: string;
  table_name: string;
  source_schema?: string;
  target_schema?: string;
  limit?: number;
}

export interface RowSampleResponse {
  table_name: string;
  source_schema: string;
  target_schema: string;
  sort_column: string;
  sort_column_type: string;
  columns: string[];
  source_rows: Record<string, string | null>[];
  target_rows: Record<string, string | null>[];
  source_count: number;
  target_count: number;
}

export async function compareRowSamples(
  jobId: string,
  req: RowSampleRequest,
): Promise<RowSampleResponse> {
  return request(`/api/v1/jobs/${jobId}/row-samples`, { method: "POST", body: req });
}

export interface ValidationReportJson {
  report_id: string;
  generated_at: string;
  overall_status: string;
  summary: {
    total_objects: number;
    passed: number;
    failed: number;
    warnings: number;
    duration_ms?: number;
  };
  results: ValidationReportResult[];
}

export async function getValidationRunReport(
  runId: string,
  fmt: "json" | "csv" | "html",
): Promise<string> {
  return request<string>(`/api/v1/validation-runs/${runId}/report?fmt=${fmt}`, {
    responseType: "text",
  });
}

export async function getValidationRunReportJson(
  runId: string,
): Promise<ValidationReportJson> {
  const raw = await getValidationRunReport(runId, "json");
  return JSON.parse(raw) as ValidationReportJson;
}

// ---- Reports ----

export interface MigrationSummaryReport {
  report_type: string;
  generated_at: string;
  job_id: string;
  status: string;
  tables_total: number;
  tables_done: number;
  rows_total: number;
  rows_migrated: number;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  table_plans: Array<{
    table: string;
    status: string;
    rows_migrated: number;
    pct_complete: number;
  }>;
}

export interface ValidationSummaryReport {
  report_type: string;
  generated_at: string;
  job_id: string;
  overall_passed: boolean;
  total_runs: number;
  levels: Array<{
    run_id: string;
    level: number;
    status: string;
    pass_count: number;
    fail_count: number;
    mismatch_count: number;
  }>;
}

export async function getMigrationReport(jobId: string): Promise<MigrationSummaryReport> {
  return request(`/api/v1/reports/migration/${jobId}`);
}

export async function downloadMigrationReportHtml(jobId: string): Promise<string> {
  return request<string>(`/api/v1/reports/migration/${jobId}?fmt=html`, {
    responseType: "text",
  });
}

export async function getValidationSummaryReport(jobId: string): Promise<ValidationSummaryReport> {
  return request(`/api/v1/reports/validation/${jobId}`);
}

// ---- Users (Admin) ----

export interface UserRecord {
  id: string;
  email: string;
  username: string;
  role: "admin" | "operator" | "viewer";
  is_active: boolean;
  created_at: string;
}

export interface CreateUserRequest {
  email: string;
  username: string;
  password: string;
  role: "admin" | "operator" | "viewer";
}

export async function getUsers(): Promise<UserRecord[]> {
  return request("/api/v1/users");
}

export async function createUser(req: CreateUserRequest): Promise<UserRecord> {
  return request("/api/v1/users", { method: "POST", body: req });
}

export async function updateUserRole(id: string, role: string): Promise<UserRecord> {
  return request(`/api/v1/users/${id}/role`, { method: "PUT", body: { role } });
}

export async function deleteUser(id: string): Promise<void> {
  return request(`/api/v1/users/${id}`, { method: "DELETE" });
}

// ---- Platform alerts ----

export interface PlatformAlert {
  id: string;
  severity: "critical" | "warning" | "info" | string;
  category: string;
  title: string;
  message: string;
  href?: string | null;
  resource_id?: string | null;
  created_at: string;
}

export interface AlertsResponse {
  alerts: PlatformAlert[];
  summary: { total: number; critical: number; warning: number; info: number };
  checked_at: string;
}

export interface AlertConfigResponse {
  webhook_configured: boolean;
  email_configured: boolean;
  email_to: string | null;
  channels_active: boolean;
}

export async function getPlatformAlerts(): Promise<AlertsResponse> {
  return request("/api/v1/alerts");
}

export async function getAlertConfig(): Promise<AlertConfigResponse> {
  return request("/api/v1/alerts/config");
}

export async function testAlertChannels(
  channel: "webhook" | "email" | "all" = "all",
): Promise<{ results: Record<string, string> }> {
  return request("/api/v1/alerts/test", { method: "POST", body: { channel } });
}

// ---- Replication ----

export interface ReplicationConcern {
  level: "info" | "warning" | "blocker";
  message: string;
  table_name?: string | null;
  property_name?: string | null;
}

export interface ReplicationStream {
  stream_id: string;
  name: string;
  status: string;
  source_connection_id?: string | null;
  target_connection_id?: string | null;
  source_schema: string;
  target_schema: string;
  tables: Array<{ name: string; pk_columns?: string[] }>;
  concerns: ReplicationConcern[];
  events_captured: number;
  events_applied: number;
  queue_depth?: number;
  state?: string;
  error_message?: string | null;
  last_checkpoint_lsn?: string | null;
  started_at?: string | null;
  stopped_at?: string | null;
}

export interface CreateReplicationStreamRequest {
  name: string;
  source_connection_id: string;
  target_connection_id: string;
  tables: string[];
  source_schema?: string;
  target_schema?: string;
  mode?: string;
}

export interface ReplicationCdcStatus {
  db_cdc_enabled: boolean;
  tables: Record<string, boolean>;
  ready: boolean;
  message: string | null;
}

export async function getReplicationCdcStatus(
  sourceConnectionId: string,
  sourceSchema: string,
  tables?: string[],
): Promise<ReplicationCdcStatus> {
  const params = new URLSearchParams({
    source_connection_id: sourceConnectionId,
    source_schema: sourceSchema,
  });
  if (tables && tables.length > 0) {
    params.set("tables", tables.join(","));
  }
  return request(`/api/v1/replication/cdc-status?${params.toString()}`);
}

export async function listReplicationStreams(): Promise<ReplicationStream[]> {
  return request("/api/v1/replication/streams");
}

export async function createReplicationStream(
  req: CreateReplicationStreamRequest,
): Promise<ReplicationStream> {
  return request("/api/v1/replication/streams", { method: "POST", body: req });
}

export async function startReplicationStream(streamId: string): Promise<ReplicationStream> {
  return request(`/api/v1/replication/streams/${streamId}/start`, { method: "POST" });
}

export async function stopReplicationStream(streamId: string): Promise<ReplicationStream> {
  return request(`/api/v1/replication/streams/${streamId}/stop`, { method: "POST" });
}

export async function pauseReplicationStream(streamId: string): Promise<ReplicationStream> {
  return request(`/api/v1/replication/streams/${streamId}/pause`, { method: "POST" });
}

export async function resumeReplicationStream(streamId: string): Promise<ReplicationStream> {
  return request(`/api/v1/replication/streams/${streamId}/resume`, { method: "POST" });
}

export async function deleteReplicationStream(streamId: string): Promise<{ deleted: boolean }> {
  return request(`/api/v1/replication/streams/${streamId}`, { method: "DELETE" });
}

export async function getReplicationStreamStatus(streamId: string): Promise<ReplicationStream> {
  return request(`/api/v1/replication/streams/${streamId}/status`);
}

// ---- First-time setup ----

export async function checkSetupRequired(): Promise<{ setup_required: boolean }> {
  return request("/api/v1/auth/setup-required");
}

export interface SetupAdminRequest {
  username: string;
  email: string;
  password: string;
}

export async function setupAdmin(req: SetupAdminRequest): Promise<UserRecord> {
  return request("/api/v1/auth/setup", { method: "POST", body: req, skipAuthRedirect: true });
}
