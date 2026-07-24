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
      // Avoid reload loop: never hard-redirect to /login when already on a public auth page.
      if (!isPublicAuthPath()) {
        window.location.replace("/login");
      }
      throw new ApiError(401, "Session expired. Please log in again.");
    }
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    const { parseApiError, formatUserMessage } = await import("./platform-errors");
    const parsed = parseApiError(error, res.status);
    throw new ApiError(res.status, formatUserMessage(parsed), parsed);
  }

  if (options.responseType === "text") {
    return res.text() as Promise<T>;
  }

  // DELETE and other endpoints may return 204/205 with an empty body.
  if (res.status === 204 || res.status === 205) {
    return undefined as T;
  }

  const contentType = res.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    const text = await res.text();
    return (text || undefined) as T;
  }

  return res.json();
}

function setAuthCookie(token: string): void {
  if (typeof window === "undefined") return;
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  // Max-Age matches the 8-hour access token TTL
  document.cookie = `auth_token=${token}; path=/; SameSite=Strict; Max-Age=28800${secure}`;
}

function isPublicAuthPath(): boolean {
  if (typeof window === "undefined") return false;
  const path = window.location.pathname;
  return path === "/login" || path === "/setup";
}

function clearAuthCookieAndStorage(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem("auth_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("auth_username");
  localStorage.removeItem("auth_role");
  document.cookie = "auth_token=; path=/; SameSite=Strict; Max-Age=0; expires=Thu, 01 Jan 1970 00:00:01 GMT";
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public payload?: import("./platform-errors").PlatformErrorPayload,
  ) {
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
  const { persistAuthRoleFromToken } = await import("@/lib/auth-role");
  const data = await request<{ access_token: string; refresh_token: string }>("/api/v1/auth/login", {
    method: "POST",
    body: { username, password },
    skipAuthRedirect: true, // 401 here means wrong password, not an expired session
  });
  localStorage.setItem("auth_token", data.access_token);
  localStorage.setItem("auth_username", username);
  if (data.refresh_token) localStorage.setItem("refresh_token", data.refresh_token);
  persistAuthRoleFromToken(data.access_token);
  setAuthCookie(data.access_token);
  return data;
}

export function getAuthUsername(): string | null {
  return typeof window !== "undefined" ? localStorage.getItem("auth_username") : null;
}

export function logout(): void {
  clearAuthCookieAndStorage();
}

/** Drop stale localStorage tokens when the session cookie is missing (prevents /login reload loops). */
export function purgeStaleAuth(): void {
  if (typeof window === "undefined" || !isPublicAuthPath()) return;
  const hasCookie = /(?:^|;\s*)auth_token=([^;]+)/.test(document.cookie);
  if (localStorage.getItem("auth_token") && !hasCookie) {
    clearAuthCookieAndStorage();
  }
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
  table_policies?: Record<string, string>;
  column_type_overrides?: Record<string, string>;
  procedures?: string[];
  functions?: string[];
  migrate_procedural_after_tables?: boolean;
}

export type TargetTablePolicy =
  | "use_existing"
  | "drop_empty_recreate"
  | "truncate_reload";

export interface MigrationPreflightTable {
  table_name: string;
  exists: boolean;
  row_count: number;
  requires_action: boolean;
  suggested_policy: TargetTablePolicy | null;
  message: string;
}

export interface PausedMigrationMatch {
  job_id: string;
  status: string;
  overlapping_tables: Array<{
    table_name: string;
    status?: string;
    rows_migrated: number;
    row_count_estimate: number;
  }>;
  rows_migrated: number;
  message: string;
}

export interface MigrationPreflightResponse {
  tables: MigrationPreflightTable[];
  paused_jobs: PausedMigrationMatch[];
  has_conflicts: boolean;
  can_start_without_prompt: boolean;
}

export interface MigrationPreflightRequest {
  source_connection_id: string;
  target_connection_id: string;
  tables: string[];
  schema?: string;
  target_schema?: string;
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
  procedural_migration?: ProceduralMigrationStatus | null;
}

export interface ProceduralMigrationObjectResult {
  name: string;
  schema_name: string;
  object_type: string;
  status: string;
  success: boolean;
  warnings: string[];
  errors: string[];
  manual_review_required: boolean;
  postgres_syntax_valid: boolean;
  converted_sql?: string;
  target_validated?: boolean;
  runtime_smoke_executed?: boolean;
  runtime_smoke_passed?: boolean;
  runtime_smoke_skipped?: boolean;
  runtime_smoke_message?: string;
}

export interface ProceduralMigrationStatus {
  status: string;
  source_schema: string;
  target_schema: string;
  selected_procedures: string[];
  selected_functions: string[];
  auto_migrate_after_tables: boolean;
  last_error?: string | null;
  objects: Record<string, ProceduralMigrationObjectResult>;
  has_selection: boolean;
}

export interface ProceduralPreviewObject {
  name: string;
  object_type: "procedure" | "function";
}

export interface ProceduralPreviewItem {
  name: string;
  object_type: string;
  schema_name: string;
  target_schema: string;
  success: boolean;
  warnings: string[];
  errors: string[];
  converted_sql: string;
  manual_review_required: boolean;
  postgres_syntax_valid: boolean;
  target_validated?: boolean;
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

export async function preflightMigration(
  req: MigrationPreflightRequest,
): Promise<MigrationPreflightResponse> {
  return request("/api/v1/migrations/preflight", { method: "POST", body: req });
}

export interface ColumnTypeOverrideOption {
  option_id: string;
  pg_ddl_type: string;
  label: string;
  description: string;
  requires_extension: string | null;
  fidelity: string;
}

export interface ColumnTypeOverrideCatalog {
  source_types: Record<string, ColumnTypeOverrideOption[]>;
}

export async function getColumnTypeOverrideOptions(): Promise<ColumnTypeOverrideCatalog> {
  return request("/api/v1/migrations/column-type-override-options");
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

export async function previewProceduralMigration(req: {
  source_connection_id: string;
  schema?: string;
  target_schema?: string;
  objects: ProceduralPreviewObject[];
}): Promise<{ items: ProceduralPreviewItem[] }> {
  return request("/api/v1/migrations/procedural/preview", { method: "POST", body: req });
}

export async function getProceduralMigrationStatus(
  jobId: string,
): Promise<ProceduralMigrationStatus> {
  return request(`/api/v1/migrations/${jobId}/procedural`);
}

export async function runProceduralMigration(
  jobId: string,
): Promise<ProceduralMigrationStatus> {
  return request(`/api/v1/migrations/${jobId}/procedural/migrate`, { method: "POST" });
}

export async function provisionMigrationTables(
  jobId: string,
): Promise<{ job_id: string; created_tables: string[]; message: string }> {
  return request(`/api/v1/migrations/${jobId}/provision-tables`, { method: "POST" });
}

export interface PostMigrationFinalizeOptions {
  finalize_identities?: boolean;
  finalize_indexes?: boolean;
  finalize_foreign_keys?: boolean;
  finalize_check_constraints?: boolean;
  finalize_defaults?: boolean;
  finalize_triggers?: boolean;
  create_indexes_concurrently?: boolean;
}

export interface PostMigrationTableInventory {
  identities: string[];
  indexes: Array<{ name: string; unsupported: string | null }>;
  foreign_keys: string[];
  check_constraints: string[];
  defaults: string[];
  triggers: string[];
}

export interface PostMigrationTableStatus {
  table_name: string;
  source_schema: string;
  target_schema: string;
  inventory: PostMigrationTableInventory;
  applied: Record<string, Record<string, string>>;
}

export interface PostMigrationStatusResponse {
  job_id: string;
  found: boolean;
  migration_status: string;
  finalize_status: string;
  last_error: string | null;
  options: Record<string, boolean>;
  tables: PostMigrationTableStatus[];
}

export async function getPostMigrationStatus(jobId: string): Promise<PostMigrationStatusResponse> {
  return request(`/api/v1/migrations/${jobId}/post-migration`);
}

export async function runPostMigrationFinalize(
  jobId: string,
  options: PostMigrationFinalizeOptions = {},
): Promise<{ job_id: string; status: string; last_error: string | null; tables: Record<string, unknown> }> {
  return request(`/api/v1/migrations/${jobId}/post-migration/finalize`, {
    method: "POST",
    body: options,
    timeout: 120000,
  });
}

// ---- SQL Conversion ----

export type DboSchemaStrategy = "map_to_public" | "preserve_dbo";

export interface ConvertRequest {
  sql: string;
  object_type?: string;
  object_name?: string;
  schema?: string;
  parameters?: Array<{ name: string; type: string }>;
  dbo_schema_strategy?: DboSchemaStrategy;
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

export interface PrivilegeScriptInfo {
  engine: string;
  title: string;
  recommended_login?: string;
  recommended_role?: string;
  default_schema?: string;
  privileges: string[];
  capabilities: string[];
  not_granted: string[];
  file: string;
  purpose: string;
  variables: Record<string, string>;
  run_example: string;
  content: string;
}

export interface PrivilegeScriptBundle {
  source: PrivilegeScriptInfo;
  target: PrivilegeScriptInfo;
}

export async function getConnectionPrivilegeScripts(): Promise<PrivilegeScriptBundle> {
  return request("/api/v1/connections/privilege-scripts");
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

// ---- Migration programs / waves (§13.1) ----

export interface MigrationWave {
  id: string;
  wave_number: number;
  name: string;
  tables: string[];
  schema_name: string;
  status: string;
  cutover_window_start: string | null;
  cutover_window_end: string | null;
  approver: string | null;
  signed_off_at: string | null;
  job_id: string | null;
}

export interface MigrationProgram {
  id: string;
  project_id: string;
  name: string;
  status: string;
  owner: string | null;
  notes: string | null;
  waves: MigrationWave[];
}

export async function listPrograms(projectId?: string): Promise<MigrationProgram[]> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return request(`/api/v1/programs${qs}`);
}

export async function getProgram(programId: string): Promise<MigrationProgram> {
  return request(`/api/v1/programs/${programId}`);
}

export async function createProgram(body: {
  project_id: string;
  name: string;
  owner?: string;
  notes?: string;
}): Promise<MigrationProgram> {
  return request("/api/v1/programs", { method: "POST", body });
}

export async function addProgramWave(
  programId: string,
  body: {
    name: string;
    tables: string[];
    schema_name?: string;
    wave_number?: number;
    cutover_window_start?: string | null;
    cutover_window_end?: string | null;
  },
): Promise<MigrationWave> {
  return request(`/api/v1/programs/${programId}/waves`, { method: "POST", body });
}

export async function scheduleProgramWave(
  waveId: string,
  body: {
    cutover_window_start?: string | null;
    cutover_window_end?: string | null;
  },
): Promise<Pick<MigrationWave, "id" | "cutover_window_start" | "cutover_window_end">> {
  return request(`/api/v1/programs/waves/${waveId}/schedule`, {
    method: "PATCH",
    body,
  });
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
  unsupported_type_columns?: Array<{ column_name: string; source_type: string }>;
  blockers: string[];
  warnings: string[];
  prerequisites: string[];
}

export interface RoutineTableDependency {
  source_schema: string;
  object_name: string;
  object_type: string;
  target_schema: string;
  target_object: string;
  status: "on_target" | "included_in_job" | "missing" | "unchecked" | string;
}

export interface RoutineAssessment {
  routine_name: string;
  schema_name: string;
  object_type: "procedure" | "function" | string;
  migration_tier: "SAFE" | "WARNING" | "BLOCKER";
  complexity_score: number;
  estimated_minutes: number;
  conversion_difficulty: string;
  detected_patterns: string[];
  blockers: string[];
  warnings: string[];
  prerequisites: string[];
  table_dependencies?: RoutineTableDependency[];
  missing_target_tables?: string[];
}

export interface DatabaseAssessment {
  database_name: string;
  overall_tier: "SAFE" | "WARNING" | "BLOCKER";
  total_tables: number;
  total_routines: number;
  safe_count: number;
  warning_count: number;
  blocker_count: number;
  routine_safe_count: number;
  routine_warning_count: number;
  routine_blocker_count: number;
  estimated_total_minutes: number;
  cdc_enabled_db: boolean;
  global_prerequisites: string[];
  linked_server_refs: unknown[];
  tables: TableAssessment[];
  routines: RoutineAssessment[];
}

export interface AssessmentRequest {
  connection_id: string;
  database?: string;
  schema?: string;
  target_connection_id?: string;
  target_schema?: string;
  selected_tables?: string[];
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
  validation_level?: number;
  validation_level_label?: string;
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

export interface AggregateColumnResult {
  column: string;
  status: string;
  source?: Record<string, unknown>;
  target?: Record<string, unknown>;
  mismatches?: string[];
  reason?: string;
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
  webhook_enabled: boolean;
  webhook_configured: boolean;
  webhook_url: string;
  email_enabled: boolean;
  email_configured: boolean;
  email_to: string | null;
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password_set: boolean;
  alert_email_to: string;
  alert_email_from: string;
  channels_active: boolean;
  source: "database" | "environment" | "none";
  updated_at: string | null;
}

export interface AlertConfigUpdateRequest {
  webhook_enabled: boolean;
  webhook_url: string;
  email_enabled: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password: string;
  alert_email_to: string;
  alert_email_from: string;
}

export async function getPlatformAlerts(): Promise<AlertsResponse> {
  return request("/api/v1/alerts");
}

export async function getAlertConfig(): Promise<AlertConfigResponse> {
  return request("/api/v1/alerts/config");
}

export async function saveAlertConfig(
  body: AlertConfigUpdateRequest,
): Promise<AlertConfigResponse> {
  return request("/api/v1/alerts/config", { method: "PUT", body });
}

export interface MigrationSettingsResponse {
  source_throttle_enabled: boolean;
  small_table_delay_sec: number;
  large_table_delay_sec: number;
  large_table_row_threshold: number;
  large_table_size_mb_threshold: number;
  max_tables_per_job: number;
  updated_at: string | null;
}

export interface MigrationSettingsUpdateRequest {
  source_throttle_enabled: boolean;
  small_table_delay_sec: number;
  large_table_delay_sec: number;
  large_table_row_threshold: number;
  large_table_size_mb_threshold: number;
  max_tables_per_job: number;
}

export async function getMigrationSettings(): Promise<MigrationSettingsResponse> {
  return request("/api/v1/admin/migration-settings");
}

export async function saveMigrationSettings(
  body: MigrationSettingsUpdateRequest,
): Promise<MigrationSettingsResponse> {
  return request("/api/v1/admin/migration-settings", { method: "PUT", body });
}

export interface ReplicationSettingsResponse {
  poll_interval_ms: number;
  poll_interval_sec: number;
  batch_size: number;
  updated_at: string | null;
  active_streams_updated?: number;
}

export interface ReplicationSettingsUpdateRequest {
  poll_interval_ms: number;
  batch_size: number;
}

export async function getReplicationSettings(): Promise<ReplicationSettingsResponse> {
  return request("/api/v1/admin/replication-settings");
}

export async function saveReplicationSettings(
  body: ReplicationSettingsUpdateRequest,
): Promise<ReplicationSettingsResponse> {
  return request("/api/v1/admin/replication-settings", { method: "PUT", body });
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

export interface ReplicationConnectionSummary {
  connection_id: string;
  name: string;
  host: string;
  port?: number | string;
  database: string;
  type: string;
}

export interface ReplicationTableProgress {
  table_schema: string;
  table_name: string;
  events_captured: number;
  batches_polled: number;
  batches_with_changes: number;
  last_batch_size: number;
  last_position?: string | null;
  last_captured_at?: string | null;
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
  is_active?: boolean;
  is_running?: boolean;
  is_paused?: boolean;
  pending_lag?: number;
}

export interface ReplicationStreamDetails extends ReplicationStream {
  source_connection?: ReplicationConnectionSummary | null;
  target_connection?: ReplicationConnectionSummary | null;
  target_tables: ReplicationTargetTableStatus[];
  checkpoints: Array<{
    table_schema: string;
    table_name: string;
    rows_applied: number;
    last_checkpoint_lsn: string;
    updated_at?: string | null;
  }>;
  operations: { insert: number; update: number; delete: number };
  duplicates_skipped: number;
  apply_failures: number;
  batches_polled: number;
  batches_with_changes: number;
  batch_size: number;
  poll_interval_ms: number;
  table_progress: ReplicationTableProgress[];
  capture_errors: string[];
  apply_errors: string[];
  all_errors: string[];
  mode: string;
  runtime_active?: boolean;
  can_start?: boolean;
}

export interface ReplicationSummary {
  total_streams: number;
  active_streams: number;
  stopped_streams: number;
  events_captured: number;
  events_applied: number;
  queue_depth: number;
  pending_lag: number;
  live: boolean;
  updated_at: string;
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

export interface ReplicationTargetTableStatus {
  table_name: string;
  exists: boolean;
  target_table_name?: string | null;
  found_in_schema?: string | null;
  row_count: number;
  schema_mismatch: boolean;
  ready: boolean;
  message: string;
}

export interface UpdateReplicationStreamRequest {
  name?: string;
  source_connection_id?: string;
  target_connection_id?: string;
  tables?: string[];
  source_schema?: string;
  target_schema?: string;
}

export async function getReplicationTargetStatus(
  targetConnectionId: string,
  targetSchema: string,
  tables: string[],
  sourceSchema = "dbo",
): Promise<ReplicationTargetTableStatus[]> {
  const params = new URLSearchParams({
    target_connection_id: targetConnectionId,
    target_schema: targetSchema,
    source_schema: sourceSchema,
    tables: tables.join(","),
  });
  return request(`/api/v1/replication/target-status?${params.toString()}`);
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

export async function getReplicationSummary(): Promise<ReplicationSummary> {
  return request("/api/v1/replication/summary");
}

export async function listReplicationStreams(): Promise<ReplicationStream[]> {
  return request("/api/v1/replication/streams");
}

export async function getReplicationStreamDetails(
  streamId: string,
): Promise<ReplicationStreamDetails> {
  return request(`/api/v1/replication/streams/${streamId}/details`);
}

export async function refreshReplicationStreamConcerns(
  streamId: string,
): Promise<{ concerns: ReplicationConcern[]; stream: ReplicationStream }> {
  return request(`/api/v1/replication/streams/${streamId}/refresh-concerns`, {
    method: "POST",
  });
}

export async function createReplicationStream(
  req: CreateReplicationStreamRequest,
): Promise<ReplicationStream> {
  return request("/api/v1/replication/streams", {
    method: "POST",
    body: req,
    timeout: 90_000,
  });
}

export async function startReplicationStream(streamId: string): Promise<ReplicationStream> {
  return request(`/api/v1/replication/streams/${streamId}/start`, {
    method: "POST",
    timeout: 90_000,
  });
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

export async function updateReplicationStream(
  streamId: string,
  req: UpdateReplicationStreamRequest,
): Promise<ReplicationStream> {
  return request(`/api/v1/replication/streams/${streamId}`, { method: "PATCH", body: req });
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
