from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from uncertainties import ufloat

try:
    from analysis import ANALYSIS_RESULTS
    from analysis.fileio import AnalysisIndex, AnalysisRun
except ImportError:
    from . import ANALYSIS_RESULTS
    from .fileio import AnalysisIndex, AnalysisRun


class BrowserApp:
    """Streamlit application for browsing detector analysis runs."""

    def __init__(self) -> None:
        self.results_root: Path | None = None
        self.index: AnalysisIndex | None = None
        self.selected_run: AnalysisRun | None = None

    @staticmethod
    @st.cache_resource(show_spinner=False)
    def _cached_index(results_dir_str: str) -> AnalysisIndex:
        """Build and cache analysis index for a results directory."""
        index = AnalysisIndex(Path(results_dir_str))
        index.build()
        return index

    @staticmethod
    @st.cache_resource(show_spinner=False)
    def _cached_run(manifest_path_str: str) -> AnalysisRun:
        """Load and cache a selected run manifest."""
        return AnalysisRun(Path(manifest_path_str))

    @staticmethod
    def _clear_caches() -> None:
        """Clear application-level caches."""
        BrowserApp._cached_index.clear()
        BrowserApp._cached_run.clear()

    @staticmethod
    def _safe_key(*parts: Any) -> str:
        """Build stable Streamlit widget keys from arbitrary values."""
        normalized = [str(p).replace(" ", "_") for p in parts]
        return "::".join(normalized)

    @staticmethod
    def _is_uvalue_dict(value: Any) -> bool:
        return isinstance(value, dict) and "val" in value and "err" in value and len(value) >= 2

    @staticmethod
    def _format_uvalue(value: dict[str, Any]) -> str:
        """Format {val, err} as val +- err."""
        try:
            val = float(value["val"])
            err = float(value["err"])
            if err == 0:
                return f"{val:.6g}"
            u = ufloat(val, err)
            ufstr = str(u)
            if "+/-" in ufstr:
                return ufstr.replace("+/-", " +- ")
            return f"{u.nominal_value:.6g} +- {u.std_dev:.2g}"
        except (TypeError, ValueError, KeyError):
            return str(value)

    @staticmethod
    def _format_scalar(value: Any) -> str:
        if BrowserApp._is_uvalue_dict(value):
            return BrowserApp._format_uvalue(value)
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

    @staticmethod
    def _get_task_config(run_data: dict[str, Any], task_name: str) -> dict[str, Any]:
        pipeline = run_data.get("config", {}).get("pipeline", [])
        for task_cfg in pipeline:
            if task_cfg.get("task") == task_name:
                return task_cfg
        return {}

    @staticmethod
    def _extract_xy_from_config(
        payload: dict[str, Any],
        task_name: str,
        run_data: dict[str, Any],
    ) -> tuple[str | None, Any, str | None, Any]:
        task_cfg = BrowserApp._get_task_config(run_data, task_name)
        xaxis = task_cfg.get("xaxis", "back").lower()
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

        x_val = payload.get(x_key) if x_key else None
        y_val = payload.get(y_key) if y_key else None
        return x_key, x_val, y_key, y_val

    @staticmethod
    def _build_xy_dataframe(x_key: str | None, x_val: Any, y_key: str | None,
                            y_val: Any) -> pd.DataFrame:
        x_label = x_key or "x"
        y_label = y_key or "y"
        x_list = x_val if isinstance(x_val, list) else []
        y_list = y_val if isinstance(y_val, list) else []
        n_rows = max(len(x_list), len(y_list))
        rows = []
        for idx in range(n_rows):
            xv = BrowserApp._format_scalar(x_list[idx]) if idx < len(x_list) else ""
            yv = BrowserApp._format_scalar(y_list[idx]) if idx < len(y_list) else ""
            rows.append({x_label: xv, y_label: yv})
        return pd.DataFrame(rows)

    @staticmethod
    def _flatten_dict_rows(prefix: str, value: Any, rows: list[dict[str, str]]) -> None:
        if value is None:
            return
        if BrowserApp._is_uvalue_dict(value):
            rows.append({"field": prefix, "value": BrowserApp._format_uvalue(value)})
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                nested_prefix = f"{prefix}.{key}" if prefix else str(key)
                BrowserApp._flatten_dict_rows(nested_prefix, nested, rows)
            return
        if isinstance(value, list):
            return
        rows.append({"field": prefix, "value": BrowserApp._format_scalar(value)})

    @staticmethod
    def _get_source_metadata(run_data: dict[str, Any], source_key: str,
                             folder_name: str | None = None) -> dict[str, Any]:
        mode = run_data.get("run", {}).get("mode", "single")
        if mode == "folders" and folder_name:
            folder_payload = run_data.get("folders", {}).get(folder_name, {})
            return folder_payload.get("sources", {}).get(source_key, {})
        return run_data.get("sources", {}).get(source_key, {})

    @staticmethod
    def _figure_candidates_for_task(
        run_data: dict[str, Any],
        task_name: str,
        target_name: str,
        folder_name: str | None = None,
        figures: list[dict[str, Any]] | None = None,
    ) -> list[tuple[Path, str]]:
        """Collect task figure candidates with folder-aware fallback to global figures."""
        if figures is None:
            figures = run_data.get("artifacts", {}).get("figures", [])
        task_lower = task_name.lower()
        target_lower = target_name.lower()

        folder_targeted: list[tuple[Path, str]] = []
        global_targeted: list[tuple[Path, str]] = []
        folder_generic: list[tuple[Path, str]] = []
        global_generic: list[tuple[Path, str]] = []

        for fig in figures:
            fig_name = fig.get("name", "")
            fig_file = fig.get("file", "")
            if not fig_file:
                continue
            text = f"{fig_name} {Path(fig_file).stem}".lower()
            if task_lower not in text:
                continue

            fig_folder = fig.get("folder")
            if folder_name is None:
                is_folder_match = True
            else:
                is_folder_match = fig_folder == folder_name
                if not is_folder_match and fig_folder is None:
                    parts = Path(fig_file).parts
                    is_folder_match = bool(parts) and parts[0] == folder_name

            candidate = (Path(fig_file), fig_name or Path(fig_file).name)
            is_targeted = target_lower in text

            if folder_name is None:
                if is_targeted:
                    folder_targeted.append(candidate)
                else:
                    folder_generic.append(candidate)
                continue

            if is_folder_match:
                if is_targeted:
                    folder_targeted.append(candidate)
                else:
                    folder_generic.append(candidate)
            else:
                if is_targeted:
                    global_targeted.append(candidate)
                else:
                    global_generic.append(candidate)

        ordered = folder_targeted + global_targeted + folder_generic + global_generic
        unique: list[tuple[Path, str]] = []
        seen: set[str] = set()
        for path, name in ordered:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            unique.append((path, name))
        return unique

    @staticmethod
    def _fit_for_figure(run_data: dict[str, Any], fig: dict[str, Any]) -> dict[str, Any]:
        fig_file = fig.get("file", "")
        source_key = Path(fig_file).stem
        mode = run_data.get("run", {}).get("mode", "single")
        if mode == "folders":
            folder_name = fig.get("folder")
            if folder_name is None and "/" in fig_file:
                folder_name = Path(fig_file).parts[0]
            if folder_name is None:
                return {}
            folder_payload = run_data.get("folders", {}).get(folder_name, {})
            return folder_payload.get("fit", {}).get(source_key, {})
        return run_data.get("fit", {}).get(source_key, {})

    @staticmethod
    def _is_spectrum_figure(run_data: dict[str, Any], fig: dict[str, Any]) -> bool:
        """Return True only when figure maps to a real source spectrum entry."""
        fig_file = fig.get("file", "")
        if not fig_file:
            return False
        source_key = Path(fig_file).stem
        mode = run_data.get("run", {}).get("mode", "single")
        if mode == "folders":
            folder_name = fig.get("folder")
            if folder_name is None and "/" in fig_file:
                folder_name = Path(fig_file).parts[0]
            if folder_name is None:
                return False
            folder_payload = run_data.get("folders", {}).get(folder_name, {})
            return source_key in folder_payload.get("sources", {})
        return source_key in run_data.get("sources", {})

    def _render_run_metadata_table(self, run: AnalysisRun) -> None:
        dates = run.acquisition_dates()
        wafers = run.wafers()
        structures = run.structures()
        rows = [
            {"field": "Analysis run", "value": run.run_id},
            {"field": "Analyzed", "value": run.created_at or "Unknown"},
            {"field": "Mode", "value": run.mode},
            {
                "field": "Acquisition date(s)",
                "value": ", ".join(dates) if dates else "N/A",
            },
            {"field": "Wafer(s)", "value": ", ".join(wafers) if wafers else "N/A"},
            {
                "field": "Structure(s)",
                "value": ", ".join(structures) if structures else "N/A",
            },
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    def _render_spectrum_metadata_table(self, run_data: dict[str, Any], source_key: str,
                                        folder_name: str | None = None) -> None:
        src_meta = self._get_source_metadata(run_data, source_key, folder_name)
        rows = []
        for key in ["date", "wafer", "structure", "voltage", "drift_voltage", "pressure"]:
            value = src_meta.get(key)
            if value is not None and value != "Unknown":
                rows.append({"field": key, "value": self._format_scalar(value)})
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    def _render_model(self, model: dict[str, Any]) -> None:
        if not isinstance(model, dict):
            return
        st.write(f"Model: {model.get('name', 'unknown')}")
        chisq = model.get("chisq")
        dof = model.get("dof")
        if chisq is not None or dof is not None:
            st.write(f"chi2: {self._format_scalar(chisq)}    dof: {self._format_scalar(dof)}")

    def _render_fit_results(self, fit_payload: dict[str, Any]) -> None:
        if not fit_payload:
            st.info("No fit results available for this spectrum.")
            return
        for target_name, target_data in fit_payload.items():
            st.write(f"Target: {target_name}")
            summary_rows = []
            for key, value in target_data.items():
                if key in {"model", "voltage", "energy"} or value is None:
                    continue
                summary_rows.append({"quantity": key, "value": self._format_scalar(value)})
            if summary_rows:
                st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
            if target_data.get("model") is not None:
                self._render_model(target_data["model"])

    def _render_spectrum_section(self, run: AnalysisRun) -> None:
        figures = run.data.get("artifacts", {}).get("figures", [])
        if not figures:
            st.info("No figures listed in artifacts.")
            return

        available_entries: list[dict[str, Any]] = []
        for fig in figures:
            fig_file = fig.get("file")
            if not fig_file:
                continue
            if not self._is_spectrum_figure(run.data, fig):
                continue
            img_path = run.manifest_path.parent / fig_file
            if not (img_path.exists() and img_path.suffix.lower() in {".png", ".jpg", ".jpeg"}):
                continue
            available_entries.append(
                {
                    "fig": fig,
                    "img_path": img_path,
                    "source_key": Path(fig_file).stem,
                    "folder_name": fig.get("folder"),
                    "label": fig.get("name", Path(fig_file).stem),
                }
            )

        if not available_entries:
            st.info("No spectrum figures with associated fit payload were found.")
            return

        with st.expander("Spectrum plots and fit results", expanded=False):
            render_mode = st.radio(
                "Spectrum view",
                options=["Single", "All"],
                horizontal=True,
                key=self._safe_key("spectrum-view", run.run_id),
            )
            if render_mode == "Single":
                selected_label = st.selectbox(
                    "Select spectrum",
                    [entry["label"] for entry in available_entries],
                    key=self._safe_key("spectrum-select", run.run_id),
                )
                entries = [entry for entry in available_entries
                           if entry["label"] == selected_label][:1]
            else:
                entries = available_entries

            for entry in entries:
                fig = entry["fig"]
                img_path = entry["img_path"]
                fit_payload = self._fit_for_figure(run.data, fig)
                if not fit_payload:
                    continue
                source_key = entry["source_key"]
                folder_name = entry["folder_name"]
                spectrum_label = entry["label"]
                with st.expander(f"Spectrum: {spectrum_label}", expanded=False):
                    col_plot, col_info = st.columns([1, 1])
                    with col_plot:
                        st.image(str(img_path), caption=fig.get("name", img_path.name))
                    with col_info:
                        self._render_spectrum_metadata_table(run.data, source_key, folder_name)
                    with st.expander("Fit results", expanded=True):
                        self._render_fit_results(fit_payload)
                st.divider()

    def _render_task_payload(
        self,
        task_name: str,
        target_name: str,
        payload: dict[str, Any],
        run_data: dict[str, Any],
        folder_name: str | None,
        manifest_base_path: Path,
        figure_candidates: list[tuple[Path, str]],
    ) -> None:
        st.write(f"Target: {target_name}")

        fig_path, fig_name = (None, None)
        if figure_candidates:
            option_labels = [name for _, name in figure_candidates]
            select_key = self._safe_key("fig", folder_name or "root", task_name, target_name)
            selected_label = st.selectbox("Figure", options=option_labels, index=0, key=select_key)
            fig_path, fig_name = figure_candidates[option_labels.index(selected_label)]

        col_left, col_right = st.columns([1, 1]) if fig_path is not None else (st.container(),
                                                                               None)
        with col_left:
            x_key, x_val, y_key, y_val = self._extract_xy_from_config(payload, task_name, run_data)
            if (x_val is not None and isinstance(x_val, list)) or (y_val is not None and
                                                                   isinstance(y_val, list)):
                xy_df = self._build_xy_dataframe(x_key, x_val, y_key, y_val)
                if not xy_df.empty:
                    st.dataframe(xy_df, use_container_width=True, hide_index=True)

            extra_rows: list[dict[str, str]] = []
            for key, value in payload.items():
                if key in {x_key, y_key, "model"}:
                    continue
                self._flatten_dict_rows(key, value, extra_rows)
            if extra_rows:
                st.dataframe(pd.DataFrame(extra_rows), use_container_width=True, hide_index=True)

            if payload.get("model") is not None:
                self._render_model(payload["model"])

        if col_right is not None and fig_path is not None:
            img_path = manifest_base_path.parent / fig_path
            if img_path.exists():
                with col_right:
                    st.image(str(img_path), caption=fig_name or fig_path.name)

    def _render_task_group(
        self,
        tasks_payload: dict[str, Any],
        title: str,
        run_data: dict[str, Any],
        folder_name: str | None,
        manifest_base_path: Path,
    ) -> None:
        if not tasks_payload:
            return

        with st.expander(title, expanded=True):
            task_names = list(tasks_payload.keys())
            figures = run_data.get("artifacts", {}).get("figures", [])
            task_mode = st.radio(
                "Task view",
                options=["Single", "All"],
                horizontal=True,
                key=self._safe_key("task-view", title),
            )
            if task_mode == "Single" and task_names:
                selected_task = st.selectbox(
                    "Select task",
                    task_names,
                    key=self._safe_key("task-select", title),
                )
                task_names = [selected_task]

            for task_name in task_names:
                task_targets = tasks_payload.get(task_name, {})
                with st.expander(f"Task: {task_name}", expanded=False):
                    if not isinstance(task_targets, dict):
                        st.write(self._format_scalar(task_targets))
                        continue

                    target_names = list(task_targets.keys())
                    target_mode = st.radio(
                        "Target view",
                        options=["Single", "All"],
                        horizontal=True,
                        key=self._safe_key("target-view", title, task_name),
                    )
                    if target_mode == "Single" and target_names:
                        selected_target = st.selectbox(
                            "Select target",
                            target_names,
                            key=self._safe_key("target-select", title, task_name),
                        )
                        target_names = [selected_target]

                    for target_name in target_names:
                        payload = task_targets[target_name]
                        if not isinstance(payload, dict):
                            st.write(f"Target: {target_name}")
                            st.write(self._format_scalar(payload))
                            continue
                        figure_candidates = self._figure_candidates_for_task(
                            run_data,
                            task_name,
                            target_name,
                            folder_name,
                            figures=figures,
                        )
                        self._render_task_payload(
                            task_name,
                            target_name,
                            payload,
                            run_data,
                            folder_name,
                            manifest_base_path,
                            figure_candidates,
                        )
                        st.divider()

    def _render_sidebar(self, available: dict[str, list[str]]
                        ) -> tuple[list[str], list[str], list[str]]:
        selected_dates = st.sidebar.multiselect(
            "Acquisition date",
            options=available["acquisition_dates"],
            default=available["acquisition_dates"],
        )
        selected_wafers = st.sidebar.multiselect(
            "Wafer",
            options=available["wafers"],
            default=available["wafers"],
        )
        selected_structures = st.sidebar.multiselect(
            "Structure",
            options=available["structures"],
            default=available["structures"],
        )
        if st.sidebar.button("Refresh cache"):
            self._clear_caches()
            st.rerun()
        return selected_dates, selected_wafers, selected_structures

    def _render_run_selector(self, table: pd.DataFrame) -> AnalysisRun:
        st.dataframe(table, use_container_width=True, hide_index=True)
        run_options = table["run_id"].tolist()
        selected_run_id = st.selectbox("Select run", run_options)
        selected_row = table.loc[table["run_id"] == selected_run_id].iloc[0]
        return self._cached_run(str(selected_row["manifest_path"]))

    def _render_selected_run(self, run: AnalysisRun) -> None:
        st.subheader("Run information")
        self._render_run_metadata_table(run)
        st.divider()
        self._render_spectrum_section(run)

        if run.mode == "folders":
            for folder_name, folder_payload in run.data.get("folders", {}).items():
                self._render_task_group(
                    tasks_payload=folder_payload.get("tasks", {}),
                    title=f"Task results - folder: {folder_name}",
                    run_data=run.data,
                    folder_name=folder_name,
                    manifest_base_path=run.manifest_path,
                )
            self._render_task_group(
                tasks_payload=run.data.get("folder_tasks", {}),
                title="Folder-level task results",
                run_data=run.data,
                folder_name=None,
                manifest_base_path=run.manifest_path,
            )
            return

        self._render_task_group(
            tasks_payload=run.data.get("tasks", {}),
            title="Task results",
            run_data=run.data,
            folder_name=None,
            manifest_base_path=run.manifest_path,
        )

    def run(self) -> None:
        st.set_page_config(page_title="Detector Analysis Hub", layout="wide")
        st.title("Detector Analysis Browser")

        results_root_default = str(ANALYSIS_RESULTS)
        results_root_text = st.sidebar.text_input("Results directory", value=results_root_default)
        self.results_root = Path(results_root_text)

        if not self.results_root.exists():
            st.error(f"Results directory does not exist: {self.results_root}")
            st.stop()

        self.index = self._cached_index(str(self.results_root))
        if not self.index.records:
            st.warning("No analysis manifests found. Run the analysis with save enabled first.")
            st.stop()

        available = self.index.available_values()
        selected_dates, selected_wafers, selected_structures = self._render_sidebar(available)

        filtered_records = self.index.filter(
            acquisition_dates=selected_dates,
            wafers=selected_wafers,
            structures=selected_structures,
        )
        rows = AnalysisIndex.records_to_rows(filtered_records)
        table = pd.DataFrame(rows)

        st.subheader(f"Found {len(filtered_records)} analyses")
        if table.empty:
            st.info("No analyses match the current filters.")
            st.stop()

        self.selected_run = self._render_run_selector(table)
        self._render_selected_run(self.selected_run)


if __name__ == "__main__":
    BrowserApp().run()
