"""PriceWatch CA."""

from pathlib import Path


def _read_version() -> str:
    for candidate in (Path(__file__).resolve().parent / "VERSION", Path(__file__).resolve().parents[2] / "VERSION"):
        if candidate.is_file():
            return candidate.read_text().strip()
    return "0.0.0"


__version__ = _read_version()
