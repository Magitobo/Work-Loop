import re
import subprocess
from datetime import datetime

from .constants import *


def _is_data_row(cols: list[str]) -> bool:
    """Return True if the row is a real data row (not header, separator, or empty)."""
    if len(cols) < COL_STATUS + 1:
        return False
    id_val = cols[COL_ID].strip()
    if not id_val or re.match(r'^[-\s]+$', id_val) or id_val == 'ID':
        return False
    return True


def _is_table_separator(line: str) -> bool:
    """Return True if the line is a markdown table separator (e.g. |---|---| or | --- | :---: |)."""
    stripped = line.strip()
    return bool(stripped.startswith('|') and re.match(r'^[|\s:\-]+$', stripped) and '-' in stripped)


def _is_table_header(line: str) -> bool:
    """Return True if the line is a markdown table header."""
    stripped = line.strip()
    if not stripped.startswith('|') or _is_table_separator(stripped):
        return False
    if '[' in stripped or '](' in stripped:
        return False
    cells = [c.strip().lower() for c in stripped.split('|')[1:-1] if c.strip()]
    if not cells:
        return False
    header_keywords = {'task', 'task / conversation', 'title', 'title / initial prompt', 'status', 'last updated', 'budget', 'id', 'location', 'log', 'what it does'}
    matches = sum(1 for c in cells if any(k == c or c.startswith(k) for k in header_keywords))
    return matches >= max(1, len(cells) // 2)


def _ts() -> str:
    return datetime.now().strftime('%H:%M:%S')


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check)


