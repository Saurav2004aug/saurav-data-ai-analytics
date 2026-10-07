"""Pick a sensible chart for a query result (the assistant shows it automatically)."""
from __future__ import annotations

import pandas as pd


def _is_time(s: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(s):
        return True
    if s.dtype == object or pd.api.types.is_string_dtype(s):
        sample = s.dropna().astype(str).head(20)
        return len(sample) > 0 and sample.str.match(r"^\d{4}-\d{2}(-\d{2})?").all()
    name = str(s.name).lower()
    return pd.api.types.is_integer_dtype(s) and name in {"year", "order_year"}


def suggest_chart(df: pd.DataFrame) -> dict | None:
    """Return {"type": "line"|"bar", "x": col, "y": [cols]} or None for a table/number."""
    if df is None or len(df) < 2 or df.shape[1] < 2:
        return None
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not _is_time(df[c])]
    time_cols = [c for c in df.columns if _is_time(df[c])]
    if time_cols and numeric:
        return {"type": "line", "x": time_cols[0], "y": numeric[:3]}
    labels = [c for c in df.columns if c not in numeric]
    if labels and numeric and len(df) <= 30:
        return {"type": "bar", "x": labels[0], "y": numeric[:1]}
    return None
