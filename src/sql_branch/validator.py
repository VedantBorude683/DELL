"""Multi-layer SQL validator using sqlglot (with strict AST/tokenizer fallback).

Enforces:
1. Exactly ONE SQL statement (blocks `;` multi-statement injection).
2. Root statement MUST be a SELECT (or WITH ... SELECT).
3. Zero DDL/DML/admin keywords outside string literals.
4. All referenced base tables MUST belong to config.yaml `allowlisted_tables`.
5. Mandatory row cap (`LIMIT <= max_rows`).
"""
from __future__ import annotations

import re
from typing import Sequence

from src.sql_branch.models import SQLValidationError, ValidatedSQL

_FORBIDDEN_KEYWORDS = {
    "DROP",
    "DELETE",
    "UPDATE",
    "INSERT",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "REPLACE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "VACUUM",
    "GRANT",
    "REVOKE",
    "COPY",
    "MERGE",
    "CALL",
    "EXEC",
    "EXECUTE",
    "DO",
    "LOAD",
    "OUTFILE",
    "DUMPFILE",
    "PG_SLEEP",
    "PG_READ_FILE",
    "PG_TERMINATE_BACKEND",
    "DBLINK",
    "LO_IMPORT",
    "LO_EXPORT",
    "SQLITE_MASTER",
    "SQLITE_SCHEMA",
    "INFORMATION_SCHEMA",
    "PG_CATALOG",
    "PG_SHADOW",
    "PG_ROLES",
    "PG_USER",
    "PG_TABLES",
    "PG_STAT_ACTIVITY",
    "SQLITE_TEMP_MASTER",
}


def _strip_comments_and_strings(sql: str) -> tuple[str, str]:
    """Return (sql_without_comments, sql_with_strings_blanked) preserving structure."""
    out_no_comments: list[str] = []
    out_no_strings: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        # Single-line comment --
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            out_no_comments.append(" ")
            out_no_strings.append(" ")
            continue
        # Block comment /* ... */
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            if end == -1:
                raise SQLValidationError("Unterminated SQL block comment.")
            i = end + 2
            out_no_comments.append(" ")
            out_no_strings.append(" ")
            continue
        # Single-quoted string literal
        if ch == "'":
            start = i
            i += 1
            while i < n:
                if sql[i] == "'" and i + 1 < n and sql[i + 1] == "'":
                    i += 2
                    continue
                if sql[i] == "'":
                    i += 1
                    break
                i += 1
            else:
                raise SQLValidationError("Unterminated SQL string literal.")
            out_no_comments.append(sql[start:i])
            out_no_strings.append(" 'STR' ")
            continue
        # Double-quoted identifier
        if ch == '"':
            start = i
            i += 1
            while i < n and sql[i] != '"':
                i += 1
            if i >= n:
                raise SQLValidationError("Unterminated quoted SQL identifier.")
            i += 1
            out_no_comments.append(sql[start:i])
            out_no_strings.append(sql[start:i])
            continue
        out_no_comments.append(ch)
        out_no_strings.append(ch)
        i += 1

    return "".join(out_no_comments).strip(), "".join(out_no_strings).strip()


def _apply_limit_cap(clean_sql: str, blanked_sql: str, max_rows: int) -> tuple[str, int]:
    """Ensure final SELECT has a LIMIT <= max_rows."""
    m = re.search(r"\bLIMIT\s+(-?\d+)\s*$", blanked_sql, flags=re.IGNORECASE)
    if m:
        existing_limit = int(m.group(1))
        if existing_limit <= 0 or existing_limit > max_rows:
            capped_sql = re.sub(
                r"\bLIMIT\s+-?\d+\s*$",
                f"LIMIT {max_rows}",
                clean_sql,
                flags=re.IGNORECASE,
            )
            return capped_sql, max_rows
        return clean_sql, existing_limit
    return f"{clean_sql} LIMIT {max_rows}", max_rows


def _validate_with_sqlglot(
    sql: str, allowlist: set[str], max_rows: int
) -> ValidatedSQL | None:
    try:
        import sqlglot  # type: ignore
        from sqlglot import exp  # type: ignore
    except ImportError:
        return None

    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise SQLValidationError("Empty SQL query.")

    try:
        parsed = sqlglot.parse(stripped, read="postgres")
    except Exception as exc:
        raise SQLValidationError(f"sqlglot parse error: {exc}") from exc

    if len(parsed) != 1 or parsed[0] is None:
        raise SQLValidationError("Only a single SQL SELECT statement is permitted.")

    tree = parsed[0]
    if not isinstance(tree, exp.Select):
        raise SQLValidationError(f"Only SELECT queries are allowed; got {type(tree).__name__}.")

    forbidden_nodes = (
        exp.Drop,
        exp.Update,
        exp.Delete,
        exp.Insert,
        exp.Alter,
        exp.Create,
        exp.Command,
        exp.Merge,
        exp.Union,
    )
    for node in tree.walk():
        if isinstance(node, forbidden_nodes):
            raise SQLValidationError(f"Forbidden SQL operation: {type(node).__name__}.")

    cte_names = {
        cte.alias_or_name.lower()
        for cte in tree.find_all(exp.CTE)
        if cte.alias_or_name
    }

    referenced_tables: list[str] = []
    for tbl in tree.find_all(exp.Table):
        name = (tbl.name or "").strip().lower()
        if not name or name in cte_names:
            continue
        db_prefix = (tbl.db or "").strip().lower()
        if db_prefix and db_prefix != "public":
            raise SQLValidationError(f"Access to schema '{db_prefix}' is forbidden.")
        if name not in allowlist:
            raise SQLValidationError(f"Table '{name}' is not in the allow-listed table set.")
        if name not in referenced_tables:
            referenced_tables.append(name)

    if not referenced_tables:
        raise SQLValidationError("SELECT query must reference at least one allow-listed table.")

    # Enforce row cap in AST
    limit_node = tree.args.get("limit")
    applied_limit = max_rows
    if limit_node is not None and isinstance(limit_node.expression, exp.Literal):
        try:
            req_limit = int(limit_node.expression.this)
            applied_limit = max_rows if req_limit <= 0 else min(req_limit, max_rows)
        except Exception:
            applied_limit = max_rows
    tree.set("limit", exp.Limit(expression=exp.Literal.number(applied_limit)))
    safe_sql = tree.sql(dialect="postgres")
    return ValidatedSQL(
        sql=safe_sql,
        tables=tuple(referenced_tables),
        limit_applied=applied_limit,
        validator_backend="sqlglot",
    )


def validate_select_sql(
    sql: str,
    allowlisted_tables: Sequence[str],
    *,
    max_rows: int = 100,
) -> ValidatedSQL:
    """Validate SQL strictly via sqlglot (or strict AST/tokenizer fallback)."""
    allowlist = {t.lower() for t in allowlisted_tables}

    # Check comments/strings & multi-statement semicolons up front
    clean_sql, blanked_sql = _strip_comments_and_strings(sql)
    clean_sql = clean_sql.rstrip(";").strip()
    blanked_sql = blanked_sql.rstrip(";").strip()

    if not clean_sql:
        raise SQLValidationError("Empty SQL query.")
    if ";" in blanked_sql:
        raise SQLValidationError("Multi-statement SQL is strictly forbidden.")

    # Check forbidden keywords outside string literals
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", blanked_sql)
    upper_tokens = [t.upper() for t in tokens]
    for tok in upper_tokens:
        if tok in _FORBIDDEN_KEYWORDS:
            raise SQLValidationError(f"Forbidden SQL keyword or object detected: {tok}")

    # Prefer sqlglot AST validation when installed
    glot_res = _validate_with_sqlglot(clean_sql, allowlist, max_rows)
    if glot_res is not None:
        return glot_res

    # Strict fallback validator when sqlglot is not installed
    if not upper_tokens or upper_tokens[0] not in ("SELECT", "WITH"):
        raise SQLValidationError("Only SELECT queries (or WITH ... SELECT) are permitted.")
    if upper_tokens[0] == "WITH" and "SELECT" not in upper_tokens:
        raise SQLValidationError("WITH CTE must terminate in a SELECT query.")
    for set_op in ("UNION", "INTERSECT", "EXCEPT"):
        if set_op in upper_tokens:
            raise SQLValidationError(f"Set operation '{set_op}' is forbidden in single-SELECT mode.")

    # Reject SELECT ... INTO
    if re.search(r"\bINTO\b", blanked_sql, flags=re.IGNORECASE):
        raise SQLValidationError("SELECT INTO is forbidden.")

    # Extract CTE aliases so they are not flagged as unknown tables
    cte_names = {
        m.group(1).lower()
        for m in re.finditer(r"(?:WITH|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s*\(", blanked_sql, flags=re.IGNORECASE)
    }

    def _register_table(raw_ident: str, out: list[str]) -> None:
        ident = raw_ident.replace('"', "").strip().lower()
        if not ident:
            return
        if "." in ident:
            schema_name, tbl_name = ident.split(".", 1)
            if schema_name != "public":
                raise SQLValidationError(f"Access to schema '{schema_name}' is forbidden.")
        else:
            tbl_name = ident
        if tbl_name in cte_names:
            return
        if tbl_name not in allowlist:
            raise SQLValidationError(f"Table '{tbl_name}' is not in the allow-listed table set.")
        if tbl_name not in out:
            out.append(tbl_name)

    # Extract FROM (including comma-joined tables) and JOIN table identifiers
    referenced_tables: list[str] = []
    for m in re.finditer(
        r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_.\"]*)",
        blanked_sql,
        flags=re.IGNORECASE,
    ):
        _register_table(m.group(1), referenced_tables)

    for m in re.finditer(
        r"\bFROM\s+(.+?)(?=\b(?:WHERE|JOIN|INNER|LEFT|RIGHT|FULL|CROSS|GROUP|HAVING|ORDER|LIMIT|OFFSET)\b|\)|$)",
        blanked_sql,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        from_clause = m.group(1).strip()
        if from_clause.startswith("("):
            continue
        for part in from_clause.split(","):
            first_tok = part.strip().split()
            if first_tok:
                _register_table(first_tok[0], referenced_tables)

    if not referenced_tables:
        raise SQLValidationError("SELECT query must reference at least one allow-listed table.")

    final_sql, limit_applied = _apply_limit_cap(clean_sql, blanked_sql, max_rows)
    return ValidatedSQL(
        sql=final_sql,
        tables=tuple(referenced_tables),
        limit_applied=limit_applied,
        validator_backend="strict_tokenizer_fallback",
    )
