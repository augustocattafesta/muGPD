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
from .page_template import render_home_page

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
        search_query = request.args.get("q", "").strip()

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
                q=search_query or None,
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

        if search_query:
            query_norm = search_query.lower()
            rows = [
                row
                for row in rows
                if query_norm in " ".join(
                    [
                        row["run_id"],
                        row["created"],
                        row["dates"],
                        row["wafers"],
                        row["structures"],
                    ]
                ).lower()
            ]

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
            search_query=search_query,
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
        search_query: str,
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
                + (f"&q={escape(search_query)}" if search_query else "")
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
                    '<td class="col-run"><a href="',
                    escape(row["details_url"]),
                    '">',
                    escape(row["run_id"]),
                    "</a></td>",
                    f"<td class=\"col-created\">{escape(row['created'])}</td>",
                    f"<td class=\"col-dates\">{escape(row['dates'])}</td>",
                    f"<td class=\"col-wafers\">{escape(row['wafers'])}</td>",
                    f"<td class=\"col-structures\">{escape(row['structures'])}</td>",
                    "</tr>",
                ]
            )
            for row in runs_table_rows
        ]
        if rows_html:
            table_html = (
                '<div class="runs-table-wrap"><table class="runs-table"><thead><tr>'
                f"<th class=\"col-run\">{sort_header_link('run_id', 'Run')}</th>"
                f"<th class=\"col-created\">{sort_header_link('created', 'Created')}</th>"
                f"<th class=\"col-dates\">{sort_header_link('dates', 'Acquisition date(s)')}</th>"
                f"<th class=\"col-wafers\">{sort_header_link('wafers', 'Wafer(s)')}</th>"
                + (
                    f"<th class=\"col-structures\">"
                    f"{sort_header_link('structures', 'Structure(s)')}</th>"
                )
                + "</tr></thead><tbody>"
                + "".join(rows_html)
                + "</tbody></table></div>"
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
                "q": search_query or None,
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

        return render_home_page(
            date_options=date_options,
            wafer_options=wafer_options,
            structure_options=structure_options,
            search_query=search_query,
            sort_by=sort_state.by,
            sort_dir=sort_state.direction,
            n_runs=n_runs,
            run_pager=run_pager,
            table_html=table_html,
            run_html=run_html,
        )

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

    def _collect_available_figures(self, run: AnalysisRun) -> list[dict[str, Any]]:
        figures = run.data.get("artifacts", {}).get("figures", [])
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
        return available_figures

    @staticmethod
    def _build_figure_summary(summary: dict[str, str]) -> tuple[str, str]:
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
        return summary_html, summary_data

    def _render_figure_card(self, item: dict[str, Any], run: AnalysisRun) -> str:
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

        if item.get("show_summary"):
            summary = cast(dict[str, str], item.get("summary"))
            summary_html, summary_data = self._build_figure_summary(summary)
        else:
            summary_html = f"<strong>{escape(label)}</strong>"
            summary_data = ""

        return "".join(
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

    def _render_figures(self, run: AnalysisRun, img_page: int, img_per_page: int) -> str:
        available_figures = self._collect_available_figures(run)

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

        cards = [self._render_figure_card(item, run) for item in page_figures]

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
