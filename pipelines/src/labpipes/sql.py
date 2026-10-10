"""Load the given SQL files as lists of statements."""

import re
from importlib.resources import files


def statements(name: str, **values: str) -> list[str]:
    """Statements of sql/<name>.sql with comments stripped and {placeholders} filled in."""
    text = re.sub(r"--[^\n]*", "", files("labpipes").joinpath("sql", f"{name}.sql").read_text())
    return [s.strip().format(**values) for s in text.split(";") if s.strip()]
