"""Flask application for browsing muGPD analysis outputs.

This module contains a small OOP wrapper around Flask routes so that
request parsing, rendering, and data transformations are grouped in a
single maintainable unit.
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from datetime import datetime
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
RUNS_PER_PAGE = 10


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
        run_page = max(1, request.args.get("run_page", default=1, type=int) or 1)

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
                    "manifest": str(rec.manifest_path),
                    "details_url": details_url,
                    "mode": rec.mode,
                    "created": self._format_created_at(rec.created_at),
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

        n_runs = len(rows)
        run_total_pages = max(1, (n_runs + RUNS_PER_PAGE - 1) // RUNS_PER_PAGE)
        run_page = min(max(1, run_page), run_total_pages)
        run_start = (run_page - 1) * RUNS_PER_PAGE
        run_end = run_start + RUNS_PER_PAGE
        page_rows = rows[run_start:run_end]

        selected_manifest = request.args.get("manifest", "")

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
            n_runs=n_runs,
            run_page=run_page,
            run_total_pages=run_total_pages,
            run_start=run_start,
            run_end=min(run_end, n_runs),
            runs_table_rows=page_rows,
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

    @staticmethod
    def _format_created_at(value: str | None) -> str:
        if not value:
            return "Unknown"

        text = value.strip()
        if not text:
            return "Unknown"

        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed.strftime("%d %b %Y, %H:%M:%S")
        except ValueError:
            pass

        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                parsed = datetime.strptime(text, fmt)
                return parsed.strftime("%d %b %Y, %H:%M:%S")
            except ValueError:
                continue

        if "." in text:
            return text.split(".", maxsplit=1)[0].replace("T", " ")
        return text.replace("T", " ")

    @staticmethod
    def _render_numeric_pager(
        current_page: int,
        total_pages: int,
        link_for_page: Any,
    ) -> str:
        if total_pages <= 1:
            return ""

        pages: set[int] = {1, total_pages}
        for page in range(current_page - 2, current_page + 3):
            if 1 <= page <= total_pages:
                pages.add(page)
        ordered_pages = sorted(pages)

        links: list[str] = []
        prev_page = max(1, current_page - 1)
        next_page = min(total_pages, current_page + 1)

        if current_page > 1:
            links.append(
                f'<a class="pager-arrow" href="{escape(link_for_page(prev_page))}" '
                'aria-label="Previous page">&larr;</a>'
            )
        else:
            links.append('<span class="pager-arrow disabled">&larr;</span>')

        last = None
        for page in ordered_pages:
            if last is not None and page - last > 1:
                links.append('<span class="pager-ellipsis">...</span>')
            if page == current_page:
                links.append(f'<span class="pager-page current">{page}</span>')
            else:
                links.append(
                    f'<a class="pager-page" href="{escape(link_for_page(page))}">{page}</a>'
                )
            last = page

        if current_page < total_pages:
            links.append(
                f'<a class="pager-arrow" href="{escape(link_for_page(next_page))}" '
                'aria-label="Next page">&rarr;</a>'
            )
        else:
            links.append('<span class="pager-arrow disabled">&rarr;</span>')

        return '<div class="pager-links">' + "".join(links) + "</div>"

    @staticmethod
    def _format_summary_value(value: Any) -> str:
        if value in (None, "", "Unknown"):
            return "-"
        if isinstance(value, float):
            return f"{value:.6g}"
        if isinstance(value, list):
            if not value:
                return "-"
            first = value[0]
            return BrowserWebApp._format_summary_value(first)
        return str(value)

    @staticmethod
    def _source_match_score(
        source_name: str,
        payload: dict[str, Any],
        figure_context: str,
    ) -> int:
        score = 0
        source_stem = Path(source_name).stem.lower()
        source_base = Path(source_name).name.lower()
        if source_stem and source_stem in figure_context:
            score += 10
        if source_base and source_base in figure_context:
            score += 10

        voltage = payload.get("voltage")
        if isinstance(voltage, (int, float)) and f"b{int(voltage)}" in figure_context:
            score += 3

        drift_voltage = payload.get("drift_voltage")
        if isinstance(drift_voltage, (int, float)) and f"d{int(drift_voltage)}" in figure_context:
            score += 3

        structure = payload.get("structure")
        if isinstance(structure, str) and structure.lower() in figure_context:
            score += 1

        wafer = payload.get("wafer")
        if isinstance(wafer, str) and wafer.lower() in figure_context:
            score += 1

        return score

    def _time_from_source(self, source_payload: dict[str, Any]) -> str:
        raw_time = source_payload.get("time_from_start")
        if raw_time in (None, ""):
            raw_time = source_payload.get("time")
        if raw_time in (None, ""):
            raw_time = source_payload.get("times")
        if raw_time in (None, ""):
            raw_time = source_payload.get("real_time")

        if raw_time in (None, ""):
            return "-"

        if isinstance(raw_time, (int, float)) and source_payload.get("real_time") == raw_time:
            return self._format_summary_value(float(raw_time) / 3600.0)

        return self._format_summary_value(raw_time)

    def _figure_summary(
        self,
        fig: dict[str, Any],
        run: AnalysisRun,
    ) -> dict[str, str]:
        sources = run.sources()
        figure_context = " ".join(
            [
                str(fig.get("file", "")),
                str(fig.get("name", "")),
                str(fig.get("source", "")),
                str(fig.get("source_name", "")),
            ]
        ).lower()

        source_payload: dict[str, Any] = {}
        best_score = -1
        for source_name, payload in sources.items():
            if not isinstance(payload, dict):
                continue
            score = self._source_match_score(str(source_name), payload, figure_context)
            if score > best_score:
                best_score = score
                source_payload = payload

        if best_score <= 0 and len(sources) == 1:
            only_payload = next(iter(sources.values()))
            if isinstance(only_payload, dict):
                source_payload = only_payload

        def get_value(*keys: str) -> str:
            for key in keys:
                if key in source_payload:
                    return self._format_summary_value(source_payload.get(key))
            return "-"

        chip_value = get_value("chip", "wafer")
        structure_value = get_value("structure")
        if chip_value == "-":
            run_wafers = run.wafers()
            chip_value = run_wafers[0] if len(run_wafers) == 1 else "-"
        if structure_value == "-":
            run_structures = run.structures()
            structure_value = run_structures[0] if len(run_structures) == 1 else "-"

        time_value = self._time_from_source(source_payload)

        return {
            "back": get_value("voltage", "back_voltage", "back", "voltages"),
            "drift": get_value("drift_voltage", "drift", "drift_voltages"),
            "pressure": get_value("pressure", "pressures"),
            "time": time_value,
            "chip": chip_value,
            "structure": structure_value,
        }

    @staticmethod
    def _is_spectrum_figure(fig: dict[str, Any]) -> bool:
        text = " ".join(
            [
                str(fig.get("name", "")),
                str(fig.get("file", "")),
                str(fig.get("folder", "")),
            ]
        ).lower()

        non_spectrum_tokens = (
            "calibration",
            "gain",
            "resolution",
            "resoution",
            "rate",
            "drift",
            "compare",
            "comparison",
            "noise",
            "trend",
            "fit",
        )
        if any(token in text for token in non_spectrum_tokens):
            return False

        if "live_data" in text or "spectrum" in text or "spectra" in text:
            return True
        return "_b" in text

    def _render_page(
        self,
        available: dict[str, list[str]],
        filters: FilterState,
        sort_state: Any,
        n_runs: int,
        run_page: int,
        run_total_pages: int,
        run_start: int,
        run_end: int,
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

        run_pager = ""
        if n_runs > 0:
            base_args = {
                "filters": "1",
                "sort_by": sort_state.by,
                "sort_dir": sort_state.direction,
                "date": filters.dates,
                "wafer": filters.wafers,
                "structure": filters.structures,
            }

            def run_page_link(page_num: int) -> str:
                page_num = min(max(1, page_num), run_total_pages)
                return url_for("_home_view", **base_args, run_page=page_num)

            run_numeric_pages = self._render_numeric_pager(
                current_page=run_page,
                total_pages=run_total_pages,
                link_for_page=run_page_link,
            )

            run_pager = "".join(
                [
                    '<div class="pager">',
                    (
                        f'<span class="muted">Runs '
                        f"{run_start + 1}-{run_end} of {n_runs}</span>"
                    ),
                    run_numeric_pages,
                    "</div>",
                ]
            )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>muGPD Analysis Browser</title>
  <style>
    :root {{
            --bg: #f5f3ef;
            --card: #fffdfa;
            --ink: #1f2528;
            --muted: #5f676c;
            --accent: #1f4f6b;
            --accent-soft: #e9f0f5;
            --border: #d7d1c6;
      --error: #b42318;
            --shadow: 0 6px 18px rgba(31, 37, 40, 0.07);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
            font-family: "Source Sans 3", "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
                radial-gradient(circle at 100% 0%, #eef2f4 0, transparent 36%),
                radial-gradient(circle at 0% 100%, #f2ece2 0, transparent 35%),
        var(--bg);
    }}
        .layout {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 24px;
            display: grid;
            gap: 16px;
        }}
        h1 {{
            margin: 0;
            letter-spacing: 0.02em;
            font-size: 1.5rem;
            font-family: "Source Serif 4", "Georgia", serif;
            font-weight: 600;
        }}
        h2 {{
            margin: 0 0 12px 0;
            font-size: 1.2rem;
            padding-bottom: 6px;
            border-bottom: 1px dashed var(--border);
        }}
    h3 {{ margin: 0 0 10px 0; font-size: 1.05rem; }}
        .card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px;
                        box-shadow: var(--shadow);
        }}
                .card:first-child {{
                        background: linear-gradient(135deg, #ffffff 0%, #f4f1ea 100%);
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
        select[multiple]:focus {{
            outline: 2px solid var(--accent-soft);
            border-color: var(--accent);
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
            transition: filter 0.12s ease;
        }}
        .btn:hover {{
            filter: brightness(1.02);
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
    .runs-table tbody tr:nth-child(even) {{ background: #fcfbf8; }}
    .runs-table tbody tr:hover {{ background: #eef3f7; }}
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
            transition: box-shadow 0.16s ease;
        }}
        .figure-card:hover {{
            box-shadow: 0 8px 18px rgba(31, 37, 40, 0.1);
        }}
        .figure-card img {{
            width: 100%;
            height: 170px;
            object-fit: contain;
            background: #f9f9f9;
            border-radius: 8px;
        }}
        .figure-summary {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 8px;
            font-size: 0.86rem;
            background: #fff;
        }}
        .figure-summary th,
        .figure-summary td {{
            border-bottom: 1px solid var(--border);
            padding: 4px 6px;
            vertical-align: top;
        }}
        .figure-summary th {{
            width: 45%;
            color: var(--muted);
            font-weight: 600;
            background: #f8f5ef;
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
        .pager-page,
        .pager-arrow {{
            min-width: 28px;
            height: 28px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 0 6px;
            background: #fff;
            color: var(--ink);
            text-decoration: none;
            font-weight: 600;
            transition: background 0.12s ease, color 0.12s ease;
        }}
        .pager-page:hover,
        .pager-arrow:hover {{
            background: var(--accent-soft);
        }}
        .pager-page.current {{
            background: var(--accent);
            color: #fff;
            border-color: var(--accent);
        }}
        .pager-arrow.disabled {{
            opacity: 0.5;
            pointer-events: none;
            background: #f5f5f5;
        }}
        .pager-ellipsis {{ color: var(--muted); padding: 0 4px; }}
        details {{
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 10px 12px;
            background: #fff;
        }}
    details + details {{ margin-top: 10px; }}
    summary {{ cursor: pointer; font-weight: 700; }}
        .modal {{
            position: fixed;
            inset: 0;
            background: rgba(10, 16, 18, 0.86);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            padding: 18px;
        }}
        .modal.open {{ display: flex; }}
        .modal-content {{
            position: relative;
            width: min(96vw, 1500px);
            height: min(92vh, 950px);
            display: grid;
            grid-template-rows: 1fr auto;
            gap: 10px;
            background: #12181c;
            border: 1px solid #2e3a42;
            border-radius: 12px;
            padding: 12px;
        }}
        .modal-image-wrap {{
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 0;
        }}
        .modal-image-wrap img {{
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
            border-radius: 8px;
            background: #0a0f12;
        }}
        .modal-caption {{
            color: #d6dde2;
            font-size: 0.9rem;
            line-height: 1.3;
            word-break: break-word;
        }}
        .modal-summary {{
            margin-top: 8px;
            width: 100%;
        }}
        .modal-summary table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.88rem;
            color: #d6dde2;
        }}
        .modal-summary th,
        .modal-summary td {{
            border-bottom: 1px solid #344149;
            padding: 5px 8px;
            text-align: left;
        }}
        .modal-summary th {{
            width: 42%;
            color: #9eb0bc;
            font-weight: 600;
            background: rgba(255, 255, 255, 0.02);
        }}
        .modal-btn {{
            position: absolute;
            border: 1px solid #4a5c66;
            background: rgba(18, 24, 28, 0.86);
            color: #ecf2f6;
            border-radius: 9px;
            width: 40px;
            height: 40px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 1.1rem;
        }}
        .modal-btn:hover {{ background: rgba(31, 79, 107, 0.8); }}
        .modal-prev {{ left: 14px; top: 50%; transform: translateY(-50%); }}
        .modal-next {{ right: 14px; top: 50%; transform: translateY(-50%); }}
        .modal-close {{ right: 12px; top: 12px; }}
        @media (max-width: 780px) {{
            .layout {{ padding: 14px; gap: 12px; }}
            h1 {{ font-size: 1.25rem; }}
            .field {{ min-width: 100%; }}
            .toolbar {{ gap: 10px; }}
            .pager {{ justify-content: center; }}
            .pager-links {{ flex-wrap: wrap; justify-content: center; }}
            .modal-content {{ width: 98vw; height: 86vh; padding: 10px; }}
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
        <input type="hidden" name="sort_by" value="{escape(sort_state.by)}" />
        <input type="hidden" name="sort_dir" value="{escape(sort_state.direction)}" />
        <button class="btn" type="submit">Apply filters</button>
        <a class="btn secondary" href="/?refresh=1">Remove filters</a>
      </form>
    </section>

    <section class="card">
      <h2>Runs ({n_runs})</h2>
            {run_pager}
      {table_html}
    </section>

    {run_html}
  </main>
    <div id="image-modal" class="modal" aria-hidden="true">
        <div class="modal-content" role="dialog" aria-modal="true" aria-label="Image preview">
            <button id="modal-close" class="modal-btn modal-close" type="button" aria-label="Close">
                ✕
            </button>
                        <button
                            id="modal-prev"
                            class="modal-btn modal-prev"
                            type="button"
                            aria-label="Previous image"
                        >
                ←
            </button>
                        <button
                            id="modal-next"
                            class="modal-btn modal-next"
                            type="button"
                            aria-label="Next image"
                        >
                →
            </button>
            <div class="modal-image-wrap">
                <img id="modal-image" src="" alt="" />
            </div>
            <div id="modal-caption" class="modal-caption"></div>
            <div id="modal-summary" class="modal-summary"></div>
        </div>
    </div>
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

            const modal = document.getElementById('image-modal');
            const modalImage = document.getElementById('modal-image');
            const modalCaption = document.getElementById('modal-caption');
            const modalSummary = document.getElementById('modal-summary');
            const modalPrev = document.getElementById('modal-prev');
            const modalNext = document.getElementById('modal-next');
            const modalClose = document.getElementById('modal-close');
            const figureLinks = Array.from(document.querySelectorAll('a.figure-open[data-full]'));
            let currentIndex = -1;

            function escapeHtml(text) {{
                return String(text)
                    .replaceAll('&', '&amp;')
                    .replaceAll('<', '&lt;')
                    .replaceAll('>', '&gt;')
                    .replaceAll('"', '&quot;')
                    .replaceAll("'", '&#39;');
            }}

            function renderModalSummary(summaryRaw) {{
                if (!modalSummary) {{
                    return;
                }}
                if (!summaryRaw) {{
                    modalSummary.innerHTML = '';
                    return;
                }}

                const rows = summaryRaw
                    .split('||')
                    .map((chunk) => chunk.split('::'))
                    .filter((pair) => pair.length >= 2);

                if (rows.length === 0) {{
                    modalSummary.innerHTML = '';
                    return;
                }}

                const rowsHtml = rows
                    .map((pair) => (
                        '<tr>'
                        + `<th>${{escapeHtml(pair[0])}}</th>`
                        + `<td>${{escapeHtml(pair.slice(1).join('::'))}}</td>`
                        + '</tr>'
                    ))
                    .join('');

                modalSummary.innerHTML = `<table><tbody>${{rowsHtml}}</tbody></table>`;
            }}

            function setModalImage(index) {{
                if (!modalImage || !modalCaption || figureLinks.length === 0) {{
                    return;
                }}
                const safeIndex = (index + figureLinks.length) % figureLinks.length;
                currentIndex = safeIndex;
                const link = figureLinks[safeIndex];
                const full = link.getAttribute('data-full') || link.getAttribute('href') || '';
                const caption = link.getAttribute('data-caption') || '';
                const summary = link.getAttribute('data-summary') || '';
                modalImage.setAttribute('src', full);
                modalImage.setAttribute('alt', caption || 'Image preview');
                modalCaption.textContent = caption;
                renderModalSummary(summary);
            }}

            function openModal(index) {{
                if (!modal) {{
                    return;
                }}
                setModalImage(index);
                modal.classList.add('open');
                modal.setAttribute('aria-hidden', 'false');
                document.body.style.overflow = 'hidden';
            }}

            function closeModal() {{
                if (!modal) {{
                    return;
                }}
                modal.classList.remove('open');
                modal.setAttribute('aria-hidden', 'true');
                document.body.style.overflow = '';
            }}

            figureLinks.forEach((link, index) => {{
                link.addEventListener('click', (event) => {{
                    event.preventDefault();
                    openModal(index);
                }});
            }});

            if (modalPrev) {{
                modalPrev.addEventListener('click', () => setModalImage(currentIndex - 1));
            }}
            if (modalNext) {{
                modalNext.addEventListener('click', () => setModalImage(currentIndex + 1));
            }}
            if (modalClose) {{
                modalClose.addEventListener('click', closeModal);
            }}
            if (modal) {{
                modal.addEventListener('click', (event) => {{
                    if (event.target === modal) {{
                        closeModal();
                    }}
                }});
            }}

            document.addEventListener('keydown', (event) => {{
                if (!modal || !modal.classList.contains('open')) {{
                    return;
                }}
                if (event.key === 'Escape') {{
                    closeModal();
                }} else if (event.key === 'ArrowLeft') {{
                    setModalImage(currentIndex - 1);
                }} else if (event.key === 'ArrowRight') {{
                    setModalImage(currentIndex + 1);
                }}
            }});
    }})();
  </script>
</body>
</html>"""

    def _render_run_section(self, manifest_path: Path, img_page: int, img_per_page: int) -> str:
        run = AnalysisRun(manifest_path)

        meta_rows = [
            ["Analysis run", run.run_id],
            ["Analyzed", self._format_created_at(run.created_at)],
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
        available_figures: list[dict[str, Any]] = []
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
            show_summary = self._is_spectrum_figure(fig)
            summary = self._figure_summary(fig, run) if show_summary else None
            available_figures.append(
                {
                    "label": fig.get("name", Path(file_rel).name),
                    "folder": fig.get("folder"),
                    "rel": normalized_rel,
                    "summary": summary,
                    "show_summary": show_summary,
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

        numeric_pages = self._render_numeric_pager(
            current_page=current_page,
            total_pages=total_pages,
            link_for_page=page_link,
        )

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
            caption = f"{label} - {normalized_rel}"
            summary_html = ""
            summary_data = ""
            if item.get("show_summary"):
                summary = cast(dict[str, str], item.get("summary"))
                summary_rows = [
                    ("Back [V]", summary["back"]),
                    ("Drift [V]", summary["drift"]),
                    ("Pressure [mbar]", summary["pressure"]),
                    ("Time [h]", summary["time"]),
                    ("Chip", summary["chip"]),
                    ("Structure", summary["structure"]),
                ]
                summary_data = "||".join(f"{k}::{v}" for k, v in summary_rows)
                summary_html = "".join(
                    [
                        '<table class="figure-summary"><tbody>',
                        "".join(
                            [
                                (
                                    "<tr>"
                                    f"<th>{escape(k)}</th>"
                                    f"<td>{escape(str(v))}</td>"
                                    "</tr>"
                                )
                                for k, v in summary_rows
                            ]
                        ),
                        "</tbody></table>",
                    ]
                )
            else:
                summary_html = f"<strong>{escape(label)}</strong>"
            cards.append(
                "".join(
                    [
                        '<article class="figure-card">',
                        (
                            f'<a class="figure-open" href="{escape(image_url)}" '
                            f'data-full="{escape(image_url)}" '
                            f'data-caption="{escape(caption)}" '
                            f'data-summary="{escape(summary_data)}">'
                        ),
                        f'<img src="{escape(thumb_url)}" loading="lazy" alt="{escape(label)}" />',
                        "</a>",
                        summary_html,
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
                numeric_pages,
                f'<div class="pager-links">Per page: {per_page_links}</div>',
                '</div>',
            ]
        )
        return (
            "<h3>Images</h3>"
            + pager_html
            + '<div class="fig-grid">'
            + "".join(cards)
            + "</div>"
            + pager_html
        )

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
    """Create the app instance for the given results root."""

    return BrowserWebApp(results_dir).create()


def main() -> None:
    """CLI entrypoint for starting the web server."""

    parser = argparse.ArgumentParser(
        prog="mugpd-web",
        description="Run the muGPD HTML browser for analysis results.",
    )
    parser.add_argument(
        "--results",
        default=str(ANALYSIS_RESULTS),
        help="Results directory containing analysis_run.yaml files.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host interface for the web server.")
    parser.add_argument("--port", type=int, default=7860, help="Port for the web server.")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode.")
    args = parser.parse_args()

    results_dir = Path(args.results)
    if not results_dir.exists():
        raise FileNotFoundError(f"Results directory does not exist: {results_dir}")

    app = create_app(results_dir)
    app.run(host=args.host, port=args.port, debug=args.debug)
