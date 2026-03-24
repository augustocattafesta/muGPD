import datetime
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from aptapy import modeling, models, plotting
from uncertainties import UFloat

from ._logger import log
from .config import AppConfig
from .fileio import PulsatorFile, SourceFile


@dataclass
class TargetContext:
    """Container class for target-specific analysis context information. This class holds the
    results of the spectral analysis for a specific target (line) in a source file. 

    Attributes
    ----------
    target : str
        The name of the target line being analyzed.
    line_val : UFloat
        The fitted line position value.
    sigma : UFloat
        The fitted line sigma value.
    voltage : float
        The voltage at which the measurement was taken.
    model : modeling.AbstractFitModel
        The fit model used for the analysis.
    """
    target: str
    line_val: UFloat
    sigma: UFloat
    voltage: float
    model: modeling.AbstractFitModel

    # Internal attributes for storing computed values and labels
    _gain_val: UFloat | None = field(default=None, init=False, repr=False)
    _gain_label: str = field(default="", init=False, repr=False)

    _fwhm_val: UFloat | None = field(default=None, init=False, repr=False)
    _fwhm_label : str = field(default="", init=False, repr=False)

    _res_val: UFloat | None = field(default=None, init=False, repr=False)
    _res_label: str = field(default="", init=False, repr=False)

    _res_escape_val: UFloat | None = field(default=None, init=False, repr=False)
    _res_escape_label: str | None = field(default=None, init=False, repr=False)

    _time_from_start: float | None = field(default=None, init=False, repr=False)
    _gain_trend_val: UFloat | None = field(default=None, init=False, repr=False)
    _gain_trend_label: str = field(default="", init=False, repr=False)

    # Default energy for resolution labels
    _energy: float = field(default=5.9, init=False, repr=False)

    @property
    def fwhm_val(self) -> UFloat:
        """The fwhm value computed in the resolution analysis task.
        """
        if self._fwhm_val is None:
            raise AttributeError("FWHM value has not been set yet.")
        return self._fwhm_val

    @fwhm_val.setter
    def fwhm_val(self, value: UFloat):
        self._fwhm_val = value
        self._fwhm_label = f"FWHM@{self._energy:.1f} keV: {value} fC"

    @property
    def gain_val(self) -> UFloat:
        """The gain value computed in the gain analysis task.
        """
        if self._gain_val is None:
            raise AttributeError("Gain value has not been set yet.")
        return self._gain_val

    @gain_val.setter
    def gain_val(self, value: UFloat):
        self._gain_val = value
        # Set the gain label for the spectral plot
        self._gain_label = f"Gain@{self.voltage:.0f} V: {self.gain_val}"

    @property
    def res_val(self) -> UFloat:
        """The resolution value computed in the resolution analysis task.
        """
        if self._res_val is None:
            raise AttributeError("Resolution value has not been set yet.")
        return self._res_val

    @res_val.setter
    def res_val(self, value: UFloat):
        self._res_val = value
        # Set the fwhm and resolution labels for the spectral plot
        self._res_label = fr"$\frac{{\Delta E}}{{E}}$: {self.res_val:.1f} % FWHM"

    @property
    def res_escape_val(self) -> UFloat:
        """The resolution (escape) value computed in the resolution analysis task.
        """
        if self._res_escape_val is None:
            raise AttributeError("Resolution (escape) value has not been set yet.")
        return self._res_escape_val

    @res_escape_val.setter
    def res_escape_val(self, value: UFloat):
        self._res_escape_val = value
        # Set the resolution (escape) label for the spectral plot
        self._res_escape_label = fr"$\frac{{\Delta E}}{{E}}$(esc.): {self.res_escape_val} % FWHM"

    @property
    def time_from_start(self) -> float:
        """The time from the start of the measurement in hours.
        """
        if self._time_from_start is None:
            raise AttributeError("Time from start has not been set yet.")
        return self._time_from_start

    @time_from_start.setter
    def time_from_start(self, value: float):
        self._time_from_start = value

    @property
    def gain_trend_val(self) -> UFloat:
        """The gain trend value computed in the gain trend analysis task.
        """
        if self._gain_trend_val is None:
            raise AttributeError("Gain trend value has not been set yet.")
        return self._gain_trend_val

    @gain_trend_val.setter
    def gain_trend_val(self, value: UFloat):
        self._gain_trend_val = value
        # Set the gain trend label for the spectral plot
        self._gain_trend_label = f"Gain@{self.time_from_start:.2g} h: {self.gain_trend_val}"

    @property
    def energy(self) -> float:
        """The energy value used for resolution labels.
        """
        return self._energy

    @energy.setter
    def energy(self, value: float):
        self._energy = value

    def task_label(self, task: str) -> str | None:
        """Retrieve the label string for the specified analysis task.

        Arguments
        ----------
        task : str
            The analysis task for which to retrieve the label.
        
        Returns
        -------
        label : str
            The label string corresponding to the specified task.
        """
        label_mapping = {
            "fwhm": self._fwhm_label,
            "gain": self._gain_label,
            "resolution": self._res_label,
            "resolution_escape": self._res_escape_label
        }
        try:
            return label_mapping[task]
        except KeyError:
            raise ValueError(f"Unknown task '{task}' for label retrieval.") from None

    def target_context_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the target context, specifically for the analysis
        results file.
        
        Returns
        -------
        dict[str, Any]
            A dictionary containing the target context information for serialization in the results
            file.
        """
        return {
            "target": self.target, "line_val": self.line_val, "sigma": self.sigma,
            "voltage": self.voltage, "energy": self.energy, "gain": self._gain_val,
            "fwhm": self._fwhm_val, "resolution": self._res_val,
            "resolution_escape": self._res_escape_val, "time_from_start": self._time_from_start,
            "gain_trend": self._gain_trend_val, "model": self.model,}


@dataclass
class ContextBase:
    config: AppConfig
    paths: list[Path] = field(default_factory=list, init=False, repr=True)

    # Internal attributes for storing results and figures
    _results: dict = field(default_factory=dict, init=False, repr=False)
    _figures: dict = field(default_factory=dict, init=False, repr=False)
    _run_metadata: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def data_to_yaml(self, data: Any) -> Any:
        """Convert the results dictionary to a YAML-serializable format.

        Parameters
        ----------
        data : Any
            The data to convert.
        """
        out = data
        # If it is a dictionary, process each key/value pair
        if isinstance(data, dict):
            out = {k: self.data_to_yaml(v) for k, v in data.items()}
        # If it is a fit model, extract relevant information
        elif isinstance(data, (modeling.AbstractFitModel, modeling.FitModelSum)):
            # Extract parameters and their values/errors
            pars_dict = {}
            for par in data:
                pars_dict[par.name] = {"val": par.value, "err": par.error}
            # Return the fit model information (name, chisquare, dof, parameters)
            out = {
                "name": data.name(),
                "chisq": float(data.status.chisquare),
                "dof": int(data.status.dof),
                "pars": pars_dict}
        # If it is a list/tuple, process each element
        elif isinstance(data, (list, tuple)):
            out = [self.data_to_yaml(x) for x in data]
        # If it is a numpy array, convert to list and process elements
        elif isinstance(data, np.ndarray):
            out = [self.data_to_yaml(x) for x in data.tolist()]
        # Normalize common non-JSON scalar types
        elif isinstance(data, Path):
            out = str(data)
        elif isinstance(data, (datetime.datetime, datetime.date)):
            out = data.isoformat()
        # If it is a ufloat (has nominal_value attribute), extract value and uncertainty
        elif hasattr(data, "nominal_value"):
            out = {
                "val": float(data.nominal_value),
                "err": float(data.std_dev),
            }
        return out

    def add_figure(self, figure_name: str, figure: Any) -> None:
        """Add a figure to the private `figures` dictionary.
        
        Arguments
        ---------
        figure_name : str
            The name of the figure.
        figure : Any
            The figure object.
        """
        self._figures[figure_name] = figure

    def update_run_metadata(self, **kwargs: Any) -> None:
        """Update the run metadata with the provided key-value pairs.
        
        This metadata can include information such as input paths, configuration path, path type,
        and any other relevant information about the analysis run that should be included in the
        analysis output file.
        """
        self._run_metadata.update(kwargs)

    @property
    def figures_items(self) -> Iterable[tuple[str, Any]]:
        """Return an iterable of figure name and figure object pairs from the private `figures`
        dictionary.
        """
        return self._figures.items()

    def _output_dir(self, output_dir: Path) -> Path:
        """Return the output directory for the current context save call.
        """
        raise NotImplementedError

    def _save_figures(self, folder_dir: Path, fig_format: str) -> list[dict[str, Any]]:
        """Save figures and return output results files entries.
        """
        raise NotImplementedError

    def _build_analysis_results(self, folder_dir: Path, fig_format: str,
                            figures_results_entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the run output results file.
        """
        raise NotImplementedError

    def _write_results_file(self, folder_dir: Path, run_manifest: dict[str, Any]) -> None:
        """Write the analysis results file to disk.
        """
        run_path = folder_dir / "analysis_run.yaml"
        with open(run_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.data_to_yaml(run_manifest), f,
                           sort_keys=False, default_flow_style=False)

    def _write_config_snapshot(self, folder_dir: Path) -> Path:
        """Write a reusable copy of the in-memory AppConfig used for this run."""
        config_snapshot_path = folder_dir / "config.yaml"
        self.config.to_yaml(config_snapshot_path)
        return config_snapshot_path

    def save(self, output_dir: Path, fig_format: str) -> None:
        """Save the context configuration, figures, and results to the specified output
        directory.

        Parameters
        ----------
        output_dir : Path
            The directory where to save the context data.
        fig_format : str
            The format to save figures (e.g., 'png', 'pdf').
        """
        log.info("Saving analysis results")
        folder_dir = self._output_dir(output_dir)
        folder_dir.mkdir(parents=True, exist_ok=True)
        log.info("Saving configuration snapshot")
        self._write_config_snapshot(folder_dir)
        log.info("Saving figures")
        figures_results_entries = self._save_figures(folder_dir, fig_format)
        log.info("Building analysis results file and saving to disk")
        output_results = self._build_analysis_results(folder_dir, fig_format,
                                                    figures_results_entries)
        self._write_results_file(folder_dir, output_results)
        log.success(f"Analysis results saved to {folder_dir}")


@dataclass
class Context(ContextBase):
    """Container class for analysis context information. This class holds the analysis
    configuration and all the data generated during the analysis pipeline. This class gets
    continually updated during the analysis.
    
    Attributes
    ----------
    config : AppConfig
        The application configuration object.
    """
    # Internal attributes for storing calibration, source files, fit results, and figures
    _calibration: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _sources: dict[str, SourceFile] = field(default_factory=dict, init=False, repr=False)
    _fit: dict = field(default_factory=dict, init=False, repr=False)

    @staticmethod
    def _normalize_file_key(file_name: str) -> str:
        """Return the canonical dictionary key for source/fit entries."""
        return Path(file_name).stem

    @property
    def pulse(self) -> PulsatorFile:
        """The PulsatorFile object obtained from the calibration pulse file."""
        _pulse = self._calibration.get("pulse")
        if _pulse is None:
            raise AttributeError("Pulse file has not been set in the context.")
        return _pulse

    @pulse.setter
    def pulse(self, value):
        if not isinstance(value, PulsatorFile):
            raise TypeError("Pulse must be an instance of PulsatorFile")
        self._calibration["pulse"] = value

    @property
    def conversion_model(self) -> models.Line:
        """The calibration conversion model to use for charge calibration of the spectral data."""
        model = self._calibration.get("model")
        if model is None:
            raise AttributeError("Calibration model has not been set in the context.")
        if not isinstance(model, models.Line):
            raise TypeError("Conversion model in context is not an instance of aptapy.models.Line")
        return model

    @conversion_model.setter
    def conversion_model(self, value):
        if not isinstance(value, models.Line):
            raise TypeError("Conversion model must be an instance of aptapy.models.Line")
        self._calibration["model"] = value

    def add_source(self, source: SourceFile) -> None:
        """Add a source file to the private `sources` dictionary."""
        if not isinstance(source, SourceFile):
            raise TypeError("Source must be an instance of SourceFile")
        file_name = self._normalize_file_key(source.file_path.stem)
        self._sources[file_name] = source
        # Keep source and fit dictionaries aligned even when no fit subtask runs.
        if file_name not in self._fit:
            self._fit[file_name] = {}

    def source(self, file_name: str) -> SourceFile:
        """Retrieve a source file from the private `sources` dictionary by its file name."""
        file_name = self._normalize_file_key(file_name)
        if file_name not in self._sources:
            raise KeyError(f"Source file '{file_name}' not found in context.")
        return self._sources[file_name]

    @property
    def last_source(self) -> SourceFile:
        """The last source file added to the private `sources` dictionary."""
        if not self._sources:
            raise AttributeError("No source files have been set in the context.")
        return list(self._sources.values())[-1]

    @property
    def file_names(self) -> list[str]:
        """List of source file names stored in the context."""
        if not self._sources:
            raise AttributeError("No source files have been set in the context.")
        return list(self._sources.keys())

    def add_target_ctx(self, source: SourceFile, target_ctx: TargetContext) -> None:
        """Add a target context for a specific source file to the private `fit` dictionary."""
        if not isinstance(target_ctx, TargetContext):
            raise TypeError("Target context must be an instance of TargetContext")
        if not isinstance(source, SourceFile):
            raise TypeError("Source must be an instance of SourceFile")
        file_name = self._normalize_file_key(source.file_path.stem)
        if file_name not in self._fit:
            self._fit[file_name] = {}
        self._fit[file_name][target_ctx.target] = target_ctx

    def target_ctx(self, file_name: str, target: str) -> TargetContext:
        """Retrieve a target context for a specific source file and target from the private `fit`
        dictionary."""
        file_name = self._normalize_file_key(file_name)
        if file_name not in self._fit:
            raise KeyError(f"File '{file_name}' not found in fit results")
        if target not in self._fit[file_name]:
            raise KeyError(f"Target subtask '{target}' not found in fit results for file" \
                           f" '{file_name}'")
        return self._fit[file_name][target]

    def add_task_results(self, task: str, target: str, results: dict) -> None:
        """Add results for a specific task and target to the private `results` dictionary."""
        if task not in self._results:
            self._results[task] = {}
        if results is None:
            raise ValueError("Results dictionary cannot be None")
        self._results[task][target] = results

    def add_task_fit_model(self, task: str, target: str, model: modeling.AbstractFitModel) -> None:
        """Add the fit model used in a specific task and target to the private `results`
        dictionary."""
        if task not in self._results:
            self._results[task] = {}
        if target not in self._results[task]:
            self._results[task][target] = {}
        self._results[task][target]["model"] = model

    def add_subtask_fit_model(self, task: str, target: str, subtask: str,
                              model: modeling.AbstractFitModel) -> None:
        """Add the fit model used in a specific subtask of a task and target to the private
        `results` dictionary."""
        if task not in self._results:
            self._results[task] = {}
        if target not in self._results[task]:
            self._results[task][target] = {}
        if subtask not in self._results[task][target]:
            self._results[task][target][subtask] = {}
        self._results[task][target][subtask]["model"] = model

    def task_results(self, task: str, target: str) -> dict:
        """Retrieve results for a specific task and target from the private `results`
        dictionary."""
        if task not in self._results:
            raise KeyError(f"Task '{task}' not found in results.")
        if target not in self._results[task]:
            raise KeyError(f"Target '{target}' not found in results for task '{task}'.")
        return self._results[task][target]

    @staticmethod
    def _safe_source_attr(source: SourceFile, attr: str) -> Any:
        """Read source metadata fields, tolerating unsupported naming patterns."""
        try:
            return getattr(source, attr)
        except (ValueError, AttributeError):
            return None

    def _source_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the source files in the context, specifically for
        the analysis results file.
        
        This method extracts relevant metadata from each source file and organizes it in a
        dictionary format suitable for serialization in the results file.
        """
        payload: dict[str, Any] = {}
        for file_name, source in self._sources.items():
            payload[file_name] = {
                "path": source.file_path,
                "voltage": self._safe_source_attr(source, "voltage"),
                "drift_voltage": self._safe_source_attr(source, "drift_voltage"),
                "pressure": self._safe_source_attr(source, "pressure"),
                "start_time": self._safe_source_attr(source, "start_time"),
                "real_time": self._safe_source_attr(source, "real_time"),
                "structure": self._safe_source_attr(source, "structure"),
                "wafer": self._safe_source_attr(source, "wafer"),
                "date": self._safe_source_attr(source, "date"),
            }
        return payload

    def _fit_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the fit results in the context, specifically for
        the analysis results file.

        This method organizes the fit results for each target in a dictionary format suitable for
        serialization in the results file.
        """
        payload: dict[str, Any] = {}
        for file_name, file_fit in self._fit.items():
            payload[file_name] = {}
            for target, target_ctx in file_fit.items():
                payload[file_name][target] = target_ctx.target_context_dict()
        return payload

    def _calibration_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the calibration artifacts used during the run.
        
        This method organizes the calibration information, including the pulse file and the
        conversion model, in a dictionary format suitable for serialization in the results file.
        """
        pulse = self._calibration.get("pulse")
        model = self._calibration.get("model")
        return {
            "pulse_file": pulse.file_path if pulse is not None else None,
            "pulse_voltages": pulse.voltage if pulse is not None else None,
            "model": model,
        }

    def _context_payload(self, include_config: bool = True) -> dict[str, Any]:
        """Build the core payload for a single-context analysis.
        """
        payload = {
            "inputs": {
                "config_path": self._run_metadata.get("config_path"),
                "raw_paths": self._run_metadata.get("input_paths"),
                "resolved_sources": self.paths,
                "path_type": self._run_metadata.get("path_type"),
            },
            "calibration": self._calibration_dict(),
            "sources": self._source_dict(),
            "fit": self._fit_dict(),
            "tasks": self._results,
        }
        if include_config:
            payload["config"] = self.config.model_dump()
        return payload

    def context_payload(self, include_config: bool = True) -> dict[str, Any]:
        """Public wrapper around context payload serialization.
        """
        return self._context_payload(include_config=include_config)

    def _output_dir(self, output_dir: Path) -> Path:
        # Create a unique directory for this run based on timestamp
        for p in self.paths:
            parts = p.parts
            if "data" in parts:
                idx = parts.index("data") + 1
                directory = "/".join(parts[idx:-1])
            else:
                directory = p.parent.name
        time_stamp = datetime.datetime.now().strftime("%y%m%d_%H%M%S")
        dir_name = f"{time_stamp}_files"
        return output_dir / directory / dir_name

    def _save_figures(self, folder_dir: Path, fig_format: str) -> list[dict[str, Any]]:
        figures_manifest: list[dict[str, Any]] = []
        for fig_name, fig in self._figures.items():
            rel_path = Path(f"{fig_name}.{fig_format}")
            fig_path = folder_dir / rel_path
            if isinstance(fig, plotting.plt.Figure):
                fig.savefig(fig_path, format=fig_format)
                figures_manifest.append({"name": fig_name, "file": str(rel_path)})
        return figures_manifest

    def _build_analysis_results(self, folder_dir: Path, fig_format: str,
                            figures_results_entries: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run": {
                "run_id": folder_dir.name,
                "created_at": datetime.datetime.now().isoformat(),
                "mode": "single",
                "fig_format": fig_format,
            },
            **self._context_payload(),
            "artifacts": {
                "figures": figures_results_entries,
            },
        }


@dataclass
class FoldersContext(ContextBase):
    """Container class for folders-specific analysis context information. This class holds the
    analysis configuration and the results from multiple folders tasks.
    
    Attributes
    ----------
    config : AppConfig
        The application configuration object.
    """
    # Internal attributes for storing folder contexts and results
    _folders: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    @property
    def folder_names(self) -> list[str]:
        """List of folder names stored in the context."""
        if not self._folders:
            raise AttributeError("No folders have been set in the context.")
        return list(self._folders.keys())

    def add_folder(self, folder_path: Path, folder_ctx: Context) -> None:
        """Add a folder context to the private `folders` dictionary."""
        if not isinstance(folder_ctx, Context):
            raise TypeError("Folder context must be an instance of Context")
        folder_name = folder_path.stem
        self._folders[folder_name] = folder_ctx

    def folder_ctx(self, folder_name: str) -> Context:
        """Retrieve a folder context from the private `folders` dictionary by its folder name."""
        if folder_name not in self._folders:
            raise KeyError(f"Folder '{folder_name}' not found in context.")
        return self._folders[folder_name]

    def add_task_results(self, task: str, target: str, results: dict) -> None:
        """Add results for a specific task and target to the private `results` dictionary."""
        if task not in self._results:
            self._results[task] = {}
        if results is None:
            raise ValueError("Results dictionary cannot be None")
        self._results[task][target] = results

    def _serialize_folder_context(self, folder_ctx: Context) -> dict[str, Any]:
        """Serialize one folder-level analysis payload."""
        return folder_ctx.context_payload(include_config=False)

    @property
    def results_dir(self) -> Path:
        """The results directory path based on the analysis paths."""
        time_stamp = datetime.datetime.now().strftime("%y%m%d_%H%M%S")
        if len(self.paths) == 1:
            parts = self.paths[0].parts
            if "data" in parts:
                idx = parts.index("data") + 1
                directory = Path("/".join(parts[idx:]))
                directory = directory / f"{time_stamp}_FullFolderAnalysis"
            else:
                directory = self.paths[0].parent / f"{time_stamp}_FullFolderAnalysis"
        else:
            folders_name = "_".join([Path(p).stem for p in self.paths])
            directory = Path(f"{time_stamp}_Folders_{folders_name}")
            directory = Path("MultiFolders") / directory
        return Path(directory)

    def _output_dir(self, output_dir: Path) -> Path:
        return output_dir / self.results_dir

    def _save_figures(self, folder_dir: Path, fig_format: str) -> list[dict[str, Any]]:
        figures_manifest: list[dict[str, Any]] = []
        # Save all figures from each folder context
        for folder_name in self.folder_names:
            folder_ctx = self.folder_ctx(folder_name)
            subfolder_dir = folder_dir
            rel_prefix = Path(".")
            if len(self.folder_names) > 1:
                subfolder_dir = folder_dir / folder_name
                rel_prefix = Path(folder_name)
            if not subfolder_dir.exists():
                subfolder_dir.mkdir(parents=True, exist_ok=True)
            for fig_name, fig in folder_ctx.figures_items:
                rel_path = rel_prefix / f"{fig_name}.{fig_format}"
                fig_path = folder_dir / rel_path
                if isinstance(fig, plotting.plt.Figure):
                    fig.savefig(fig_path, format=fig_format)
                    figures_manifest.append({"name": f"{folder_name}:{fig_name}",
                                             "file": str(rel_path),
                                             "folder": folder_name})
        # Save the folders-wide figures
        for fig_name, fig in self._figures.items():
            rel_path = Path(f"{fig_name}.{fig_format}")
            fig_path = folder_dir / rel_path
            if isinstance(fig, plotting.plt.Figure):
                fig.savefig(fig_path, format=fig_format)
                figures_manifest.append({"name": fig_name, "file": str(rel_path),
                                         "scope": "folders"})
        return figures_manifest

    def _build_analysis_results(self, folder_dir: Path, fig_format: str,
                            figures_results_entries: list[dict[str, Any]]) -> dict[str, Any]:
        folders_payload: dict[str, Any] = {}
        for folder_name in self.folder_names:
            folder_ctx = self.folder_ctx(folder_name)
            folders_payload[folder_name] = self._serialize_folder_context(folder_ctx)
        return {
            "schema_version": 1,
            "run": {
                "run_id": folder_dir.name,
                "created_at": datetime.datetime.now().isoformat(),
                "mode": "folders",
                "fig_format": fig_format,
            },
            "config": self.config.model_dump(),
            "inputs": {
                "config_path": self._run_metadata.get("config_path"),
                "raw_paths": self._run_metadata.get("input_paths"),
                "resolved_folders": self.paths,
                "path_type": self._run_metadata.get("path_type"),
            },
            "folders": folders_payload,
            "folder_tasks": self._results,
            "artifacts": {
                "figures": figures_results_entries,
            },
        }
