"""SQL table allowlist checks shared by training and HITL workflows."""

import re

TABLE_REFERENCE_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Z0-9_.$\"]+)", re.IGNORECASE
)


def extract_referenced_tables(sql: str) -> set[str]:
    tables = set()

    for match in TABLE_REFERENCE_PATTERN.finditer(sql):
        table_name = match.group(1).strip('"').split(".")[-1].upper()
        tables.add(table_name)

    return tables


def uses_only_allowed_tables(sql: str, allowed_tables: set[str]) -> bool:
    if not allowed_tables:
        return True

    referenced_tables = extract_referenced_tables(sql)
    return referenced_tables <= allowed_tables
