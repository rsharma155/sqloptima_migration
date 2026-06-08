"""
Module: procedural_converter.py
Purpose: Converts T-SQL stored procedures, functions, and triggers to PL/pgSQL
Author: Migration Platform Team
Created: 2026-05-22
Domain: Transpilation
Dependencies: sqlglot
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from domains.parsing.tsql_parse_unblocker import TsqlParseUnblocker
from domains.transpilation.ast_enhancements import ASTEnhancer
from domains.transpilation.source_preamble import attach_source_preamble, extract_source_preamble
from domains.transpilation.tsql_plpgsql_conversion_enhancer import EnhancedProceduralConverter

if TYPE_CHECKING:
    from domains.parsing.resilient_transpiler import ResilientTranspiler
    from domains.parsing.sqlglot_adapter import SqlglotParser


class ConversionDifficulty(StrEnum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    EXTREME = "extreme"


class ObjectType(StrEnum):
    PROCEDURE = "procedure"
    FUNCTION = "function"
    TRIGGER = "trigger"
    RAW = "raw"


@dataclass
class ParameterInfo:
    """Information about a procedure/function parameter."""

    name: str
    data_type: str
    is_output: bool = False
    is_readonly: bool = False
    default_value: str | None = None


@dataclass
class ProceduralObject:
    """Represents a parsed procedural object."""

    object_id: UUID = field(default_factory=uuid4)
    object_type: ObjectType = ObjectType.PROCEDURE
    schema_name: str = "dbo"
    object_name: str = ""
    parameters: list[ParameterInfo] = field(default_factory=list)
    body_sql: str = ""
    returns_table: bool = False
    return_type: str | None = None
    difficulty: ConversionDifficulty = ConversionDifficulty.SIMPLE
    detected_patterns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PostgresSyntaxIssue:
    """PostgreSQL syntax validation issue on converted output."""

    message: str
    line: int | None = None
    position: int | None = None


@dataclass
class AppliedRepairInfo:
    """Repair fix applied after conversion to resolve pgparse errors."""

    fixer: str
    description: str
    line: int | None = None


@dataclass
class ConversionResult:
    """Result of converting a procedural object."""

    source: ProceduralObject
    converted_sql: str = ""
    success: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    conversion_time_ms: float = 0.0
    postgres_syntax_valid: bool = True
    postgres_syntax_errors: list[PostgresSyntaxIssue] = field(default_factory=list)
    postgres_syntax_warnings: list[str] = field(default_factory=list)
    repairs_applied: list[AppliedRepairInfo] = field(default_factory=list)
    repair_exhausted: bool = False
    parse_unblockers_applied: list[str] = field(default_factory=list)
    body_transform_fallback: bool = False
    manual_review_required: bool = False


# Mapping of T-SQL statements/constructs to PL/pgSQL equivalents
TSQL_TO_PLG_SNIPPETS: dict[str, str] = {
    "PRINT": "RAISE NOTICE",
    "GETDATE()": "NOW()",
    "NEWID()": "gen_random_uuid()",
    "LEN(": "LENGTH(",
    "ISNULL(": "COALESCE(",
    "CHARINDEX(": "STR_POSITION(",
    "SUBSTRING(": "SUBSTRING(",
    "UPPER(": "UPPER(",
    "LOWER(": "LOWER(",
    "RTRIM(": "RTRIM(",
    "LTRIM(": "LTRIM(",
    "ABS(": "ABS(",
    "ROUND(": "ROUND(",
    "CEILING(": "CEIL(",
    "FLOOR(": "FLOOR(",
    "GETUTCDATE()": "NOW() AT TIME ZONE 'UTC'",
    "SCOPE_IDENTITY()": "LASTVAL()",
    "@@IDENTITY": "LASTVAL()",
    "@@ROWCOUNT": "GET DIAGNOSTICS integer_var = ROW_COUNT",
    "@@ERROR": "GET STACKED DIAGNOSTICS",
}

# T-SQL pattern rules: (display_name, regex, difficulty).
# Regexes use word boundaries / structural context to avoid false positives
# (e.g. sys.dm_exec_connections, @OutputFormat).
_TSQL_PATTERN_RULES: list[tuple[str, str, ConversionDifficulty | None]] = [
    ("EXEC", r"\b(?:EXEC|EXECUTE)\s*\(", ConversionDifficulty.COMPLEX),
    ("EXEC", r"\b(?:EXEC|EXECUTE)\s+[@\[\w]", ConversionDifficulty.MODERATE),
    ("sp_executesql", r"\bsp_executesql\b", ConversionDifficulty.EXTREME),
    ("CURSOR", r"\bCURSOR\b", ConversionDifficulty.COMPLEX),
    ("FETCH", r"\bFETCH\b", ConversionDifficulty.MODERATE),
    ("TRY", r"\bTRY\b", ConversionDifficulty.MODERATE),
    ("CATCH", r"\bCATCH\b", ConversionDifficulty.MODERATE),
    ("RAISERROR", r"\bRAISERROR\b", ConversionDifficulty.MODERATE),
    ("MERGE", r"\bMERGE\b", ConversionDifficulty.COMPLEX),
    (
        "OUTPUT",
        r"\bOUTPUT\s+(?:INSERTED|DELETED|\$action)\b"
        r"|\bOUTPUT\s+INTO\b"
        r"|@\w+(?:\s+[\w]+(?:\([^)]*\))?)*\s+OUTPUT\b",
        ConversionDifficulty.COMPLEX,
    ),
    ("CROSS APPLY", r"\bCROSS\s+APPLY\b", ConversionDifficulty.MODERATE),
    ("OUTER APPLY", r"\bOUTER\s+APPLY\b", ConversionDifficulty.MODERATE),
    ("UNPIVOT", r"\bUNPIVOT\b", ConversionDifficulty.COMPLEX),
    ("PIVOT", r"(?<!UN)\bPIVOT\b", ConversionDifficulty.COMPLEX),
    ("@@", r"@@\w+", ConversionDifficulty.MODERATE),
    ("#temp", r"(?<![#\w])#[\w]+|##[\w]+", ConversionDifficulty.MODERATE),
    ("GOTO", r"\bGOTO\b", ConversionDifficulty.COMPLEX),
    ("WAITFOR", r"\bWAITFOR\b", ConversionDifficulty.MODERATE),
    (
        "XML",
        r"\bAS\s+XML\b|\bFOR\s+XML\b|\.(?:value|query|exist|modify|nodes)\s*\(",
        ConversionDifficulty.COMPLEX,
    ),
    ("FOR JSON", r"\bFOR\s+JSON\b", None),
    ("FOR XML", r"\bFOR\s+XML\b", None),
    ("OPENQUERY", r"\bOPENQUERY\b", None),
    ("OPENROWSET", r"\bOPENROWSET\b", None),
    ("LINKED", r"\bLINKED\s+SERVER\b", None),
]

_COMPILED_TSQL_PATTERN_RULES: list[
    tuple[str, re.Pattern[str], ConversionDifficulty | None]
] = [
    (name, re.compile(pattern, re.IGNORECASE), difficulty)
    for name, pattern, difficulty in _TSQL_PATTERN_RULES
]

_DIFFICULTY_ORDER = [
    ConversionDifficulty.SIMPLE,
    ConversionDifficulty.MODERATE,
    ConversionDifficulty.COMPLEX,
    ConversionDifficulty.EXTREME,
]


class TsqlFunctionMapper:
    """Maps T-SQL functions to PostgreSQL equivalents."""

    FUNCTION_MAP: dict[str, str] = {
        "GETDATE": "NOW",
        "GETUTCDATE": "NOW() AT TIME ZONE 'UTC'",
        "NEWID": "gen_random_uuid",
        "LEN": "LENGTH",
        "ISNULL": "COALESCE",
        "CHARINDEX": "STR_POSITION",
        "UPPER": "UPPER",
        "LOWER": "LOWER",
        "RTRIM": "RTRIM",
        "LTRIM": "LTRIM",
        "ABS": "ABS",
        "ROUND": "ROUND",
        "CEILING": "CEIL",
        "FLOOR": "FLOOR",
        "SCOPE_IDENTITY": "LASTVAL",
        "DB_NAME": "CURRENT_DATABASE",
        "HOST_NAME": "pg_backend_pid()::TEXT || '-' || inet_server_addr()::TEXT",
        "OBJECT_NAME": "pg_class.relname",
        "IDENT_CURRENT": "last_value",
        "DATEADD": "",
        "DATEDIFF": "",
        "DATEPART": "EXTRACT",
        "YEAR": "EXTRACT(YEAR FROM",
        "MONTH": "EXTRACT(MONTH FROM",
        "DAY": "EXTRACT(DAY FROM",
        "EOMONTH": "date_trunc('month', date) + interval '1 month - 1 day'",
        "FORMAT": "TO_CHAR",
        "STRING_AGG": "STRING_AGG",
        "STRING_SPLIT": "regexp_split_to_table",
        "ROW_NUMBER": "ROW_NUMBER",
        "RANK": "RANK",
        "DENSE_RANK": "DENSE_RANK",
        "NTILE": "NTILE",
        "LEAD": "LEAD",
        "LAG": "LAG",
        "FIRST_VALUE": "FIRST_VALUE",
        "LAST_VALUE": "LAST_VALUE",
        "COALESCE": "COALESCE",
        "NULLIF": "NULLIF",
        "CAST": "CAST",
        "CONVERT": "CAST",
        "TRY_CAST": "CAST",
        "TRY_CONVERT": "CAST",
        "IIF": "CASE WHEN",
        "CHOOSE": "CASE",
        "REPLICATE": "REPEAT",
        "STUFF": "OVERLAY",
        "PATINDEX": "POSITION",
        "SPACE": "REPEAT(' ', ",
        "PARSE": "CAST",
        "REPLACE": "REPLACE",
        "RIGHT": "RIGHT",
        "LEFT": "LEFT",
        "REVERSE": "REVERSE",
        "JSON_VALUE": "jsonb_extract_path_text",
        "JSON_QUERY": "jsonb_extract_path",
        "OPENJSON": "jsonb_to_recordset",
    }


class TSqlPatternMatcher:
    """Detects T-SQL patterns in source code for complexity analysis."""

    @staticmethod
    def _scan_sql(sql: str) -> str:
        """Blank string literals so pattern rules do not match inside quotes."""
        return re.sub(r"'(?:''|[^'])*'", "''", sql)

    @staticmethod
    def detect_difficulty(sql: str) -> ConversionDifficulty:
        """Analyze SQL and return estimated conversion difficulty."""
        scan = TSqlPatternMatcher._scan_sql(sql)
        max_difficulty = ConversionDifficulty.SIMPLE

        for _, compiled, difficulty in _COMPILED_TSQL_PATTERN_RULES:
            if difficulty is None:
                continue
            if compiled.search(scan):
                if _DIFFICULTY_ORDER.index(difficulty) > _DIFFICULTY_ORDER.index(max_difficulty):
                    max_difficulty = difficulty

        return max_difficulty

    @staticmethod
    def detect_patterns(sql: str) -> list[str]:
        """Detect T-SQL-specific patterns in the code."""
        scan = TSqlPatternMatcher._scan_sql(sql)
        patterns: list[str] = []
        seen: set[str] = set()
        for name, compiled, _difficulty in _COMPILED_TSQL_PATTERN_RULES:
            if name in seen:
                continue
            if compiled.search(scan):
                patterns.append(name)
                seen.add(name)
        return patterns


class ProceduralConverter:
    """Converts T-SQL procedural objects to PL/pgSQL.

    Uses SQLGlot for base transpilation, then applies T-SQL-specific semantic
    transformations. Integrates Phase 1, 2, and 3 enhancement fixes for:
    - Parameter formatting and variable prefixes (Phase 1)
    - Hint removal and pattern flagging (Phase 2)
    - Transaction control and syntax cleanup (Phase 3)

    An optional :class:`SchemaMapper` is applied as the last step to rename
    source schema names (e.g. ``dbo``) to their PostgreSQL equivalents
    (e.g. ``public``).

    Example::

        from domains.transpilation.schema_mapping_config import SchemaMappingConfig
        from domains.transpilation.schema_mapper import SchemaMapper

        mapper = SchemaMapper(SchemaMappingConfig.default())
        converter = ProceduralConverter(schema_mapper=mapper)
    """

    def __init__(
        self,
        parser: "SqlglotParser | ResilientTranspiler | None" = None,
        schema_mapper: "SchemaMapper | None" = None,
        enable_phase_enhancements: bool = True,
    ) -> None:
        if parser is None:
            from domains.parsing.resilient_transpiler import ResilientTranspiler

            self._parser = ResilientTranspiler()
        else:
            self._parser = parser
        self._schema_mapper = schema_mapper
        self._enhanced_converter = EnhancedProceduralConverter() if enable_phase_enhancements else None

    @staticmethod
    def _unblock_source(
        sql: str,
        *,
        aggressive: bool = False,
    ) -> tuple[str, list[str], list[str]]:
        result = TsqlParseUnblocker.apply(sql, aggressive=aggressive)
        return result.sql, result.warnings, result.steps_applied

    @staticmethod
    def _record_unblockers(result: ConversionResult, steps: list[str]) -> None:
        for step in steps:
            if step not in result.parse_unblockers_applied:
                result.parse_unblockers_applied.append(step)

    def _transpile_body(self, sql: str) -> tuple[str, list[str], list[str]]:
        """Transpile inner T-SQL body with Phase C resilient parser."""
        warnings: list[str] = []
        parse_errors: list[str] = []

        if hasattr(self._parser, "transpile_with_metadata"):
            meta = self._parser.transpile_with_metadata(sql)
            warnings.extend(meta.warnings)
            parse_errors.extend(meta.parse_errors)
            if meta.success and meta.sql.strip():
                return meta.sql, warnings, parse_errors

        converted = self._parser.transpile(sql)
        if converted and converted.strip():
            return converted, warnings, parse_errors

        return "", warnings, parse_errors

    @staticmethod
    def _needs_body_transform_fallback(
        preprocessed: str,
        transpiled: str,
        source_body: str | None = None,
    ) -> bool:
        """True when SQLGlot output is untrustworthy for complex T-SQL constructs."""
        if not transpiled.strip():
            return True

        src = (source_body or preprocessed).upper()
        tr = transpiled
        pre = preprocessed.upper()

        # Cursor fetch loops
        if "CURSOR" in src and ("@@FETCH_STATUS" in src or "FETCH NEXT" in src):
            if re.search(r"\bOPEN\s+AS\b", tr, re.IGNORECASE):
                return True
            if "CURSOR FOR" in tr.upper() and " LOOP" not in tr.upper():
                return True

        # TRY/CATCH and SQL Server error metadata — SQLGlot truncates or mangles the body
        if "BEGIN TRY" in src or "BEGIN CATCH" in src:
            return True
        if any(token in src for token in ("ERROR_NUMBER()", "ERROR_MESSAGE()", "XACT_STATE()")):
            return True

        # Recursive CTEs and SQL Server query hints — prefer body-transform path
        if "UNION ALL" in src and re.search(r"\bWITH\b", source_body or preprocessed, re.IGNORECASE):
            return True
        if re.search(r"\bOPTION\s*\(", source_body or preprocessed, re.IGNORECASE):
            return True

        if re.search(r"\bOUTPUT\b", source_body or preprocessed, re.IGNORECASE):
            return True

        # RETURNING in preprocessed body before SQLGlot (OUTPUT already rewritten)
        if re.search(r"\bRETURNING\b", pre, re.IGNORECASE):
            return True

        if re.search(r"\bsp_executesql\b", source_body or preprocessed, re.IGNORECASE):
            return True
        if re.search(r"\bGOTO\b", source_body or preprocessed, re.IGNORECASE):
            return True

        # SQLGlot $variable artifacts (e.g. $StartProductID)
        if re.search(r"\$\w+", tr):
            return True

        # Severe truncation vs source body
        if len(tr.strip()) < max(80, len(preprocessed.strip()) // 4):
            return True

        return False

    @staticmethod
    def _body_transform_fallback(source_body: str, obj: ProceduralObject) -> str:
        from domains.transpilation.converters.plpgsql._body_transforms import TsqlBodyConverter
        from domains.transpilation.converters.plpgsql._models import ParamInfo
        from domains.transpilation.converters.plpgsql._output_builder import TsqlToPlpgsqlConverter

        if obj.object_type in (ObjectType.PROCEDURE, ObjectType.FUNCTION):
            full_ddl = obj.body_sql.strip()
            if full_ddl.upper().startswith("CREATE"):
                return TsqlToPlpgsqlConverter().convert(full_ddl)

            ddl_kw = "PROCEDURE" if obj.object_type == ObjectType.PROCEDURE else "FUNCTION"
            # Strip accidental AS/BEGIN prefix when strip_ddl_wrapper missed outer wrapper
            inner = source_body.strip()
            inner = re.sub(r"^AS\s+BEGIN\s+", "", inner, flags=re.IGNORECASE)
            ddl = (
                f"CREATE {ddl_kw} {obj.schema_name}.{obj.object_name}\n"
                f"AS\nBEGIN\n{inner}\nEND"
            )
            return TsqlToPlpgsqlConverter().convert(ddl)

        param_infos = [
            ParamInfo(
                name=p.name.lstrip("@").removeprefix("p_"),
                pg_type=p.data_type,
                is_output=p.is_output,
                is_readonly=p.is_readonly,
                default_value=p.default_value,
            )
            for p in obj.parameters
        ]
        return TsqlBodyConverter.convert(source_body, param_infos)

    @staticmethod
    def detect_object_type(sql: str) -> str:
        """Detect whether SQL is a procedure, function, trigger, or ad-hoc SQL.

        Returns: \"procedure\", \"function\", \"trigger\", or \"raw\".
        """
        import re
        stripped = sql.strip()
        upper = stripped.upper()

        # Remove leading comments and blank lines to find the first statement
        lines = upper.split("\n")
        first_stmt = ""
        for line in lines:
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith("--"):
                continue
            first_stmt = stripped_line
            break

        # Normalize whitespace for matching
        first_stmt = re.sub(r'\s+', ' ', first_stmt)

        if first_stmt.startswith("CREATE PROCEDURE") or first_stmt.startswith("CREATE PROC"):
            return ObjectType.PROCEDURE.value
        if first_stmt.startswith("CREATE FUNCTION") or first_stmt.startswith("CREATE FUNC"):
            return ObjectType.FUNCTION.value
        if first_stmt.startswith("CREATE TRIGGER"):
            return ObjectType.TRIGGER.value

        return ObjectType.RAW.value

    def convert_adhoc(self, sql: str) -> ConversionResult:
        """Convert a simple ad-hoc T-SQL statement (no wrapping)."""
        obj = ProceduralObject(
            object_type=ObjectType.RAW,
            schema_name="",
            object_name="",
            body_sql=sql,
        )
        result = ConversionResult(source=obj)

        try:
            from domains.transpilation.sql_expression_converter import TsqlExpressionConverter

            from domains.transpilation.tsql_pattern_converter import TsqlPatternConverter

            preamble, sql_body = extract_source_preamble(sql)
            sql_body, unblock_warnings, unblock_steps = self._unblock_source(sql_body)
            result.warnings.extend(unblock_warnings)
            self._record_unblockers(result, unblock_steps)
            preprocessed, preproc_warnings = self._preprocess_tsql(sql_body)
            result.warnings.extend(preproc_warnings)
            converted, tx_warnings, parse_errors = self._transpile_body(preprocessed)
            result.warnings.extend(tx_warnings)
            if parse_errors:
                for err in parse_errors[:3]:
                    result.warnings.append(f"T-SQL parse note: {err}")
            if not converted.strip():
                converted = self._body_transform_fallback(sql_body, obj)
                result.body_transform_fallback = True
                result.warnings.append(
                    "Used PL/pgSQL body-transform fallback (SQLGlot transpile unavailable)"
                )
            post_result = TsqlPatternConverter().postprocess(converted)
            converted = post_result.sql
            result.warnings.extend(post_result.warnings)
            converted = TsqlExpressionConverter.convert_expression(converted)

            # Optional schema-name remapping (e.g. dbo → public)
            if self._schema_mapper is not None:
                converted = self._schema_mapper.apply(converted)

            result.converted_sql = attach_source_preamble(preamble, converted)
            result.success = True
        except Exception as e:
            result.errors.append(str(e))
            result.success = False

        return result

    @staticmethod
    def _first_statement_line(sql: str) -> str:
        """Extract the first non-comment, non-blank line from SQL text."""
        for line in sql.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("--"):
                import re
                return re.sub(r'\s+', ' ', stripped)
        return ""

    def auto_convert(self, sql: str) -> ConversionResult:
        """Automatically detect the SQL type and convert accordingly.

        For PROCEDURE and FUNCTION objects, this delegates to
        :class:`TsqlToPlpgsqlConverter` which correctly parses the full
        T-SQL header (name, schema, parameters) and applies all 30
        transformation categories identified in the gap analysis.
        """
        import re as _re
        obj_type = self.detect_object_type(sql)

        # When a file has a preamble (e.g. CREATE TYPE) before the CREATE PROCEDURE,
        # detect_object_type only sees the preamble. Fall back to a full-text scan.
        if obj_type == ObjectType.RAW.value:
            if _re.search(r'\bCREATE\s+(?:PROCEDURE|PROC)\b', sql, _re.IGNORECASE):
                obj_type = ObjectType.PROCEDURE.value
            elif _re.search(r'\bCREATE\s+FUNCTION\b', sql, _re.IGNORECASE):
                obj_type = ObjectType.FUNCTION.value

        if obj_type in (ObjectType.PROCEDURE.value, ObjectType.FUNCTION.value):
            hint = (
                ObjectType.FUNCTION
                if obj_type == ObjectType.FUNCTION.value
                else ObjectType.PROCEDURE
            )
            return self._convert_sproc_unified(sql, object_type_hint=hint)

        if obj_type == ObjectType.TRIGGER.value:
            import re
            first_line = self._first_statement_line(sql)
            name_match = re.search(
                r'CREATE\s+TRIGGER\s+(?:\[?\w+\]?\.)?\[?(\w+)\]?',
                first_line, re.IGNORECASE,
            )
            name = name_match.group(1) if name_match else "trg_converted"
            schema_match = re.search(
                r'CREATE\s+TRIGGER\s+\[?(\w+)\]?\.',
                first_line, re.IGNORECASE,
            )
            schema = schema_match.group(1) if schema_match else "dbo"
            return self.convert_trigger(
                schema, name, name, "BEFORE", "INSERT OR UPDATE OR DELETE", sql,
            )

        return self.convert_adhoc(sql)

    def _convert_sproc_unified(
        self,
        sql: str,
        *,
        object_type_hint: ObjectType | None = None,
    ) -> ConversionResult:
        """Single pipeline for all PROCEDURE/FUNCTION conversions.

        Phase 0: dynamic SQL pre-pass (inline EXEC/sp_executesql)
        Phase 1: PivotConverter when applicable
        Phase 2: TsqlToPlpgsqlConverter (always)
        Phase 3: schema mapping (when configured)
        """
        from domains.transpilation.converters.pivot_converter import PivotConverter
        from domains.transpilation.converters.tsql_to_plpgsql import (
            TsqlHeaderParser,
            TsqlToPlpgsqlConverter,
        )
        from domains.transpilation.dynamic_sql.prepass import apply_dynamic_sql_prepass

        unblocked, unblock_warnings, unblock_steps = self._unblock_source(sql, aggressive=False)
        prepass = apply_dynamic_sql_prepass(unblocked)
        working_sql = prepass.sql

        info = TsqlHeaderParser.parse(working_sql)
        detected_type = object_type_hint
        if detected_type is None:
            detected_type = (
                ObjectType.FUNCTION
                if re.search(r"\bCREATE\s+FUNCTION\b", working_sql, re.IGNORECASE)
                else ObjectType.PROCEDURE
            )
        params = [
            ParameterInfo(
                name=f"p_{p.name}",
                data_type=p.pg_type,
                is_output=p.is_output,
                default_value=p.default_value,
            )
            for p in info.parameters
        ]
        obj = ProceduralObject(
            object_type=detected_type,
            schema_name=info.schema,
            object_name=info.name,
            parameters=params,
            body_sql=working_sql,
            difficulty=TSqlPatternMatcher.detect_difficulty(working_sql),
            detected_patterns=TSqlPatternMatcher.detect_patterns(working_sql),
        )
        result = ConversionResult(source=obj)
        result.warnings.extend(unblock_warnings)
        self._record_unblockers(result, unblock_steps)
        if prepass.applied:
            result.warnings.extend(prepass.warnings)

        if PivotConverter.can_handle(working_sql):
            pivot_result = PivotConverter.convert(working_sql)
            result.warnings.extend(pivot_result.warnings)
            if pivot_result.success and pivot_result.converted_sql:
                result.converted_sql = pivot_result.converted_sql
                result.success = True
                if self._schema_mapper is not None:
                    result.converted_sql = self._schema_mapper.apply(result.converted_sql)
                return result

        try:
            try:
                result.converted_sql = TsqlToPlpgsqlConverter().convert(working_sql)
            except Exception:
                aggressive_sql, aggressive_warnings, aggressive_steps = self._unblock_source(
                    working_sql, aggressive=True
                )
                result.warnings.extend(aggressive_warnings)
                self._record_unblockers(result, aggressive_steps)
                aggressive_sql = apply_dynamic_sql_prepass(aggressive_sql).sql
                result.converted_sql = TsqlToPlpgsqlConverter().convert(aggressive_sql)
                result.warnings.append(
                    "Retried conversion with aggressive T-SQL parse unblockers after initial failure"
                )
            result.success = True
            if obj.difficulty in (ConversionDifficulty.COMPLEX, ConversionDifficulty.EXTREME):
                result.warnings.append(
                    f"Complex patterns detected: {', '.join(obj.detected_patterns)}. "
                    "Manual review recommended."
                )
        except Exception as exc:
            result.errors.append(str(exc))
            result.success = False
            return result

        if self._schema_mapper is not None and result.converted_sql:
            result.converted_sql = self._schema_mapper.apply(result.converted_sql)
        return result

    def _auto_convert_sproc(self, sql: str) -> ConversionResult:
        """Backward-compatible alias for the unified sproc pipeline."""
        return self._convert_sproc_unified(sql)

    @staticmethod
    def _ensure_sproc_ddl(
        body: str,
        *,
        schema: str,
        name: str,
        object_type: ObjectType,
    ) -> str:
        stripped = body.strip()
        if stripped.upper().startswith("CREATE"):
            return stripped
        keyword = "PROCEDURE" if object_type == ObjectType.PROCEDURE else "FUNCTION"
        return (
            f"CREATE {keyword} {schema}.{name}\n"
            f"AS\nBEGIN\n{stripped}\nEND"
        )

    def convert_procedure(
        self,
        schema: str,
        name: str,
        parameters: list[ParameterInfo],
        body: str,
    ) -> ConversionResult:
        """Convert a T-SQL stored procedure to PL/pgSQL."""
        sql = self._ensure_sproc_ddl(
            body,
            schema=schema,
            name=name,
            object_type=ObjectType.PROCEDURE,
        )
        return self._convert_sproc_unified(sql, object_type_hint=ObjectType.PROCEDURE)

    def convert_function(
        self,
        schema: str,
        name: str,
        parameters: list[ParameterInfo],
        body: str,
        return_type: str = "INTEGER",
        returns_table: bool = False,
    ) -> ConversionResult:
        """Convert a T-SQL function to PL/pgSQL function."""
        sql = self._ensure_sproc_ddl(
            body,
            schema=schema,
            name=name,
            object_type=ObjectType.FUNCTION,
        )
        return self._convert_sproc_unified(sql, object_type_hint=ObjectType.FUNCTION)

    def convert_trigger(
        self,
        schema: str,
        name: str,
        table_name: str,
        timing: str,
        event: str,
        body: str,
    ) -> ConversionResult:
        """Convert a T-SQL trigger to PL/pgSQL trigger."""
        obj = ProceduralObject(
            object_type=ObjectType.TRIGGER,
            schema_name=schema,
            object_name=name,
            body_sql=body,
            difficulty=TSqlPatternMatcher.detect_difficulty(body),
            detected_patterns=TSqlPatternMatcher.detect_patterns(body),
        )
        result = self._convert(obj)

        if result.success:
            trigger_ddl = (
                f"CREATE OR REPLACE FUNCTION {schema}.{name}_func() RETURNS TRIGGER AS $$\n"
                f"BEGIN\n"
                f"{self._indent_body(result.converted_sql)}\n"
                f"RETURN NEW;\n"
                f"END;\n"
                f"$$ LANGUAGE plpgsql;\n\n"
                f"CREATE TRIGGER {name} {timing} {event} ON {schema}.{table_name}\n"
                f"    FOR EACH ROW EXECUTE FUNCTION {schema}.{name}_func();"
            )
            result.converted_sql = trigger_ddl

        return result

    @staticmethod
    def _preprocess_tsql(sql: str) -> tuple[str, list[str]]:
        """Pre-process T-SQL before transpilation.

        Returns (processed_sql, warnings) where warnings contains annotations
        about constructs that require manual review.

        Converts:
        - @@IDENTITY, @@ROWCOUNT, @@FETCH_STATUS, @@ERROR
        - SET NOCOUNT ON / SET XACT_ABORT ON
        - WITH (NOLOCK), MERGE, FOR XML PATH, MAXRECURSION, ## global temp tables
          (via TsqlPatternConverter)
        """
        import re as _re

        from domains.transpilation.tsql_pattern_converter import TsqlPatternConverter

        result = sql

        # @@IDENTITY
        result = _re.sub(r'@@IDENTITY(?![a-zA-Z_])', 'LASTVAL()', result, flags=_re.IGNORECASE)

        # @@ROWCOUNT -> comment + placeholder
        result = _re.sub(
            r'@@ROWCOUNT(?![a-zA-Z_])',
            '0 /* @@ROWCOUNT - manual: use GET DIAGNOSTICS in PL/pgSQL; no equivalent in SELECT */',
            result,
            flags=_re.IGNORECASE,
        )

        # @@FETCH_STATUS — do not rewrite here. Replacing @@FETCH_STATUS → FOUND turns
        # `WHILE @@FETCH_STATUS = 0` into invalid `WHILE FOUND = 0` and breaks cursor
        # loop conversion in TsqlBodyConverter.

        # @@ERROR
        result = _re.sub(r'@@ERROR(?![a-zA-Z_])', 'SQLSTATE', result, flags=_re.IGNORECASE)

        # SET NOCOUNT ON -> remove (not needed in PG)
        result = _re.sub(r'SET\s+NOCOUNT\s+(ON|OFF)\s*;?', '', result, flags=_re.IGNORECASE)

        # SET XACT_ABORT ON -> translate to PG equivalent
        result = _re.sub(
            r'SET\s+XACT_ABORT\s+ON\s*;?',
            '-- SET XACT_ABORT ON converted: use EXCEPTION blocks in PL/pgSQL',
            result,
            flags=_re.IGNORECASE,
        )

        # Pre-transpilation: remove NOLOCK hints and rename ## global temp tables
        # so SQLGlot can parse the SQL correctly.
        # FOR XML / MERGE / MAXRECURSION are handled POST-transpilation.
        pattern_result = TsqlPatternConverter().preprocess(result)
        result = pattern_result.sql
        warnings = list(pattern_result.warnings)

        return result, warnings

    @staticmethod
    def _strip_ddl_wrapper(sql: str, object_type: ObjectType) -> str:
        """Strip the outer DDL wrapper (CREATE PROCEDURE/FUNCTION/TRIGGER ... AS)
        and return only the inner procedural body.

        Handles: CREATE PROCEDURE/FUNCTION/TRIGGER ... AS BEGIN ... END
        """
        import re
        upper = sql.upper().strip()
        body = sql

        # Strategy: find the outermost BEGIN that starts the main body.
        # The AS keyword that precedes this BEGIN is the DDL's AS.
        # We search backwards from the first BEGIN to find the right AS.
        begin_idx = upper.find("BEGIN")
        if begin_idx < 0:
            return sql

        # Find the last AS before this BEGIN (skipping quoted identifiers)
        before_begin = upper[:begin_idx]
        # Look for AS preceded by whitespace/), not part of a word
        as_matches = list(re.finditer(r'(?<![a-zA-Z0-9_])AS\s', before_begin))
        if not as_matches:
            # For triggers: also try WITH ENCRYPTION AS, WITH EXECUTE AS, etc.
            as_matches = list(re.finditer(r'(?<![a-zA-Z0-9_])AS\s', before_begin))
        if as_matches:
            last_as = as_matches[-1]
            as_end = last_as.end()  # position after 'AS' + space
            # Extract everything after this AS
            body = sql[as_end:].strip()
            # Strip leading BEGIN if present
            if body.upper().strip().startswith("BEGIN"):
                body = body[body.upper().find("BEGIN") + 5:].strip()
            # Find matching END - count BEGIN/END nesting
            body_upper = body.upper()
            depth = 0
            end_idx = -1
            for m in re.finditer(r'\b(BEGIN|END)\b', body_upper):
                if m.group() == 'BEGIN':
                    depth += 1
                elif m.group() == 'END':
                    depth -= 1
                    if depth < 0:
                        end_idx = m.start()
                        break
            if end_idx >= 0:
                body = body[:end_idx].strip()
            return body
        return sql

    @staticmethod
    def _is_incomplete_body(body: str) -> tuple[bool, str]:
        bare = body.strip()
        if not bare:
            return False, ""

        bare_upper = bare.upper().rstrip(";")
        INCOMPLETE_KEYWORDS = {"SELECT", "FROM", "WHERE", "INSERT", "UPDATE", "DELETE",
                               "CREATE", "ALTER", "DROP", "BEGIN", "END", "DECLARE",
                               "SET", "EXEC", "EXECUTE", "TRUNCATE", "MERGE", "WITH",
                               "BEGIN TRY", "BEGIN CATCH", "IF", "ELSE", "WHILE",
                               "RETURN", "PRINT", "RAISEERROR", "THROW", "COMMIT",
                               "ROLLBACK", "SAVE TRANSACTION", "USE", "GO", "GRANT", "REVOKE"}
        words = bare_upper.split()
        if len(words) <= 2:
            all_incomplete = all(w in INCOMPLETE_KEYWORDS for w in words)
            if all_incomplete:
                return True, f"Incomplete SQL: '{body.strip()}' does not form a complete SQL statement"
        return False, ""

    def _convert(self, obj: ProceduralObject) -> ConversionResult:
        """Internal conversion logic."""
        from domains.transpilation.converters.pivot_converter import PivotConverter

        result = ConversionResult(source=obj)

        # ----------------------------------------------------------------
        # Pre-SQLGlot: specialized PIVOT converter.
        # SQLGlot cannot parse EXEC sp_executesql or T-SQL PIVOT syntax.
        # When both are detected, hand off to PivotConverter which produces
        # a complete, correct PostgreSQL procedure using conditional aggregation.
        # ----------------------------------------------------------------
        if PivotConverter.can_handle(obj.body_sql):
            pivot_result = PivotConverter.convert(obj.body_sql)
            if pivot_result.success:
                result.converted_sql = pivot_result.converted_sql
                result.warnings.extend(pivot_result.warnings)
                result.success = True
                return result
            # Non-fatal: fall through to SQLGlot path with the warnings recorded
            result.warnings.extend(pivot_result.warnings)

        try:
            from domains.transpilation.sql_expression_converter import TsqlExpressionConverter
            from domains.transpilation.tsql_pattern_converter import TsqlPatternConverter

            # Strip outer DDL wrapper before transpilation
            inner_body = self._strip_ddl_wrapper(obj.body_sql, obj.object_type)
            inner_body, unblock_warnings, unblock_steps = self._unblock_source(inner_body)
            result.warnings.extend(unblock_warnings)
            self._record_unblockers(result, unblock_steps)

            incomplete, msg = self._is_incomplete_body(inner_body)
            if incomplete:
                result.errors.append(msg)
                result.success = False
                return result

            # Pre-process: convert common T-SQL expressions before SQLGlot parsing
            preprocessed, preproc_warnings = self._preprocess_tsql(inner_body)
            result.warnings.extend(preproc_warnings)

            converted, tx_warnings, parse_errors = self._transpile_body(preprocessed)
            result.warnings.extend(tx_warnings)
            if parse_errors:
                for err in parse_errors[:3]:
                    result.warnings.append(f"T-SQL parse note: {err}")

            body_already_wrapped = False
            if self._needs_body_transform_fallback(preprocessed, converted, inner_body):
                converted = self._body_transform_fallback(inner_body, obj)
                result.body_transform_fallback = True
                result.warnings.append(
                    "Used PL/pgSQL body-transform fallback (SQLGlot cannot reliably transpile this T-SQL construct)"
                )
                body_already_wrapped = True
            elif not converted.strip():
                converted = self._body_transform_fallback(inner_body, obj)
                result.body_transform_fallback = True
                result.warnings.append(
                    "Used PL/pgSQL body-transform fallback (SQLGlot transpile unavailable)"
                )
                body_already_wrapped = converted.strip().upper().startswith("CREATE")

            ast_fixes = 0
            if not body_already_wrapped:
                # Post-transpilation pattern conversions (FOR XML, MERGE, MAXRECURSION)
                post_result = TsqlPatternConverter().postprocess(converted)
                converted = post_result.sql
                result.warnings.extend(post_result.warnings)

                converted = TsqlExpressionConverter.convert_expression(converted)

                if self._enhanced_converter:
                    ast_result = ASTEnhancer.enhance(converted, apply_phase1=True, apply_phase2=True)
                    converted = ast_result.sql
                    result.warnings.extend(ast_result.warnings)
                    ast_fixes = ast_result.fixes_applied

                converted = self._apply_plpgsql_wrapper(obj, converted)

                if self._enhanced_converter:
                    enhancement_result = self._enhanced_converter.apply_phase3_and_4(converted)
                    converted = enhancement_result.sql
                    result.warnings.extend(enhancement_result.warnings)
                    if ast_fixes + enhancement_result.fixes_applied > 0:
                        result.warnings.append(
                            f"Applied {ast_fixes + enhancement_result.fixes_applied} total enhancement fixes"
                        )
            elif self._enhanced_converter:
                # Wrapped PL/pgSQL from TsqlToPlpgsqlConverter — skip AST/Phase 4 (they corrupt DDL).
                pass

            if body_already_wrapped:
                post_result = TsqlPatternConverter().postprocess(converted)
                converted = post_result.sql
                result.warnings.extend(post_result.warnings)

            # Add warnings for complex patterns
            if obj.difficulty in (ConversionDifficulty.COMPLEX, ConversionDifficulty.EXTREME):
                result.warnings.append(
                    f"Object contains complex patterns: {', '.join(obj.detected_patterns)}"
                )
                result.warnings.append("Manual review recommended after conversion")

            if self._schema_mapper is not None:
                converted = self._schema_mapper.apply(converted)

            result.converted_sql = converted
            result.success = True

        except Exception as e:
            result.errors.append(str(e))
            result.success = False

        return result

    def _apply_plpgsql_wrapper(self, obj: ProceduralObject, body: str) -> str:
        """Wrap the converted body in a PL/pgSQL function/procedure declaration."""
        param_list = self._format_parameters(obj.parameters)

        if obj.object_type == ObjectType.PROCEDURE:
            return (
                f"CREATE OR REPLACE PROCEDURE {obj.schema_name}.{obj.object_name}(\n"
                f"    {param_list}\n"
                f")\n"
                f"LANGUAGE plpgsql\n"
                f"AS $function$\n"
                f"DECLARE\n"
                f"BEGIN\n"
                f"{self._indent_body(body)}\n"
                f"END;\n"
                f"$function$;"
            )
        elif obj.object_type == ObjectType.FUNCTION:
            returns = "TABLE(...)" if obj.returns_table else (obj.return_type or "INTEGER")
            return (
                f"CREATE OR REPLACE FUNCTION {obj.schema_name}.{obj.object_name}(\n"
                f"    {param_list}\n"
                f")\n"
                f"RETURNS {returns}\n"
                f"LANGUAGE plpgsql\n"
                f"AS $function$\n"
                f"DECLARE\n"
                f"BEGIN\n"
                f"{self._indent_body(body)}\n"
                f"END;\n"
                f"$function$;"
            )

        if obj.object_type == ObjectType.RAW:
            return body

        return body

    @staticmethod
    def _format_parameters(params: list[ParameterInfo]) -> str:
        """Format parameters for PL/pgSQL."""
        parts = []
        for p in params:
            pg_type = p.data_type
            if p.is_output:
                parts.append(f"INOUT {p.name} {pg_type}")
            else:
                parts.append(f"{p.name} {pg_type}")
                if p.default_value:
                    parts[-1] += f" DEFAULT {p.default_value}"
        return ",\n    ".join(parts) if parts else ""

    @staticmethod
    def _indent_body(body: str, indent: str = "    ") -> str:
        """Indent the body for embedding in a function."""
        return "\n".join(f"{indent}{line}" for line in body.split("\n"))


class DynamicSqlType(StrEnum):
    STATIC_TEMPLATE = "static_template"
    PARAMETERIZED = "parameterized"
    RUNTIME_GENERATED = "runtime_generated"
    NONE = "none"


@dataclass
class DynamicSqlOccurrence:
    """A single dynamic SQL occurrence in the code."""

    line: str = ""
    sql_type: DynamicSqlType = DynamicSqlType.NONE
    risk_level: str = "low"
    suggestion: str = ""


class DynamicSqlAnalyzer:
    """Analyzes T-SQL for dynamic SQL usage and categorizes complexity."""

    def analyze(self, sql: str) -> list[DynamicSqlOccurrence]:
        """Analyze SQL for dynamic SQL occurrences."""
        occurrences: list[DynamicSqlOccurrence] = []
        sql.upper()

        lines = sql.split("\n")
        for _i, line in enumerate(lines):
            stripped = line.strip().upper()

            if "SP_EXECUTESQL" in stripped:
                occ = DynamicSqlOccurrence(
                    line=line.strip(),
                    sql_type=DynamicSqlType.PARAMETERIZED,
                    risk_level="medium",
                    suggestion="sp_executesql can be converted to PL/pgSQL EXECUTE ... USING. "
                               "Extract the SQL template and parameters.",
                )
                occurrences.append(occ)

            elif "EXEC" in stripped and ("@" in stripped or "+" in stripped):
                occ = DynamicSqlOccurrence(
                    line=line.strip(),
                    sql_type=DynamicSqlType.RUNTIME_GENERATED,
                    risk_level="high",
                    suggestion="Runtime-generated dynamic SQL requires manual rewrite. "
                               "Consider using PL/pgSQL EXECUTE with USING clause.",
                )
                occurrences.append(occ)

            elif "EXEC" in stripped:
                occ = DynamicSqlOccurrence(
                    line=line.strip(),
                    sql_type=DynamicSqlType.STATIC_TEMPLATE,
                    risk_level="low",
                    suggestion="EXEC with static SQL can use CALL or direct function call in PL/pgSQL.",
                )
                occurrences.append(occ)

        return occurrences

    def generate_remediation(self, occurrences: list) -> list[str]:
        """Generate remediation suggestions for dynamic SQL occurrences."""
        suggestions = []
        for occ in occurrences:
            if occ.risk_level == "high":
                suggestions.append(f"[HIGH] {occ.line[:60]}... -> {occ.suggestion}")
            elif occ.risk_level == "medium":
                suggestions.append(f"[MEDIUM] {occ.line[:60]}... -> {occ.suggestion}")
            else:
                suggestions.append(f"[LOW] {occ.line[:60]}... -> {occ.suggestion}")
        return suggestions


# =============================================================================
# Phase 4.4: Control Flow Graph (CFG) Builder for Stored Procedures
# =============================================================================

@dataclass
class CFGNode:
    """A single node in the control flow graph."""

    node_id: int
    label: str = ""
    statement_type: str = "unknown"  # ASSIGNMENT, IF, LOOP, CALL, EXEC, RETURN, etc.
    sql_fragment: str = ""
    children: list["CFGNode"] = field(default_factory=list)
    parent: Optional["CFGNode"] = None


class ControlFlowGraph:
    """Control Flow Graph representing execution paths in a procedure."""

    def __init__(self) -> None:
        self.nodes: list[CFGNode] = []
        self._node_counter: int = 0
        self._entry_node: CFGNode | None = None

    def add_node(
        self,
        label: str,
        statement_type: str = "unknown",
        sql_fragment: str = "",
    ) -> CFGNode:
        self._node_counter += 1
        node = CFGNode(
            node_id=self._node_counter,
            label=label,
            statement_type=statement_type,
            sql_fragment=sql_fragment,
        )
        self.nodes.append(node)
        if self._entry_node is None:
            self._entry_node = node
        return node

    def add_edge(self, parent: CFGNode, child: CFGNode) -> None:
        parent.children.append(child)
        child.parent = parent

    def get_entry(self) -> CFGNode | None:
        return self._entry_node

    def find_node(self, predicate) -> CFGNode | None:
        """Find first node matching predicate."""
        for n in self.nodes:
            if predicate(n):
                return n
        return None

    def find_all(self, predicate) -> list[CFGNode]:
        return [n for n in self.nodes if predicate(n)]


class ControlFlowGraphBuilder:
    """Builds a Control Flow Graph from T-SQL procedure body.

    Analyzes: IF/ELSE, WHILE, GOTO, TRY/CATCH, EXEC calls, CURSOR loops.
    """

    def build(self, sql: str) -> ControlFlowGraph:
        """Build a CFG from a T-SQL procedure body."""
        cfg = ControlFlowGraph()
        lines = sql.split("\n")
        upper_lines = [l.upper() for l in lines]

        entry = cfg.add_node("PROCEDURE ENTRY", "entry", "")
        current_parent = entry
        block_stack: list[list[CFGNode]] = []
        depth = 0

        for i, (raw_line, upper_line) in enumerate(zip(lines, upper_lines, strict=False)):
            stripped = upper_line.strip()
            if not stripped:
                continue

            if stripped.startswith("IF ") or stripped.startswith("IF("):
                node = cfg.add_node(f"IF at line {i+1}", "if", raw_line.strip())
                cfg.add_edge(current_parent, node)
                block_stack.append([node])
                current_parent = node
                depth += 1

            elif stripped.startswith("ELSE") and not stripped.startswith("ELSE "):
                pass  # part of IF
            elif "BEGIN" in stripped and depth > 0:
                pass  # block start
            elif stripped.rstrip(";") == "END" and block_stack:
                block_stack.pop()
                depth -= 1
                current_parent = block_stack[-1][-1] if block_stack else entry

            elif stripped.startswith("WHILE "):
                node = cfg.add_node(f"WHILE loop at line {i+1}", "loop", raw_line.strip())
                cfg.add_edge(current_parent, node)
                block_stack.append([node])
                current_parent = node
                depth += 1

            elif "GOTO" in stripped and not stripped.startswith("--"):
                parts = stripped.split()
                idx = parts.index("GOTO") if "GOTO" in parts else -1
                if idx >= 0 and idx + 1 < len(parts):
                    label = parts[idx + 1].rstrip(";")
                    cfg.add_node(f"GOTO {label} at line {i+1}", "goto", raw_line.strip())

            elif "RETURN" in stripped:
                node = cfg.add_node(f"RETURN at line {i+1}", "return", raw_line.strip())
                cfg.add_edge(current_parent, node)

            elif "EXEC " in stripped or "EXEC(" in stripped:
                node = cfg.add_node(f"EXEC at line {i+1}", "call", raw_line.strip())
                cfg.add_edge(current_parent, node)

            elif "FETCH" in stripped or "CURSOR" in stripped:
                node = cfg.add_node(f"CURSOR/FETCH at line {i+1}", "cursor", raw_line.strip())
                cfg.add_edge(current_parent, node)

            elif "CATCH" in stripped:
                node = cfg.add_node(f"CATCH block at line {i+1}", "catch", raw_line.strip())
                cfg.add_edge(current_parent, node)

            elif "=" in stripped and not stripped.startswith("--") and not stripped.startswith("IF"):
                node = cfg.add_node(f"ASSIGNMENT at line {i+1}", "assignment", raw_line.strip())
                cfg.add_edge(current_parent, node)

            else:
                node = cfg.add_node(f"STATEMENT at line {i+1}", "statement", raw_line.strip())
                cfg.add_edge(current_parent, node)

        return cfg

    @staticmethod
    def to_mermaid(cfg: ControlFlowGraph) -> str:
        """Export CFG as Mermaid diagram."""
        lines = ["graph TD;"]
        for node in cfg.nodes:
            label = node.label.replace('"', "'")
            lines.append(f'    N{node.node_id}["{label}"];')
            for child in node.children:
                lines.append(f"    N{node.node_id} --> N{child.node_id};")
        return "\n".join(lines)


# =============================================================================
# Phase 4.5: Variable Scope Resolver
# =============================================================================

@dataclass
class Variable:
    """A variable declaration found in a procedure."""

    name: str
    data_type: str
    default_value: str | None = None
    is_cursor: bool = False
    is_table_variable: bool = False
    declared_line: int = 0
    last_assigned_line: int = 0
    used_in_lines: list[int] = field(default_factory=list)
    scope_depth: int = 0


@dataclass
class ScopeBlock:
    """A scope block (BEGIN...END) in the procedure."""

    block_id: int
    parent_block_id: int | None = None
    variables: list[Variable] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0


class VariableScopeResolver:
    """Resolves variable scopes and declarations in T-SQL procedures.

    Handles:
    - @variables with DECLARE statements
    - Table variables (@table)
    - Cursor variables
    - Scope-based resolution (BEGIN...END blocks)
    - Variable usage tracking
    """

    def __init__(self) -> None:
        self._scope_stack: list[ScopeBlock] = []
        self._current_block_id: int = 0
        self._all_variables: dict[str, Variable] = {}

    def resolve(self, sql: str) -> list[ScopeBlock]:
        """Parse SQL and return scope blocks with variable declarations."""
        self._scope_stack = []
        self._current_block_id = 0
        self._all_variables = {}

        root = ScopeBlock(block_id=0, start_line=0)
        self._scope_stack.append(root)

        lines = sql.split("\n")

        for i, line in enumerate(lines):
            stripped = line.strip()
            upper = stripped.upper()

            if upper.startswith("DECLARE "):
                self._parse_declare(stripped, i + 1)
                self._track_variable_usage(stripped, i + 1)
            elif "BEGIN" in upper and i > 0:
                self._push_scope(i + 1)
            elif upper.rstrip(";") == "END" or upper.rstrip() == "END":
                self._pop_scope(i + 1)
            else:
                self._track_variable_usage(stripped, i + 1)

        current_scope = self._scope_stack[-1] if self._scope_stack else root
        current_scope.end_line = len(lines)

        return self._scope_stack

    def _parse_declare(self, line: str, line_num: int) -> None:
        """Parse a DECLARE statement and extract variable info."""
        rest = line[8:].strip()  # remove "DECLARE "
        # Handle table variable: DECLARE @table TABLE (...)
        if " TABLE " in rest.upper():
            var_name = rest.split()[0]  # @tableName
            self._add_variable(Variable(
                name=var_name,
                data_type="TABLE",
                is_table_variable=True,
                declared_line=line_num,
                scope_depth=len(self._scope_stack),
            ))
        elif " CURSOR" in rest.upper():
            var_name = rest.split()[0]
            self._add_variable(Variable(
                name=var_name,
                data_type="CURSOR",
                is_cursor=True,
                declared_line=line_num,
                scope_depth=len(self._scope_stack),
            ))
        else:
            # DECLARE @var type [= value]
            parts = rest.split()
            if len(parts) >= 2:
                var_name = parts[0]
                data_type = parts[1].rstrip(",;")
                default = None
                if "=" in parts:
                    eq_idx = parts.index("=")
                    default = " ".join(parts[eq_idx + 1:]).rstrip(";")
                self._add_variable(Variable(
                    name=var_name,
                    data_type=data_type,
                    default_value=default,
                    declared_line=line_num,
                    scope_depth=len(self._scope_stack),
                ))

    def _add_variable(self, var: Variable) -> None:
        self._all_variables[var.name.upper()] = var
        if self._scope_stack:
            self._scope_stack[-1].variables.append(var)

    def _push_scope(self, line_num: int) -> None:
        self._current_block_id += 1
        parent_id = self._scope_stack[-1].block_id if self._scope_stack else None
        new_scope = ScopeBlock(
            block_id=self._current_block_id,
            parent_block_id=parent_id,
            start_line=line_num,
        )
        self._scope_stack.append(new_scope)

    def _pop_scope(self, line_num: int) -> None:
        if len(self._scope_stack) > 1:
            popped = self._scope_stack.pop()
            popped.end_line = line_num

    def _track_variable_usage(self, line: str, line_num: int) -> None:
        """Track which variables are used/assigned on a line."""
        import re
        var_refs = re.findall(r'@\w+', line)
        for ref in var_refs:
            key = ref.upper()
            if key in self._all_variables:
                self._all_variables[key].used_in_lines.append(line_num)
                if "=" in line.upper() and ref in line:
                    self._all_variables[key].last_assigned_line = line_num

    def get_variable(self, name: str) -> Variable | None:
        return self._all_variables.get(name.upper())

    def get_all_variables(self) -> list[Variable]:
        return list(self._all_variables.values())

    def find_unused_variables(self) -> list[Variable]:
        return [
            v for v in self._all_variables.values()
            if not [l for l in v.used_in_lines if l != v.declared_line]
        ]

    def find_undeclared_variables(self, sql: str) -> list[str]:
        """Find @variables used but never declared."""
        import re
        declared = set(self._all_variables.keys())
        used = set()
        for m in re.finditer(r'@\w+', sql.upper()):
            used.add(m.group())
        return sorted(u for u in used if u not in declared)


# =============================================================================
# Phase 4.10: Table-Valued Parameters (TVP) → JSONB / Temp Table
# =============================================================================

@dataclass
class TvpTypeDefinition:
    """Definition of a user-defined table type (TVP)."""

    type_name: str
    schema: str = "dbo"
    columns: list[dict] = field(default_factory=list)  # [{"name": "...", "type": "..."}]


@dataclass
class TvpUsage:
    """A usage of a TVP in a procedure."""

    variable_name: str
    type_name: str
    columns: list[dict] = field(default_factory=list)
    used_in_statements: list[str] = field(default_factory=list)


class TvpConverter:
    """Converts T-SQL Table-Valued Parameters to PostgreSQL alternatives.

    Strategy:
    - Method A: JSONB parameter + jsonb_to_recordset()
    - Method B: Temp table + procedure-local processing
    - Method C: PostgreSQL typed array (for simple types only)
    """

    def __init__(self) -> None:
        self._type_definitions: dict[str, TvpTypeDefinition] = {}
        self._usages: list[TvpUsage] = []

    def register_type(self, type_def: TvpTypeDefinition) -> None:
        self._type_definitions[type_def.type_name.upper()] = type_def

    def analyze(self, sql: str) -> list[TvpUsage]:
        """Analyze SQL for TVP usage patterns."""
        import re
        usages: list[TvpUsage] = []

        # Pattern: DECLARE @var [AS] type_name  where type_name contains "TABLE"
        # or ends with common TVP suffixes
        for match in re.finditer(
            r'DECLARE\s+(@\w+)\s+(?:AS\s+)?([\w.]+)',
            sql, re.IGNORECASE,
        ):
            var_name = match.group(1)
            type_name = match.group(2)
            upper_type = type_name.upper()
            is_tvp = (
                "TABLE" in upper_type
                or upper_type.endswith("_TT")
                or upper_type.endswith("TVP")
                or upper_type.endswith("TABLE_TYPE")
                or upper_type.endswith("LIST")
            )
            if is_tvp:
                type_def = self._type_definitions.get(upper_type)
                usages.append(TvpUsage(
                    variable_name=var_name,
                    type_name=type_name,
                    columns=type_def.columns if type_def else [],
                    used_in_statements=self._find_tvp_statements(sql, var_name),
                ))

        self._usages = usages
        return usages

    def convert_to_jsonb(self, usage: TvpUsage, param_name: str = "p_data") -> str:
        """Generate PL/pgSQL code using JSONB parameter."""
        cols = usage.columns
        col_list = ", ".join(c["name"] for c in cols)
        cast_list = ", ".join(f"{c['name']}::{self._map_type(c['type'])}" for c in cols)

        return (
            f"-- Converted from TVP {usage.type_name} (JSONB method)\n"
            f"-- Call with: SELECT * FROM jsonb_to_recordset({param_name}) "
            f"AS x({cast_list})\n"
            f"DECLARE\n"
            f"    rec RECORD;\n"
            f"BEGIN\n"
            f"    FOR rec IN\n"
            f"        SELECT {col_list}\n"
            f"        FROM jsonb_to_recordset({param_name}) AS x({cast_list})\n"
            f"    LOOP\n"
            f"        -- process each record\n"
            f"        -- original TVP: {usage.variable_name}\n"
            f"    END LOOP;\n"
            f"END;"
        )

    def convert_to_temp_table(self, usage: TvpUsage, temp_table_name: str = "input_data") -> str:
        """Generate PL/pgSQL code using a temp table."""
        cols = usage.columns
        col_defs = ", ".join(f"{c['name']} {self._map_type(c['type'])}" for c in cols)

        return (
            f"-- Converted from TVP {usage.type_name} (temp table method)\n"
            f"CREATE TEMPORARY TABLE {temp_table_name} (\n"
            f"    {col_defs}\n"
            f") ON COMMIT DROP;\n\n"
            f"-- Insert data into temp table using jsonb_to_recordset\n"
            f"INSERT INTO {temp_table_name}\n"
            f"SELECT * FROM jsonb_to_recordset($1::jsonb) AS x({col_defs});\n\n"
            f"-- Use {temp_table_name} as the TVP replacement\n"
            f"-- WHERE {usage.variable_name} -> {temp_table_name}"
        )

    @staticmethod
    def _map_type(tsql_type: str) -> str:
        """Map T-SQL types to PostgreSQL types for TVP columns."""
        mapping = {
            "INT": "INTEGER", "INTEGER": "INTEGER", "BIGINT": "BIGINT",
            "SMALLINT": "SMALLINT", "TINYINT": "SMALLINT",
            "VARCHAR": "TEXT", "NVARCHAR": "TEXT", "CHAR": "TEXT", "NCHAR": "TEXT",
            "TEXT": "TEXT", "NTEXT": "TEXT",
            "DECIMAL": "NUMERIC", "NUMERIC": "NUMERIC", "MONEY": "NUMERIC",
            "FLOAT": "DOUBLE PRECISION", "REAL": "REAL",
            "DATETIME": "TIMESTAMP", "DATE": "DATE", "TIME": "TIME",
            "UNIQUEIDENTIFIER": "UUID", "BIT": "BOOLEAN",
            "BINARY": "BYTEA", "VARBINARY": "BYTEA", "IMAGE": "BYTEA",
        }
        base = tsql_type.upper().split("(")[0].split()[0].rstrip(")")
        return mapping.get(base, "TEXT")

    def _find_tvp_statements(self, sql: str, var_name: str) -> list[str]:
        """Find statements that use the TVP variable."""
        statements = []
        for line in sql.split("\n"):
            if var_name.upper() in line.upper():
                statements.append(line.strip())
        return statements
