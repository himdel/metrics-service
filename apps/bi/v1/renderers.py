import csv
import io
from typing import Any

from rest_framework.renderers import BaseRenderer


class CsvRenderer(BaseRenderer):
    media_type = "text/csv"
    format = "csv"
    charset = "utf-8"

    def render(self, data: Any, accepted_media_type: str | None = None, renderer_context: dict | None = None) -> Any:
        return data


def csv_safe(value: Any) -> str:
    s = str(value) if value is not None else ""
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{s}"
    return s


def _flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict:
    items: list[tuple[str, Any]] = []
    for k, v in d.items():
        key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, key, sep).items())
        elif isinstance(v, list):
            items.append((key, str(v)))
        else:
            items.append((key, v))
    return dict(items)


def json_to_csv(data: Any) -> str:
    output = io.StringIO()
    writer = csv.writer(output)

    if isinstance(data, list) and data and isinstance(data[0], dict):
        headers = list(dict.fromkeys(k for row in data for k in _flatten_dict(row)))
        writer.writerow(headers)
        for row in data:
            flat = _flatten_dict(row)
            writer.writerow(csv_safe(flat.get(h)) for h in headers)
    elif isinstance(data, dict):
        flat = _flatten_dict(data)
        writer.writerow(flat.keys())
        writer.writerow(csv_safe(v) for v in flat.values())
    else:
        writer.writerow(["value"])
        writer.writerow([csv_safe(data)])

    return output.getvalue()
