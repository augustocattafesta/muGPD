from __future__ import annotations

import argparse
import hashlib
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any

from uncertainties import ufloat

from mugpd import ANALYSIS_RESULTS
from mugpd.fileio import AnalysisIndex, AnalysisRun

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency fallback.
    Image = None


ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
THUMBNAIL_CACHE_DIR = Path.home() / ".cache" / "mugpd" / "thumbnails"


def _is_uvalue_dict(value: Any) -> bool:
    return isinstance(value, dict) and "val" in value and "err" in value and len(value) >= 2


def _format_uvalue(value: dict[str, Any]) -> str:
    try:
        val = float(value["val"])
        err = float(value["err"])
        if err == 0:
            return f"{val:.6g}"
        uvalue = ufloat(val, err)
        text = str(uvalue)
        if "+/-" in text:
            return text.replace("+/-", " +- ")
        return f"{uvalue.nominal_value:.6g} +- {uvalue.std_dev:.2g}"
    except (TypeError, ValueError, KeyError):
        return str(value)


def _format_scalar(value: Any) -> str:
    if _is_uvalue_dict(value):
        return _format_uvalue(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _flatten_dict_rows(prefix: str, value: Any, rows: list[tuple[str, str]]) -> None:
    if value is None:
        return
    if _is_uvalue_dict(value):
        rows.append((prefix, _format_uvalue(value)))
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_dict_rows(nested_prefix, nested, rows)
        return
    if isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            rows.append((prefix, ", ".join(_format_scalar(item) for item in value)))
        return
    rows.append((prefix, _format_scalar(value)))


def _get_task_config(run_data: dict[str, Any], task_name: str) -> dict[str, Any]:
    for task_cfg in run_data.get("config", {}).get("pipeline", []):
        if task_cfg.get("task") == task_name:
            return task_cfg
    return {}


def _extract_xy_from_config(
    payload: dict[str, Any],
    task_name: str,
    run_data: dict[str, Any],
) -> tuple[str | None, list[Any], str | None, list[Any]]:
    task_cfg = _get_task_config(run_data, task_name)
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


def _build_measurement_table(
    payload: dict[str, Any],
    task_name: str,
    run_data: dict[str, Any],
) -> tuple[list[str], list[list[str]]]:
    x_key, _, y_key, y_vals = _extract_xy_from_config(payload, task_name, run_data)

    axis_columns: list[tuple[str, str]] = [
        ("voltages", "Back [V]"),
        ("drifts", "Drift [V]"),
        ("pressures", "Pressure [mbar]"),
        ("times", "Time [h]"),
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

    col_data: dict[str, list[Any]] = {}
    max_rows = len(y_vals)
    for key, _ in axis_columns:
        values = payload.get(key)
        if isinstance(values, list):
            col_data[key] = values
            max_rows = max(max_rows, len(values))
        else:
            col_data[key] = []

    if y_key and isinstance(payload.get(y_key), list):
        col_data[y_key] = payload[y_key]
    else:
        col_data[y_key or ""] = []

    rows: list[list[str]] = []
    for idx in range(max_rows):
        row: list[str] = []
        for key, _ in axis_columns:
            values = col_data.get(key, [])
            row.append(_format_scalar(values[idx]) if idx < len(values) else "")
        y_values = col_data.get(y_key or "", [])
        row.append(_format_scalar(y_values[idx]) if idx < len(y_values) else "")
        rows.append(row)

    return headers, rows


def _extract_fit_rows(payload: dict[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []

    def _walk(prefix: str, value: Any) -> None:
        if not isinstance(value, dict):
            return
        for key, nested in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            if key == "model" and isinstance(nested, dict):
                _flatten_dict_rows(child_prefix, nested, rows)
                continue
            if isinstance(nested, dict):
                _walk(child_prefix, nested)

    _walk("", payload)
    return rows


def _html_table(headers: list[str], rows: list[list[str]], css_class: str = "") -> str:
    if not rows:
        return '<p class="muted">No data available.</p>'
    class_attr = f' class="{css_class}"' if css_class else ""
    parts = [f"<table{class_attr}><thead><tr>"]
    for header in headers:
        parts.append(f"<th>{escape(header)}</th>")
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        for cell in row:
            parts.append(f"<td>{escape(cell)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _safe_path_inside(base_dir: Path, relative_path: str) -> Path:
    base = base_dir.resolve()
    target = (base / relative_path).resolve()
    if target != base and base not in target.parents:
        raise ValueError("Path traversal not allowed")
    return target


def _resolve_image_path(base_dir: Path, image_rel: str, folder: str | None = None) -> tuple[Path, str] | None:
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
            path = _safe_path_inside(base_dir, rel)
        except ValueError:
            continue
        if path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
            continue
        if path.exists():
            return path, rel
    return None


@lru_cache(maxsize=8)
def _cached_index(results_dir: str) -> AnalysisIndex:
    index = AnalysisIndex(Path(results_dir))
    index.build()
    return index


def _build_app(results_dir: Path) -> Any:
    from flask import Flask, abort, request, send_file, url_for

    app = Flask(__name__)

    @app.route("/")
    def home() -> str:
        if request.args.get("refresh") == "1":
            _cached_index.cache_clear()

        index = _cached_index(str(results_dir))
        available = index.available_values()

        filters_active = request.args.get("filters", "") == "1"
        selected_dates_raw = request.args.getlist("date")
        selected_wafers_raw = request.args.getlist("wafer")
        selected_structures_raw = request.args.getlist("structure")
        selected_dates = selected_dates_raw if filters_active else available["acquisition_dates"]
        selected_wafers = selected_wafers_raw if filters_active else available["wafers"]
        selected_structures = selected_structures_raw if filters_active else available["structures"]
        selected_img_page = max(1, request.args.get("img_page", default=1, type=int) or 1)
        selected_img_per_page = request.args.get("img_per_page", default=24, type=int) or 24
        if selected_img_per_page not in {24, 48, 96}:
            selected_img_per_page = 24
        sort_by = request.args.get("sort_by", "created")
        sort_dir = request.args.get("sort_dir", "desc")
        allowed_sort_fields = {"run_id", "mode", "created", "dates", "wafers", "structures"}
        if sort_by not in allowed_sort_fields:
            sort_by = "created"
        if sort_dir not in {"asc", "desc"}:
            sort_dir = "desc"

        records = index.filter(
            acquisition_dates=selected_dates if selected_dates else available["acquisition_dates"],
            wafers=selected_wafers if selected_wafers else available["wafers"],
            structures=selected_structures if selected_structures else available["structures"],
        )

        table_rows: list[dict[str, str]] = []
        for rec in records:
            details_url = url_for(
                "home",
                filters="1" if filters_active else None,
                date=selected_dates,
                wafer=selected_wafers,
                structure=selected_structures,
                sort_by=sort_by,
                sort_dir=sort_dir,
                manifest=str(rec.manifest_path),
            )
            table_rows.append(
                {
                    "run_id": rec.run_id,
                    "details_url": details_url,
                    "mode": rec.mode,
                    "created": rec.created_at or "Unknown",
                    "dates": ", ".join(rec.acquisition_dates) if rec.acquisition_dates else "N/A",
                    "wafers": ", ".join(rec.wafers) if rec.wafers else "N/A",
                    "structures": ", ".join(rec.structures) if rec.structures else "N/A",
                }
            )

        def _sort_key(row: dict[str, str]) -> str:
            value = row.get(sort_by, "")
            if sort_by == "created" and value == "Unknown":
                return ""
            return value.lower()

        table_rows.sort(key=_sort_key, reverse=(sort_dir == "desc"))

        selected_manifest = request.args.get("manifest", "")
        if not selected_manifest and records:
            selected_manifest = str(records[0].manifest_path)
        run_html = ""
        if selected_manifest:
            try:
                run_html = _render_run_section(
                    Path(selected_manifest),
                    img_page=selected_img_page,
                    img_per_page=selected_img_per_page,
                )
            except (FileNotFoundError, ValueError, TypeError) as exc:
                run_html = (
                    '<section class="card"><h2>Run details</h2>'
                    f'<p class="error">Cannot load selected run: {escape(str(exc))}</p></section>'
                )

        return _render_page(
            available=available,
            selected_dates=selected_dates,
            selected_wafers=selected_wafers,
            selected_structures=selected_structures,
            sort_by=sort_by,
            sort_dir=sort_dir,
            n_runs=len(records),
            runs_table_rows=table_rows,
            run_html=run_html,
        )

    @app.route("/image")
    def image():
        manifest = request.args.get("manifest", "")
        image_rel = request.args.get("file", "")
        folder = request.args.get("folder")
        if not manifest or not image_rel:
            abort(404)
        manifest_path = Path(manifest)
        if not manifest_path.exists():
            abort(404)
        resolved = _resolve_image_path(manifest_path.parent, image_rel, folder)
        if resolved is None:
            abort(404)
        image_path, _ = resolved
        return send_file(image_path)

    @app.route("/thumb")
    def thumbnail():
        manifest = request.args.get("manifest", "")
        image_rel = request.args.get("file", "")
        folder = request.args.get("folder")
        if not manifest or not image_rel:
            abort(404)
        manifest_path = Path(manifest)
        if not manifest_path.exists():
            abort(404)
        resolved = _resolve_image_path(manifest_path.parent, image_rel, folder)
        if resolved is None:
            abort(404)
        image_path, normalized_rel = resolved

        if Image is None:
            return send_file(image_path)

        THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        stat = image_path.stat()
        key = (
            f"{image_path}:{normalized_rel}:{folder}:{stat.st_mtime_ns}:{stat.st_size}"
        ).encode("utf-8")
        digest = hashlib.sha1(key, usedforsecurity=False).hexdigest()
        thumb_path = THUMBNAIL_CACHE_DIR / f"{digest}.jpg"

        if not thumb_path.exists():
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                img.thumbnail((960, 640))
                img.save(thumb_path, format="JPEG", quality=90, optimize=True)

        return send_file(thumb_path, mimetype="image/jpeg")

    return app


def _render_page(
    available: dict[str, list[str]],
    selected_dates: list[str],
    selected_wafers: list[str],
    selected_structures: list[str],
    sort_by: str,
    sort_dir: str,
    n_runs: int,
    runs_table_rows: list[dict[str, str]],
    run_html: str,
) -> str:
    date_options = "".join(
        (
            f"<option value=\"{escape(option)}\""
            f"{' selected' if option in selected_dates else ''}>{escape(option)}</option>"
        )
        for option in available["acquisition_dates"]
    )
    wafer_options = "".join(
        (
            f"<option value=\"{escape(option)}\""
            f"{' selected' if option in selected_wafers else ''}>{escape(option)}</option>"
        )
        for option in available["wafers"]
    )
    structure_options = "".join(
        (
            f"<option value=\"{escape(option)}\""
            f"{' selected' if option in selected_structures else ''}>{escape(option)}</option>"
        )
        for option in available["structures"]
    )

    def _sort_header_link(field: str, label: str) -> str:
        next_dir = "desc" if (sort_by == field and sort_dir == "asc") else "asc"
        arrow = ""
        if sort_by == field:
            arrow = " ↑" if sort_dir == "asc" else " ↓"
        link = (
            f"/?filters=1&sort_by={escape(field)}&sort_dir={escape(next_dir)}"
            + "".join(f"&date={escape(v)}" for v in selected_dates)
            + "".join(f"&wafer={escape(v)}" for v in selected_wafers)
            + "".join(f"&structure={escape(v)}" for v in selected_structures)
        )
        return f'<a class="sort-link" href="{link}">{escape(label)}{arrow}</a>'

    table_rows_html: list[str] = []
    for row in runs_table_rows:
        table_rows_html.append(
            "".join(
                [
                    "<tr>",
                    '<td><a href="',
                    escape(row["details_url"]),
                    '">',
                    escape(row["run_id"]),
                    "</a></td>",
                    f"<td>{escape(row['mode'])}</td>",
                    f"<td>{escape(row['created'])}</td>",
                    f"<td>{escape(row['dates'])}</td>",
                    f"<td>{escape(row['wafers'])}</td>",
                    f"<td>{escape(row['structures'])}</td>",
                    "</tr>",
                ]
            )
        )
    if table_rows_html:
        table_html = (
            '<table class="runs-table"><thead><tr>'
            f"<th>{_sort_header_link('run_id', 'Run')}</th>"
            f"<th>{_sort_header_link('mode', 'Mode')}</th>"
            f"<th>{_sort_header_link('created', 'Created')}</th>"
            f"<th>{_sort_header_link('dates', 'Acquisition date(s)')}</th>"
            f"<th>{_sort_header_link('wafers', 'Wafer(s)')}</th>"
            f"<th>{_sort_header_link('structures', 'Structure(s)')}</th>"
            "</tr></thead><tbody>"
            + "".join(table_rows_html)
            + "</tbody></table>"
        )
    else:
        table_html = '<p class="muted">No runs found with current filters.</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>muGPD Analysis Browser</title>
  <style>
    :root {{
      --bg: #f3efe4;
      --card: #fffef9;
      --ink: #102027;
      --muted: #5d6f74;
      --accent: #0b6e4f;
      --border: #d8d1bf;
      --error: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 100% 0%, #dff4e9 0, transparent 36%),
        radial-gradient(circle at 0% 100%, #f9e6cd 0, transparent 35%),
        var(--bg);
    }}
    .layout {{ max-width: 1400px; margin: 0 auto; padding: 24px; display: grid; gap: 16px; }}
    h1 {{ margin: 0; letter-spacing: 0.03em; }}
    h2 {{ margin: 0 0 12px 0; font-size: 1.2rem; }}
    h3 {{ margin: 0 0 10px 0; font-size: 1.05rem; }}
    .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 16px; }}
    .toolbar {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: end; }}
        .field {{ display: grid; gap: 6px; min-width: 220px; }}
        .field label {{ font-weight: 600; font-size: 0.9rem; }}
        select[multiple] {{
            min-height: 120px;
            max-height: 180px;
            border-radius: 10px;
            border: 1px solid var(--border);
            padding: 8px;
            background: #fff;
            font-family: inherit;
        }}
    .btn {{
      border: 0;
      border-radius: 10px;
      background: var(--accent);
      color: #fff;
      font-weight: 700;
      padding: 10px 14px;
      cursor: pointer;
      text-decoration: none;
      display: inline-block;
    }}
    .btn.secondary {{ background: #3f4e4f; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f5f1e5; font-size: 0.92rem; }}
    .sort-link {{ color: inherit; text-decoration: none; font-weight: 700; }}
    .sort-link:hover {{ text-decoration: underline; }}
    .muted {{ color: var(--muted); margin: 0; }}
    .error {{ color: var(--error); font-weight: 600; }}
    .split {{ display: grid; gap: 16px; grid-template-columns: 1fr; }}
    .fig-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 12px;
    }}
    .figure-card {{ border: 1px solid var(--border); border-radius: 12px; padding: 10px; background: #ffffff; }}
    .figure-card img {{ width: 100%; height: 170px; object-fit: contain; background: #f9f9f9; border-radius: 8px; }}
    .figure-meta {{ margin-top: 8px; font-size: 0.88rem; color: var(--muted); }}
    .pager {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 10px 0 14px 0; }}
    .pager-links {{ display: flex; gap: 10px; align-items: center; }}
    .pager a {{ color: var(--accent); text-decoration: none; font-weight: 700; }}
    details {{ border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; background: #fff; }}
    details + details {{ margin-top: 10px; }}
    summary {{ cursor: pointer; font-weight: 700; }}
    @media (min-width: 1080px) {{
      .split {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="layout">
    <section class="card">
      <h1>muGPD Analysis Browser</h1>
    </section>

    <section class="card">
      <h2>Filters</h2>
      <form method="get" class="toolbar">
                <input type="hidden" name="filters" value="1" />
        <div class="field">
                    <label for="date">Acquisition date</label>
                    <select id="date" name="date" multiple data-toggle-multi>
                        {date_options}
                    </select>
        </div>
        <div class="field">
                    <label for="wafer">Wafer</label>
                    <select id="wafer" name="wafer" multiple data-toggle-multi>
                        {wafer_options}
                    </select>
        </div>
        <div class="field">
                    <label for="structure">Structure</label>
                    <select id="structure" name="structure" multiple data-toggle-multi>
                        {structure_options}
                    </select>
        </div>
                <input type="hidden" name="sort_by" value="{escape(sort_by)}" />
                <input type="hidden" name="sort_dir" value="{escape(sort_dir)}" />
        <button class="btn" type="submit">Apply filters</button>
        <a class="btn secondary" href="/?refresh=1">Remove filters</a>
      </form>
    </section>

    <section class="card">
      <h2>Runs ({n_runs})</h2>
      {table_html}
    </section>

    {run_html}
  </main>
    <script>
        (function () {{
            const selects = document.querySelectorAll('select[multiple][data-toggle-multi]');
            selects.forEach((select) => {{
                let lastIndex = -1;
                select.addEventListener('mousedown', (event) => {{
                    const option = event.target;
                    if (!(option instanceof HTMLOptionElement)) {{
                        return;
                    }}
                    event.preventDefault();
                    const options = Array.from(select.options);
                    const clickedIndex = options.indexOf(option);
                    if (clickedIndex < 0) {{
                        return;
                    }}
                    if (event.shiftKey && lastIndex >= 0) {{
                        const start = Math.min(lastIndex, clickedIndex);
                        const end = Math.max(lastIndex, clickedIndex);
                        for (let idx = start; idx <= end; idx += 1) {{
                            options[idx].selected = true;
                        }}
                    }} else if (event.ctrlKey || event.metaKey) {{
                        option.selected = !option.selected;
                    }} else {{
                        // Plain click isolates the chosen value.
                        options.forEach((entry) => {{
                            entry.selected = (entry === option);
                        }});
                    }}
                    lastIndex = clickedIndex;
                    select.focus();
                }});
            }});
        }})();
    </script>
</body>
</html>"""


def _render_run_section(manifest_path: Path, img_page: int, img_per_page: int) -> str:
    run = AnalysisRun(manifest_path)

    meta_rows = [
        ["Analysis run", run.run_id],
        ["Analyzed", run.created_at or "Unknown"],
        ["Mode", run.mode],
        ["Acquisition date(s)", ", ".join(run.acquisition_dates()) or "N/A"],
        ["Wafer(s)", ", ".join(run.wafers()) or "N/A"],
        ["Structure(s)", ", ".join(run.structures()) or "N/A"],
    ]

    figures_html = _render_figures(run, img_page=img_page, img_per_page=img_per_page)
    tasks_html = _render_tasks(run)

    return (
        '<section class="card">'
        '<h2>Run details</h2>'
        f"{_html_table(['Field', 'Value'], [[str(a), str(b)] for a, b in meta_rows])}"
        f"{figures_html}"
        f"{tasks_html}"
        "</section>"
    )


def _render_figures(run: AnalysisRun, img_page: int, img_per_page: int) -> str:
    from flask import request, url_for

    figures = run.data.get("artifacts", {}).get("figures", [])
    cards: list[str] = []
    available_figures: list[dict[str, str | None]] = []
    for fig in figures:
        file_rel = fig.get("file", "")
        if not file_rel:
            continue
        ext = Path(file_rel).suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            continue

        resolved = _resolve_image_path(run.manifest_path.parent, file_rel, fig.get("folder"))
        if resolved is None:
            continue
        _, normalized_rel = resolved
        available_figures.append(
            {
                "label": fig.get("name", Path(file_rel).name),
                "folder": fig.get("folder"),
                "rel": normalized_rel,
            }
        )

    # Group figures for display order:
    # 0) all non-live_data files first
    # 1) live_data_* files next
    # 2) live_data_chip* files last
    # Keep ordering deterministic inside each group.
    def _figure_group_key(item: dict[str, str | None]) -> tuple[int, str]:
        name = Path(str(item["rel"])).name.lower()
        if name.startswith("live_data_chip"):
            return (2, name)
        if name.startswith("live_data_"):
            return (1, name)
        return (0, name)

    available_figures.sort(key=_figure_group_key)

    total = len(available_figures)
    if total == 0:
        return "<h3>Images</h3><p class=\"muted\">No images found for this run.</p>"

    total_pages = max(1, (total + img_per_page - 1) // img_per_page)
    current_page = min(max(1, img_page), total_pages)
    start_idx = (current_page - 1) * img_per_page
    end_idx = start_idx + img_per_page
    page_figures = available_figures[start_idx:end_idx]

    args_multi = request.args.to_dict(flat=False)
    args_multi["img_per_page"] = [str(img_per_page)]

    def _page_link(page_num: int) -> str:
        page_num = min(max(1, page_num), total_pages)
        args_multi["img_page"] = [str(page_num)]
        return url_for("home", **args_multi)

    for item in page_figures:
        normalized_rel = str(item["rel"])
        folder = item["folder"]

        thumb_url = url_for(
            "thumbnail",
            manifest=str(run.manifest_path),
            file=normalized_rel,
            folder=folder,
        )
        image_url = url_for(
            "image",
            manifest=str(run.manifest_path),
            file=normalized_rel,
            folder=folder,
        )
        label = str(item["label"])
        folder_display = folder or "-"
        cards.append(
            "".join(
                [
                    '<article class="figure-card">',
                    f'<a href="{escape(image_url)}" target="_blank" rel="noopener">',
                    f'<img src="{escape(thumb_url)}" loading="lazy" alt="{escape(label)}" />',
                    "</a>",
                    f"<strong>{escape(label)}</strong>",
                    '<div class="figure-meta">',
                    f"file: {escape(normalized_rel)}<br />",
                    f"folder: {escape(folder_display)}",
                    "</div>",
                    "</article>",
                ]
            )
        )

    per_page_parts: list[str] = []
    for value in (24, 48, 96):
        page_args = dict(args_multi)
        page_args["img_page"] = ["1"]
        page_args["img_per_page"] = [str(value)]
        if value == img_per_page:
            per_page_parts.append(f"<strong>{value}</strong>")
        else:
            per_page_parts.append(f'<a href="{escape(url_for("home", **page_args))}">{value}</a>')
    per_page_links = " ".join(per_page_parts)
    pager_html = "".join(
        [
            '<div class="pager">',
            f'<span class="muted">Images {start_idx + 1}-{min(end_idx, total)} of {total}</span>',
            '<div class="pager-links">',
            f'<a href="{escape(_page_link(1))}">First</a>',
            f'<a href="{escape(_page_link(current_page - 1))}">Prev</a>',
            f'<strong>Page {current_page}/{total_pages}</strong>',
            f'<a href="{escape(_page_link(current_page + 1))}">Next</a>',
            f'<a href="{escape(_page_link(total_pages))}">Last</a>',
            '</div>',
            f'<div class="pager-links">Per page: {per_page_links}</div>',
            '</div>',
        ]
    )
    return "<h3>Images</h3>" + pager_html + "<div class=\"fig-grid\">" + "".join(cards) + "</div>"


def _render_tasks(run: AnalysisRun) -> str:
    sections: list[str] = ["<h3>Task results</h3>"]
    if run.mode == "folders":
        folders = run.data.get("folders", {})
        for folder_name, folder_payload in folders.items():
            sections.append(
                _render_task_payloads(folder_payload.get("tasks", {}), f"Folder: {folder_name}", run.data)
            )
        sections.append(
            _render_task_payloads(run.data.get("folder_tasks", {}), "Folder-level tasks", run.data)
        )
    else:
        sections.append(_render_task_payloads(run.data.get("tasks", {}), "Run tasks", run.data))
    return "".join(sections)


def _render_task_payloads(tasks_payload: dict[str, Any], title: str, run_data: dict[str, Any]) -> str:
    if not tasks_payload:
        return f"<p class=\"muted\">{escape(title)}: no task payload available.</p>"

    details_blocks: list[str] = []
    for task_name, targets in tasks_payload.items():
        if not isinstance(targets, dict):
            details_blocks.append(
                "".join(
                    [
                        "<details>",
                        f"<summary>{escape(task_name)}</summary>",
                        f"<p>{escape(_format_scalar(targets))}</p>",
                        "</details>",
                    ]
                )
            )
            continue

        target_blocks: list[str] = []
        for target_name, payload in targets.items():
            if not isinstance(payload, dict):
                target_blocks.append(
                    f"<p><strong>{escape(target_name)}:</strong> {escape(_format_scalar(payload))}</p>"
                )
                continue

            measurement_headers, measurement_rows = _build_measurement_table(
                payload,
                task_name,
                run_data,
            )
            fit_rows = _extract_fit_rows(payload)

            target_sections = [f"<h4>{escape(target_name)}</h4>"]
            if measurement_rows:
                target_sections.append(
                    _html_table(
                        measurement_headers,
                        measurement_rows,
                    )
                )
            if fit_rows:
                target_sections.append(
                    _html_table(
                        ["Field", "Value"],
                        [[str(a), str(b)] for a, b in fit_rows],
                    )
                )

            target_blocks.append("".join(target_sections))

        details_blocks.append(
            "".join(
                [
                    "<details>",
                    f"<summary>{escape(task_name)}</summary>",
                    "".join(target_blocks),
                    "</details>",
                ]
            )
        )

    return (
        '<section class="card">'
        f"<h3>{escape(title)}</h3>"
        + "".join(details_blocks)
        + "</section>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mugpd-web",
        description="Run the muGPD HTML browser (Flask) as an alternative to Streamlit.",
    )
    parser.add_argument(
        "--results",
        default=str(ANALYSIS_RESULTS),
        help="Results directory containing analysis_run.yaml files.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host interface for the web server.")
    parser.add_argument("--port", type=int, default=7860, help="Port for the web server.")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode.")
    args = parser.parse_args()

    results_dir = Path(args.results)
    if not results_dir.exists():
        raise FileNotFoundError(f"Results directory does not exist: {results_dir}")

    app = _build_app(results_dir)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()