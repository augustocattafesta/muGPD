"""Flask application for browsing muGPD analysis outputs.

This module contains a small OOP wrapper around Flask routes so that
request parsing, rendering, and data transformations are grouped in a
single maintainable unit.
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any, cast

from flask import Flask, abort, request, send_file, url_for

from mugpd import ANALYSIS_RESULTS
from mugpd.fileio import AnalysisIndex, AnalysisRun

from .logic import (
    ALLOWED_IMAGE_EXTENSIONS,
    build_measurement_table,
    extract_fit_rows,
    format_scalar,
    html_table,
    normalize_sort,
    resolve_image_path,
    sort_figure_rows,
    sort_run_rows,
)

pil_image: Any | None
try:
    from PIL import Image as _PILImage

    pil_image = _PILImage
except ImportError:  # pragma: no cover
    pil_image = None


THUMBNAIL_CACHE_DIR = Path.home() / ".cache" / "mugpd" / "thumbnails"


@dataclass(frozen=True)
class FilterState:
    """Current filter state for runs list."""

    dates: list[str]
    wafers: list[str]
    structures: list[str]


@lru_cache(maxsize=8)
def _cached_index(results_dir: str) -> AnalysisIndex:
    index = AnalysisIndex(Path(results_dir))
    index.build()
    return index


class BrowserWebApp:
    """Stateful builder for the muGPD Flask web application."""

    def __init__(self, results_dir: Path):
        self.results_dir = results_dir

    def create(self) -> Any:
        app = Flask(__name__)
        app.add_url_rule("/", view_func=self._home_view)
        app.add_url_rule("/image", view_func=self._image_view)
        app.add_url_rule("/thumb", view_func=self._thumbnail_view)
        return app

    def _home_view(self) -> str:
        if request.args.get("refresh") == "1":
            _cached_index.cache_clear()

        index = _cached_index(str(self.results_dir))
        available = index.available_values()

        filters_active = request.args.get("filters", "") == "1"
        filter_state = FilterState(
            dates=(
                request.args.getlist("date")
                if filters_active
                else available["acquisition_dates"]
            ),
            wafers=(
                request.args.getlist("wafer")
                if filters_active
                else available["wafers"]
            ),
            structures=(
                request.args.getlist("structure")
                if filters_active
                else available["structures"]
            ),
        )

        img_page = max(1, request.args.get("img_page", default=1, type=int) or 1)
        img_per_page = request.args.get("img_per_page", default=24, type=int) or 24
        if img_per_page not in {24, 48, 96}:
            img_per_page = 24

        sort_state = normalize_sort(
            request.args.get("sort_by", "created"),
            request.args.get("sort_dir", "desc"),
        )

        records = index.filter(
            acquisition_dates=filter_state.dates,
            wafers=filter_state.wafers,
            structures=filter_state.structures,
        )

        rows: list[dict[str, str]] = []
        for rec in records:
            details_url = url_for(
                "_home_view",
                filters="1" if filters_active else None,
                date=filter_state.dates,
                wafer=filter_state.wafers,
                structure=filter_state.structures,
                sort_by=sort_state.by,
                sort_dir=sort_state.direction,
                manifest=str(rec.manifest_path),
            )
            rows.append(
                {
                    "run_id": rec.run_id,
                    "details_url": details_url,
                    "mode": rec.mode,
                    "created": rec.created_at or "Unknown",
                    "dates": ", ".join(rec.acquisition_dates)
                    if rec.acquisition_dates
                    else "N/A",
                    "wafers": ", ".join(rec.wafers) if rec.wafers else "N/A",
                    "structures": ", ".join(rec.structures)
                    if rec.structures
                    else "N/A",
                }
            )

        sort_run_rows(rows, sort_state)

        selected_manifest = request.args.get("manifest", "")
        if not selected_manifest and records:
            selected_manifest = str(records[0].manifest_path)

        run_html = ""
        if selected_manifest:
            try:
                run_html = self._render_run_section(
                    Path(selected_manifest),
                    img_page=img_page,
                    img_per_page=img_per_page,
                )
            except (FileNotFoundError, ValueError, TypeError) as exc:
                run_html = (
                    '<section class="card"><h2>Run details</h2>'
                    f'<p class="error">Cannot load selected run: {escape(str(exc))}</p></section>'
                )

        return self._render_page(
            available=available,
            filters=filter_state,
            sort_state=sort_state,
            n_runs=len(records),
            runs_table_rows=rows,
            run_html=run_html,
        )

    @staticmethod
    def _image_view():
        manifest = request.args.get("manifest", "")
        image_rel = request.args.get("file", "")
        folder = request.args.get("folder")
        if not manifest or not image_rel:
            abort(404)
        manifest_path = Path(manifest)
        if not manifest_path.exists():
            abort(404)
        resolved = resolve_image_path(manifest_path.parent, image_rel, folder)
        if resolved is None:
            abort(404)
        image_path, _ = resolved
        return send_file(image_path)

    @staticmethod
    def _thumbnail_view():
        manifest = request.args.get("manifest", "")
        image_rel = request.args.get("file", "")
        folder = request.args.get("folder")
        if not manifest or not image_rel:
            abort(404)
        manifest_path = Path(manifest)
        if not manifest_path.exists():
            abort(404)
        resolved = resolve_image_path(manifest_path.parent, image_rel, folder)
        if resolved is None:
            abort(404)
        image_path, normalized_rel = resolved

        if pil_image is None:
            return send_file(image_path)

        THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        stat = image_path.stat()
        key = (
            f"{image_path}:{normalized_rel}:{folder}:{stat.st_mtime_ns}:{stat.st_size}"
        ).encode()
        digest = hashlib.sha1(key, usedforsecurity=False).hexdigest()
        thumb_path = THUMBNAIL_CACHE_DIR / f"{digest}.jpg"

        if not thumb_path.exists():
            with pil_image.open(image_path) as img:
                img = img.convert("RGB")
                img.thumbnail((960, 640))
                img.save(thumb_path, format="JPEG", quality=90, optimize=True)

        return send_file(thumb_path, mimetype="image/jpeg")

    def _render_page(
        self,
        available: dict[str, list[str]],
        filters: FilterState,
        sort_state: Any,
        n_runs: int,
        runs_table_rows: list[dict[str, str]],
        run_html: str,
    ) -> str:
        date_options = "".join(
            (
                f"<option value=\"{escape(option)}\""
                f"{' selected' if option in filters.dates else ''}>{escape(option)}</option>"
            )
            for option in available["acquisition_dates"]
        )
        wafer_options = "".join(
            (
                f"<option value=\"{escape(option)}\""
                f"{' selected' if option in filters.wafers else ''}>{escape(option)}</option>"
            )
            for option in available["wafers"]
        )
        structure_options = "".join(
            (
                f"<option value=\"{escape(option)}\""
                f"{' selected' if option in filters.structures else ''}>{escape(option)}</option>"
            )
            for option in available["structures"]
        )

        def sort_header_link(field: str, label: str) -> str:
            next_dir = (
                "desc"
                if sort_state.by == field and sort_state.direction == "asc"
                else "asc"
            )
            arrow = ""
            if sort_state.by == field:
                arrow = " ↑" if sort_state.direction == "asc" else " ↓"
            link = (
                f"/?filters=1&sort_by={escape(field)}&sort_dir={escape(next_dir)}"
                + "".join(f"&date={escape(v)}" for v in filters.dates)
                + "".join(f"&wafer={escape(v)}" for v in filters.wafers)
                + "".join(f"&structure={escape(v)}" for v in filters.structures)
            )
            return (
                f'<a class="sort-link" href="{link}">'
                f"{escape(label)}{arrow}</a>"
            )

        rows_html = [
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
            for row in runs_table_rows
        ]
        if rows_html:
            table_html = (
                '<table class="runs-table"><thead><tr>'
                f"<th>{sort_header_link('run_id', 'Run')}</th>"
                f"<th>{sort_header_link('mode', 'Mode')}</th>"
                f"<th>{sort_header_link('created', 'Created')}</th>"
                f"<th>{sort_header_link('dates', 'Acquisition date(s)')}</th>"
                f"<th>{sort_header_link('wafers', 'Wafer(s)')}</th>"
                f"<th>{sort_header_link('structures', 'Structure(s)')}</th>"
                "</tr></thead><tbody>"
                + "".join(rows_html)
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
        .card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px;
        }}
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
        th, td {{
            border-bottom: 1px solid var(--border);
            padding: 8px;
            text-align: left;
            vertical-align: top;
        }}
    th {{ background: #f5f1e5; font-size: 0.92rem; }}
    .sort-link {{ color: inherit; text-decoration: none; font-weight: 700; }}
    .sort-link:hover {{ text-decoration: underline; }}
    .muted {{ color: var(--muted); margin: 0; }}
    .error {{ color: var(--error); font-weight: 600; }}
        .fig-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
            gap: 12px;
        }}
        .figure-card {{
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 10px;
            background: #ffffff;
        }}
        .figure-card img {{
            width: 100%;
            height: 170px;
            object-fit: contain;
            background: #f9f9f9;
            border-radius: 8px;
        }}
    .figure-meta {{ margin-top: 8px; font-size: 0.88rem; color: var(--muted); }}
        .pager {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            align-items: center;
            margin: 10px 0 14px 0;
        }}
    .pager-links {{ display: flex; gap: 10px; align-items: center; }}
    .pager a {{ color: var(--accent); text-decoration: none; font-weight: 700; }}
        details {{
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 10px 12px;
            background: #fff;
        }}
    details + details {{ margin-top: 10px; }}
    summary {{ cursor: pointer; font-weight: 700; }}
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
        <input type="hidden" name="sort_by" value="{escape(sort_state.by)}" />
        <input type="hidden" name="sort_dir" value="{escape(sort_state.direction)}" />
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

    def _render_run_section(self, manifest_path: Path, img_page: int, img_per_page: int) -> str:
        run = AnalysisRun(manifest_path)

        meta_rows = [
            ["Analysis run", run.run_id],
            ["Analyzed", run.created_at or "Unknown"],
            ["Mode", run.mode],
            ["Acquisition date(s)", ", ".join(run.acquisition_dates()) or "N/A"],
            ["Wafer(s)", ", ".join(run.wafers()) or "N/A"],
            ["Structure(s)", ", ".join(run.structures()) or "N/A"],
        ]

        figures_html = self._render_figures(run, img_page=img_page, img_per_page=img_per_page)
        tasks_html = self._render_tasks(run)

        return (
            '<section class="card">'
            '<h2>Run details</h2>'
            f"{html_table(['Field', 'Value'], [[str(a), str(b)] for a, b in meta_rows])}"
            f"{figures_html}"
            f"{tasks_html}"
            "</section>"
        )

    def _render_figures(self, run: AnalysisRun, img_page: int, img_per_page: int) -> str:
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

            resolved = resolve_image_path(run.manifest_path.parent, file_rel, fig.get("folder"))
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

        sort_figure_rows(available_figures)

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

        def page_link(page_num: int) -> str:
            page_num = min(max(1, page_num), total_pages)
            args_multi["img_page"] = [str(page_num)]
            return url_for("_home_view", **cast(dict[str, Any], args_multi))

        for item in page_figures:
            normalized_rel = str(item["rel"])
            folder = item["folder"]

            thumb_url = url_for(
                "_thumbnail_view",
                manifest=str(run.manifest_path),
                file=normalized_rel,
                folder=folder,
            )
            image_url = url_for(
                "_image_view",
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
                per_page_parts.append(
                    f'<a href="{escape(url_for("_home_view",
                                               **cast(dict[str, Any], page_args)))}">{value}</a>'
                )
        per_page_links = " ".join(per_page_parts)

        pager_html = "".join(
            [
                '<div class="pager">',
                (
                    f'<span class="muted">Images '
                    f"{start_idx + 1}-{min(end_idx, total)} of {total}</span>"
                ),
                '<div class="pager-links">',
                f'<a href="{escape(page_link(1))}">First</a>',
                f'<a href="{escape(page_link(current_page - 1))}">Prev</a>',
                f'<strong>Page {current_page}/{total_pages}</strong>',
                f'<a href="{escape(page_link(current_page + 1))}">Next</a>',
                f'<a href="{escape(page_link(total_pages))}">Last</a>',
                '</div>',
                f'<div class="pager-links">Per page: {per_page_links}</div>',
                '</div>',
            ]
        )
        return "<h3>Images</h3>" + pager_html + '<div class="fig-grid">' + "".join(cards) + "</div>"

    def _render_tasks(self, run: AnalysisRun) -> str:
        sections: list[str] = ["<h3>Task results</h3>"]
        if run.mode == "folders":
            folders = run.data.get("folders", {})
            for folder_name, folder_payload in folders.items():
                sections.append(
                    self._render_task_payloads(
                        folder_payload.get("tasks", {}),
                        f"Folder: {folder_name}",
                        run.data,
                    )
                )
            sections.append(
                self._render_task_payloads(
                    run.data.get("folder_tasks", {}),
                    "Folder-level tasks",
                    run.data,
                )
            )
        else:
            sections.append(
                self._render_task_payloads(
                    run.data.get("tasks", {}),
                    "Run tasks",
                    run.data,
                )
            )
        return "".join(sections)

    def _render_task_payloads(
        self,
        tasks_payload: dict[str, Any],
        title: str,
        run_data: dict[str, Any],
    ) -> str:
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
                            f"<p>{escape(format_scalar(targets))}</p>",
                            "</details>",
                        ]
                    )
                )
                continue

            target_blocks: list[str] = []
            for target_name, payload in targets.items():
                if not isinstance(payload, dict):
                    target_blocks.append(
                        "".join(
                            [
                                f"<p><strong>{escape(target_name)}:</strong> ",
                                f"{escape(format_scalar(payload))}</p>",
                            ]
                        )
                    )
                    continue

                measurement_headers, measurement_rows = build_measurement_table(
                    payload,
                    task_name,
                    run_data,
                )
                fit_rows = extract_fit_rows(payload)

                target_sections = [f"<h4>{escape(target_name)}</h4>"]
                if measurement_rows:
                    target_sections.append(html_table(measurement_headers, measurement_rows))
                if fit_rows:
                    target_sections.append(
                        html_table(
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


def create_app(results_dir: Path) -> Any:
    """Create the Flask app instance for the given results root."""

    return BrowserWebApp(results_dir).create()


def main() -> None:
    """CLI entrypoint for starting the Flask web server."""

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

    app = create_app(results_dir)
    app.run(host=args.host, port=args.port, debug=args.debug)
