"""
Module: antlr_adapter.py
Purpose: ANTLR4-based T-SQL fallback parser adapter
Author: Migration Platform Team
Created: 2026-05-22
Domain: Parsing
Dependencies: antlr4 (optional — graceful fallback to SQLGlot)
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import logging
from pathlib import Path
from typing import Any

from domains.parsing.parser_port import ParseResult, SqlParser
from domains.transpilation.ir_models import IrNode, IrNodeType

logger = logging.getLogger(__name__)

# T-SQL grammar files expected in tools/antlr/grammars/
ANTLR_GRAMMAR_DIR = Path(__file__).parent.parent.parent / "tools" / "antlr" / "grammars"
TSQL_GRAMMAR = "TSqlLexer.g4 TSqlParser.g4"

# Mapping of ANTLR token names to IrNodeType values
ANTLR_TOKEN_TO_IR_TYPE: dict[str, IrNodeType] = {
    "SELECT": IrNodeType.SELECT,
    "INSERT": IrNodeType.INSERT,
    "UPDATE": IrNodeType.UPDATE,
    "DELETE": IrNodeType.DELETE,
    "MERGE": IrNodeType.MERGE,
    "CREATE_TABLE": IrNodeType.CREATE_TABLE,
    "CREATE_VIEW": IrNodeType.CREATE_VIEW,
    "CREATE_INDEX": IrNodeType.CREATE_INDEX,
    "CREATE_PROCEDURE": IrNodeType.CREATE_PROCEDURE,
    "CREATE_FUNCTION": IrNodeType.CREATE_FUNCTION,
    "CREATE_TRIGGER": IrNodeType.CREATE_TRIGGER,
    "ALTER_TABLE": IrNodeType.ALTER_TABLE,
    "DROP": IrNodeType.DROP,
    "IF": IrNodeType.IF,
    "WHILE": IrNodeType.WHILE,
    "RETURN": IrNodeType.RETURN,
    "DECLARE": IrNodeType.DECLARE,
    "SET": IrNodeType.SET,
    "CURSOR": IrNodeType.CURSOR,
    "EXEC": IrNodeType.EXEC,
    "CALL": IrNodeType.CALL,
    "TRY": IrNodeType.TRY,
    "CATCH": IrNodeType.CATCH,
    "BLOCK": IrNodeType.BLOCK,
    "WHERE": IrNodeType.WHERE,
    "JOIN": IrNodeType.JOIN,
    "ORDER_BY": IrNodeType.ORDER_BY,
    "GROUP_BY": IrNodeType.GROUP_BY,
    "HAVING": IrNodeType.HAVING,
    "TOP": IrNodeType.TOP,
    "LIMIT": IrNodeType.LIMIT,
    "WINDOW": IrNodeType.WINDOW,
}


class _AntlrErrorListener:
    """Custom error listener that collects ANTLR4 parse errors."""

    def __init__(self):
        self.errors: list[str] = []

    # noqa needed below: ANTLR4 ErrorListener interface uses camelCase
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):  # noqa: N802, N803, ARG002
        self.errors.append(f"ANTLR4 syntax error at line {line}:{column}: {msg}")

    def reportAmbiguity(self, recognizer, dfa, startIndex, stopIndex, exact, ambigAlts, configs):  # noqa: N802, N803, ARG002
        pass

    def reportAttemptingFullContext(  # noqa: N802, N803, ARG002
        self, recognizer, dfa, startIndex, stopIndex, conflictingAlts, configs,  # noqa: N803
    ):
        pass

    def reportContextSensitivity(self, recognizer, dfa, startIndex, stopIndex, prediction, configs):  # noqa: N802, N803, ARG002
        pass


class AntlrParser(SqlParser):
    """ANTLR4-based T-SQL parser used as a fallback when SQLGlot cannot parse.

    Uses the ANTLR4 T-SQL grammar from the antlr/grammars directory.
    If ANTLR4 is not available, falls back to error reporting.

    This adapter wraps the ANTLR4-generated Python parser classes.
    """

    READ_DIALECT = "tsql"

    def __init__(self, grammar_dir: Path | None = None):
        self._grammar_dir = grammar_dir or ANTLR_GRAMMAR_DIR
        self._parser_available = self._check_parser_available()
        self._antlr4_importable = self._check_antlr4_runtime()

    def _check_parser_available(self) -> bool:
        """Check if ANTLR4-generated parser is available."""
        grammar_dir = self._grammar_dir
        parser_files = list(grammar_dir.glob("*Parser*.py")) if grammar_dir.exists() else []
        lexer_files = list(grammar_dir.glob("*Lexer*.py")) if grammar_dir.exists() else []
        return len(parser_files) > 0 and len(lexer_files) > 0

    @staticmethod
    def _check_antlr4_runtime() -> bool:
        """Check if antlr4 Python runtime package is importable."""
        try:
            import antlr4  # noqa: F401
            return True
        except ImportError:
            return False

    # _generate_parser() was removed (L-19).
    #
    # Runtime grammar compilation via subprocess (java antlr4.jar) is not supported.
    # To enable the ANTLR4 fallback parser:
    #   1. Download the T-SQL grammar from github.com/antlr/grammars-v4/tree/master/sql/tsql
    #   2. Run: java -jar antlr4.jar -Dlanguage=Python3 TSqlLexer.g4 TSqlParser.g4
    #   3. Copy the generated *Lexer.py / *Parser.py into tools/antlr/grammars/
    #   4. Commit the generated files — no runtime compilation needed.
    # Until then, the adapter returns a graceful "not available" result and
    # SqlglotParser handles all parsing.

    def parse(self, sql: str) -> ParseResult:
        """Parse T-SQL using ANTLR4-generated parser."""
        if not self._parser_available or not self._antlr4_importable:
            return ParseResult(
                success=False,
                errors=["ANTLR4 parser not available. Install ANTLR4 tools and generate parser."],
                dialect=self.READ_DIALECT,
            )

        try:
            return self._parse_with_antlr(sql)
        except ImportError as e:
            return ParseResult(
                success=False,
                errors=[f"ANTLR4 runtime import error: {e}"],
                dialect=self.READ_DIALECT,
            )
        except Exception as e:
            return ParseResult(
                success=False,
                errors=[f"ANTLR4 parse error: {e}"],
                dialect=self.READ_DIALECT,
            )

    def parse_multiple(self, sql: str) -> list[ParseResult]:
        """Parse multiple T-SQL statements with ANTLR4."""
        if not self._parser_available or not self._antlr4_importable:
            return [
                ParseResult(
                    success=False,
                    errors=["ANTLR4 parser not available"],
                    dialect=self.READ_DIALECT,
                )
            ]

        results = []
        for statement in self._split_batch(sql):
            results.append(self.parse(statement))
        return results

    def transpile(self, sql: str) -> str:
        """Transpile T-SQL to PostgreSQL SQL.

        Falls back to SQLGlot for transpilation since ANTLR4 only provides parsing.
        """
        try:
            import sqlglot  # noqa: F401
            from sqlglot import transpile as sqlglot_transpile

            result = sqlglot_transpile(sql, read="tsql", write="postgres")
            return "\n".join(result)
        except Exception:
            return self._simple_transpile(sql)

    def _simple_transpile(self, sql: str) -> str:
        """Basic regex-based transpilation when SQLGlot is unavailable."""
        result = sql
        replacements = [
            ("TOP (", "LIMIT "),
            ("TOP ", "LIMIT "),
            (" ISNULL(", " COALESCE("),
            (" GETDATE()", " NOW()"),
            (" LEN(", " LENGTH("),
            (" CHARINDEX(", " STRPOS("),
            (" GETUTCDATE()", " NOW() AT TIME ZONE 'UTC'"),
            (" NEWID()", " gen_random_uuid()"),
            (" PRINT ", " RAISE NOTICE "),
            ("@@ROWCOUNT", "ROW_COUNT"),
            ("@@IDENTITY", "LASTVAL()"),
        ]
        import re
        for old, new in replacements:
            result = re.sub(re.escape(old), new, result, flags=re.IGNORECASE)
        return result

    def _parse_with_antlr(self, sql: str) -> ParseResult:
        """Internal ANTLR4 parsing logic using generated parser classes."""
        from antlr4 import CommonTokenStream, InputStream

        # Attempt to import generated parser classes
        try:
            sys.path.insert(0, str(self._grammar_dir))
            from TSqlLexer import TSqlLexer
            from TSqlParser import TSqlParser
        except ImportError as err:
            raise ImportError(f"Cannot import generated ANTLR4 classes: {err}") from err

        error_listener = _AntlrErrorListener()

        input_stream = InputStream(sql)
        lexer = TSqlLexer(input_stream)
        lexer.removeErrorListeners()
        lexer.addErrorListener(error_listener)

        token_stream = CommonTokenStream(lexer)
        parser = TSqlParser(token_stream)
        parser.removeErrorListeners()
        parser.addErrorListener(error_listener)

        tree = parser.tsql_file()

        if error_listener.errors:
            return ParseResult(
                success=False,
                errors=error_listener.errors,
                dialect=self.READ_DIALECT,
            )

        ir_node = self._antlr_to_ir_node(tree, sql)
        return ParseResult(success=True, ast=ir_node, dialect=self.READ_DIALECT)

    def _antlr_to_ir_node(self, tree: Any, sql: str) -> IrNode:
        """Convert an ANTLR parse tree node to an IrNode.

        Walks the ANTLR parse tree and maps known production rules
        to corresponding IrNodeType values.
        """
        if hasattr(tree, "getRuleIndex"):
            rule_name = self._get_rule_name(tree) if hasattr(self, "_get_rule_name") else ""
        else:
            rule_name = ""

        node_type = ANTLR_TOKEN_TO_IR_TYPE.get(rule_name, IrNodeType.STATEMENT_LIST)

        source_location = (
            self._get_source_location(tree)
            if hasattr(tree, "getSourceInterval")
            else None
        )
        ir = IrNode(
            node_type=node_type,
            original_sql=sql,
            source_location=source_location,
        )
        ir.properties["antlr_rule"] = rule_name

        has_children = hasattr(tree, "children") and tree.children
        ir.children = self._get_children(tree, sql) if has_children else []

        return ir

    def _get_rule_name(self, tree: Any) -> str:
        """Extract the ANTLR rule name from the parse tree."""
        try:
            from antlr4 import ParserRuleContext
            if isinstance(tree, ParserRuleContext):
                return type(tree).__name__.replace("Context", "").upper()
        except ImportError:
            pass
        return ""

    def _get_source_location(self, tree: Any) -> str | None:
        """Extract source location from ANTLR tree node."""
        try:
            interval = tree.getSourceInterval()
            return f"token_index:{interval.start}:{interval.stop}"
        except Exception:
            return None

    def _get_children(self, tree: Any, sql: str) -> list[IrNode]:
        """Recursively extract children from ANTLR parse tree."""
        children = []
        for child in tree.children:
            if hasattr(child, "children") and child.children:
                child_sql = self._extract_child_sql(child, sql)
                ir_child = self._antlr_to_ir_node(child, child_sql)
                children.append(ir_child)
        return children

    @staticmethod
    def _extract_child_sql(child: Any, sql: str) -> str:
        """Extract the SQL text for a child node from the original SQL."""
        try:
            from antlr4 import ParserRuleContext
            if isinstance(child, ParserRuleContext):
                start = child.start.start
                stop = child.stop.stop
                return sql[start:stop + 1] if start >= 0 and stop >= 0 else sql
        except (ImportError, AttributeError):
            pass
        return sql

    def _parse_with_sqlglot_fallback(self, sql: str) -> ParseResult:
        """Try ANTLR4 first, fall back to SQLGlot if ANTLR4 fails or is unavailable.

        Returns a ParseResult from whichever parser succeeds.
        """
        antlr_result = self.parse(sql)
        if antlr_result.success:
            antlr_result.details = {"parser": "antlr4"}
            return antlr_result

        try:
            from domains.parsing.sqlglot_adapter import SqlglotParser

            sqlglot_parser = SqlglotParser()
            sg_result = sqlglot_parser.parse(sql)
            if sg_result.success:
                sg_result.details = {"parser": "sqlglot", "antlr_error": antlr_result.errors}
                return sg_result
            return ParseResult(
                success=False,
                errors=[*antlr_result.errors, *sg_result.errors],
                dialect=self.READ_DIALECT,
            )
        except ImportError:
            return antlr_result

    @staticmethod
    def _split_batch(sql: str) -> list[str]:
        """Split T-SQL batch into statements on GO boundaries."""
        statements = []
        current = []
        for line in sql.split("\n"):
            stripped = line.strip().upper()
            if stripped == "GO" or stripped.startswith("GO "):
                if current:
                    statements.append("\n".join(current))
                    current = []
            else:
                current.append(line)
        if current:
            statements.append("\n".join(current))
        return statements

    @property
    def dialect(self) -> str:
        return self.READ_DIALECT


class CompositeParser(SqlParser):
    """Combines SQLGlot (primary) with ANTLR4 (fallback).

    Tries SQLGlot first. If it fails, delegates to ANTLR4.
    If both fail, returns the original SQLGlot error.
    """

    def __init__(
        self,
        primary: SqlParser | None = None,
        fallback: SqlParser | None = None,
    ):
        from domains.parsing.sqlglot_adapter import SqlglotParser
        self._primary = primary or SqlglotParser()
        self._fallback = fallback or AntlrParser()

    def parse(self, sql: str) -> ParseResult:
        result = self._primary.parse(sql)
        if result.success:
            return result

        fallback_result = self._fallback.parse(sql)
        if fallback_result.success:
            fallback_result.details = {"parser": "antlr4", "primary_error": result.errors}
            return fallback_result

        return result  # return primary error

    def parse_multiple(self, sql: str) -> list[ParseResult]:
        primary_results = self._primary.parse_multiple(sql)
        if all(r.success for r in primary_results):
            return primary_results

        fallback_results = self._fallback.parse_multiple(sql)
        if all(r.success for r in fallback_results):
            return fallback_results

        return primary_results  # return primary errors

    @property
    def dialect(self) -> str:
        return self._primary.dialect
