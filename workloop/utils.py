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


def _ts() -> str:
    return datetime.now().strftime('%H:%M:%S')


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check)


