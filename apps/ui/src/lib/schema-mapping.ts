/**
 * Resolve PostgreSQL target schema from SQL Server source schema.
 * dbo → public; all other schemas keep the same name (matches backend resolver).
 */
export function resolveTargetSchema(
  sourceSchema: string,
  explicitTarget?: string | null,
): string {
  const src = (sourceSchema || "dbo").trim();
  const explicit = explicitTarget?.trim();
  if (!explicit) {
    return src.toLowerCase() === "dbo" ? "public" : src;
  }
  // Legacy default: non-dbo sources must not land in public when SPs are schema-qualified.
  if (explicit.toLowerCase() === "public" && src.toLowerCase() !== "dbo") {
    return src;
  }
  return explicit;
}
