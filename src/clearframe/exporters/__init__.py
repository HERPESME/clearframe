def safe_cell(value: str) -> str:
    """Neutralize spreadsheet formula injection in CSV text cells.

    Labels and owner names originate from footage content and open-web
    research; a leading = + - @ (or tab/CR) would execute as a formula when
    the coordinator opens the export in Excel/Sheets.
    """
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value
