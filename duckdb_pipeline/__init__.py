from pathlib import Path

_ROOT = Path(__file__).resolve().parent
__path__ = [str(_ROOT / "src" / "duckdb_pipeline")]
