"""Pure logic helpers for the Flask web UI.

This module intentionally avoids Flask-specific objects where possible so it is
simple to test and reuse.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class SortState:
    """Represents sorting selection for the runs table."""

    by: str = "created"
    direction: str = "desc"

    @property
    def reverse(self) -> bool:
        return self.direction == "desc"


def is_uvalue_dict(value: Any) -> bool:
    return isinstance(value, dict) and "val" in value and "err" in value and len(value) >= 2


def format_uvalue(value: dict[str, Any]) -> str:
    try:
        from uncertainties import ufloat  # pylint: disable=import-outside-toplevel
    except ImportError:
        ufloat = None

    try:
        val = float(value["val"])
        err = float(value["err"])
        if err == 0:
            return f"{val:.6g}"
        if ufloat is None:
            return f"{val:.6g} +- {err:.2g}"
        uvalue = ufloat(val, err)
        text = str(uvalue)
        if "+/-" in text:
            return text.replace("+/-", " +- ")
        return f"{uvalue.nominal_value:.6g} +- {uvalue.std_dev:.2g}"
    except (TypeError, ValueError, KeyError):
        return str(value)


def format_scalar(value: Any) -> str:
    if is_uvalue_dict(value):
        return format_uvalue(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def flatten_dict_rows(prefix: str, value: Any, rows: list[tuple[str, str]]) -> None:
    if value is None:
        return
    if is_uvalue_dict(value):
        rows.append((prefix, format_uvalue(value)))
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_prefix = f"{prefix}.{key}" if prefix else str(key)
            flatten_dict_rows(nested_prefix, nested, rows)
        return
    if isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            rows.append((prefix, ", ".join(format_scalar(item) for item in value)))
        return
    rows.append((prefix, format_scalar(value)))


def get_task_config(run_data: dict[str, Any], task_name: str) -> dict[str, Any]:
    for task_cfg in run_data.get("config", {}).get("pipeline", []):
        if task_cfg.get("task") == task_name:
            return task_cfg
    return {}


def extract_xy_from_config(
    payload: dict[str, Any],
    task_name: str,
    run_data: dict[str, Any],
) -> tuple[str | None, list[Any], str | None, list[Any]]:
    task_cfg = get_task_config(run_data, task_name)
    xaxis = str(task_cfg.get("xaxis", "back")).lower()
    x_mapping = {
        "back": "voltages",
        "drift": "drift_voltages",
        "time": "time_from_start",
        "pressure": "pressures",
    }
    x_key = x_mapping.get(xaxis)
    if x_key not in payload:
        x_key = None
        for candidate in x_mapping.values():
            if candidate in payload and isinstance(payload[candidate], list):
                x_key = candidate
                break

    task_y_candidates = {
        "gain": ["gain_vals", "gains", "gain"],
        "resolution": ["res_vals", "resolution_vals", "resolutions", "resolution"],
        "rate": ["rates", "rate_vals", "rate"],
    }
    y_key = None
    for candidate in task_y_candidates.get(task_name.lower(), []):
        if candidate in payload and isinstance(payload[candidate], list):
            y_key = candidate
            break
    if y_key is None:
        for key, value in payload.items():
            if key == x_key or not isinstance(value, list):
                continue
            y_key = key
            break

    x_values = payload.get(x_key) if x_key else []
    y_values = payload.get(y_key) if y_key else []
    return x_key, x_values if isinstance(x_values, list) else [], y_key, y_values if isinstance(
        y_values, list
    ) else []


def _first_list(payload: dict[str, Any], keys: list[str]) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def build_measurement_table(
    payload: dict[str, Any],
    task_name: str,
    run_data: dict[str, Any],
) -> tuple[list[str], list[list[str]]]:
    _, _, y_key, y_vals = extract_xy_from_config(payload, task_name, run_data)

    axis_columns: list[tuple[list[str], str]] = [
        (["voltages", "back_voltages"], "Back [V]"),
        (["drift_voltages", "drifts"], "Drift [V]"),
        (["pressures"], "Pressure [mbar]"),
        (["time_from_start", "times"], "Time [h]"),
    ]

    y_label_map = {
        "gain_vals": "Gain",
        "gains": "Gain",
        "gain": "Gain",
        "res_vals": "Resolution",
        "resolution_vals": "Resolution",
        "resolutions": "Resolution",
        "resolution": "Resolution",
        "rates": "Rate",
        "rate_vals": "Rate",
        "rate": "Rate",
    }

    y_label = y_label_map.get(y_key or "", y_key or task_name.title())
    headers = [label for _, label in axis_columns] + [y_label]

    axis_values = [_first_list(payload, keys) for keys, _ in axis_columns]
    max_rows = max([len(y_vals)] + [len(values) for values in axis_values])

    rows: list[list[str]] = []
    for idx in range(max_rows):
        row = [
            format_scalar(values[idx]) if idx < len(values) else ""
            for values in axis_values
        ]
        row.append(format_scalar(y_vals[idx]) if idx < len(y_vals) else "")
        rows.append(row)

    return headers, rows


def extract_fit_rows(payload: dict[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []

    def walk(prefix: str, value: Any) -> None:
        if not isinstance(value, dict):
            return
        for key, nested in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            if key == "model" and isinstance(nested, dict):
                flatten_dict_rows(child_prefix, nested, rows)
                continue
            if isinstance(nested, dict):
                walk(child_prefix, nested)

    walk("", payload)
    return rows


def html_table(headers: list[str], rows: list[list[str]], css_class: str = "") -> str:
    if not rows:
        return '<p class="muted">No data available.</p>'
    class_attr = f' class="{css_class}"' if css_class else ""
    parts = [f"<table{class_attr}><thead><tr>"]
    parts.extend(f"<th>{escape(header)}</th>" for header in headers)
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        parts.extend(f"<td>{escape(cell)}</td>" for cell in row)
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def safe_path_inside(base_dir: Path, relative_path: str) -> Path:
    base = base_dir.resolve()
    target = (base / relative_path).resolve()
    if target != base and base not in target.parents:
        raise ValueError("Path traversal not allowed")
    return target


def resolve_image_path(
    base_dir: Path,
    image_rel: str,
    folder: str | None = None,
) -> tuple[Path, str] | None:
    candidates: list[str] = [image_rel]
    basename = Path(image_rel).name
    if folder:
        folder_clean = str(folder).strip().strip("/")
        if folder_clean:
            candidates.append(f"{folder_clean}/{basename}")
    candidates.append(basename)

    seen: set[str] = set()
    for rel in candidates:
        if rel in seen:
            continue
        seen.add(rel)
        try:
            path = safe_path_inside(base_dir, rel)
        except ValueError:
            continue
        if path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
            continue
        if path.exists():
            return path, rel
    return None


def normalize_sort(by: str, direction: str) -> SortState:
    allowed_sort_fields = {"run_id", "mode", "created", "dates", "wafers", "structures"}
    safe_by = by if by in allowed_sort_fields else "created"
    safe_dir = direction if direction in {"asc", "desc"} else "desc"
    return SortState(by=safe_by, direction=safe_dir)


def sort_run_rows(rows: list[dict[str, str]], sort_state: SortState) -> None:
    def sort_key(row: dict[str, str]) -> str:
        value = row.get(sort_state.by, "")
        if sort_state.by == "created" and value == "Unknown":
            return ""
        return value.lower()

    rows.sort(key=sort_key, reverse=sort_state.reverse)


def sort_figure_rows(figures: list[dict[str, str | None]]) -> None:
    def group_key(item: dict[str, str | None]) -> tuple[int, str]:
        name = Path(str(item["rel"])).name.lower()
        if name.startswith("live_data_chip"):
            return (2, name)
        if name.startswith("live_data_"):
            return (1, name)
        return (0, name)

    figures.sort(key=group_key)
