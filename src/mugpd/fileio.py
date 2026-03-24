"""Module to handle reading of different types of file and analyze specific type of signals.
"""

import datetime
import inspect
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aptapy.modeling
import numpy as np
import yaml
from aptapy.hist import Histogram1d
from uncertainties import unumpy

from . import ANALYSIS_DATA, ANALYSIS_RESOURCES


class FileBase:
    """Load data from a file and define the path and the histogram.
    """
    def __init__(self, file_path: Path) -> None:
        """Class constructor.

        Arguments
        ----------
        file_path : pathlib.Path
            Path of the file to open.
        """
        self.file_path = file_path
        self.hist = Histogram1d.from_amptek_file(file_path)


class SourceFile(FileBase):
    """Class to analyze a source file and extract relevant quantities from the name of the file.
    """
    def __init__(self, file_path: Path,
                 charge_conv_model: aptapy.modeling.AbstractFitModel | None = None) -> None:
        super().__init__(file_path)
        self.noise_subtracted = False
        if charge_conv_model is not None:
            content = self.hist.content
            # Apply charge conversion to the bin edges
            old_edges = self.hist.bin_edges()
            model_pars = charge_conv_model.parameter_values()
            # Check if the model has the correct number of parameters
            if len(model_pars) != 2:
                raise ValueError("Charge conversion model must have two parameters.")
            slope = model_pars[0]
            offset = model_pars[1]
            new_edges = unumpy.nominal_values(old_edges * slope + offset)
            # Update the histogram with the new edges and same content
            self.hist = Histogram1d(new_edges, xlabel="Charge [fC]")
            self.hist.set_content(content)

    @property
    def voltage(self) -> float:
        """Back voltage of the detector extracted from the file name.
        """
        match = re.search(r"B(\d+)", self.file_path.name)
        if match is not None:
            _voltage = float(match.group(1))
        else:
            raise ValueError("Incorrect file type or different name used.")
        return _voltage

    @property
    def drift_voltage(self) -> float:
        """Drift voltage of the detector extracted from the file name.
        """
        match = re.search(r"D(\d+)", self.file_path.name)
        if match is not None:
            _voltage = float(match.group(1))
        else:
            raise ValueError("Incorrect file type or different name used.")
        return _voltage

    @property
    def real_time(self) -> float:
        """Real integration time of the histogram extracted from the amptek file..
        """
        with open(self.file_path, encoding="UTF-8") as input_file:
            real_time_str = input_file.readlines()[8]
        if real_time_str.split('-')[0].strip() == "REAL_TIME":
            return float(real_time_str.split('-')[1].strip())
        raise ValueError("Not reading REAL_TIME")

    @property
    def start_time(self) -> datetime.datetime:
        """Start time of the acquisition extracted from the amptek file.
        """
        with open(self.file_path, encoding="UTF-8") as input_file:
            start_time_str = input_file.readlines()[9]
        if start_time_str.split('-')[0].strip() == "START_TIME":
            start = datetime.datetime.strptime(start_time_str, "START_TIME - %m/%d/%Y %H:%M:%S\n")
            return start
        raise ValueError("Not reading START_TIME")

    @property
    def pressure(self) -> float:
        """Pressure of the gas in the detector extracted from the file name.
        """
        match = re.search(r"P(\d+)", self.file_path.name)
        if match is not None:
            return float(match.group(1))
        return 0.0

    @property
    def structure(self) -> str:
        """Structure type of the detector extracted from the file name.
        """
        match = re.search(r"_(\d+p\d+[a-zA-Z]*|\d+[Dd])_", self.file_path.name)
        if match is not None:
            value = match.group(1).upper()
            return value.replace("P", ".")
        return "Unknown"

    @property
    def wafer(self) -> str:
        """Wafer type of the detector extracted from the file name.
        """
        match = re.search(r"_([Ww]\d+[a-zA-Z]?)_", self.file_path.name)
        if match is not None:
            return match.group(1).upper()
        return "Unknown"

    @property
    def date(self) -> datetime.date | str:
        """Date of the acquisition extracted from the start time.
        """
        if self.start_time is not None:
            return self.start_time.date()
        return "Unknown"


class PulsatorFile(FileBase):
    """Class to analyze a calibration pulse file.
    """
    @property
    def voltage(self) -> np.ndarray:
        """Voltages of the pulses.
        """
        match = re.search(r"ci([\d_-]+)(?=[^\d_-])", self.file_path.name, re.IGNORECASE)
        if match is not None:
            parts = [n for n in re.split(r"[-_]", match.group(1)) if n]  # <-- filter empty strings
            _voltage = np.array([int(n) for n in parts])
        else:
            raise ValueError("Incorrect file type or different name used.")
        return _voltage

    @property
    def num_pulses(self) -> int:
        """Number of pulses in the spectrum.
        """
        return len(self.voltage)


class Folder:
    def __init__(self, folder_path: Path) -> None:
        """Class constructor.

        Parameters
        ----------
        folder_path : Path
            Path of the folder to open.
        """
        self.folder_path = folder_path
        if not self.folder_path.exists():
            raise FileExistsError(f"Folder {str(self.folder_path)} does not exist.\
                                  Verify the path.")
        self.input_files = list(folder_path.iterdir())

    @property
    def source_files(self) -> list[Path]:
        """Extract the source files from all the files of the directory and return a sorted list
        of the files. If file names contain "trend{i}", the sorting is done numerically according
        to the index {i}, otherwise it's done alphabetically.
        """
        # Keep files containing _B<number>
        filtered_sources = [_f for _f in self.input_files if re.search(r"B\d+", _f.name)]
        noise_sources = [_f for _f in self.input_files if "noise" in _f.name.lower()
                         and _f not in filtered_sources]

        def numeric_sort_key(p: Path):
            """Sort the files with numerical order.
            """
            numbers = [int(x) for x in re.findall(r"\d+", p.stem)]
            return numbers[-1]  # sort by the last number

        return sorted(filtered_sources, key=numeric_sort_key) + sorted(noise_sources)

    @property
    def pulse_file(self) -> Path:
        """Extract the calibration pulse files from all the files of the directory and return
        the path of the first file in the list.
        """
        return [_f for _f in self.input_files if re.search(r"ci([\d\-_]+)",
                                                           _f.name,re.IGNORECASE) is not None][0]


def load_label(key: str) -> str | None:
    """Load a label from the analysis resources labels.yaml file based on the calling function
    name and on the file name.

    Arguments
    ---------
    key : str
        Key of the label to load.
    """
    label_value = None
    yaml_file_path = ANALYSIS_RESOURCES / "labels.yaml"
    try:
        with open(yaml_file_path, encoding="utf-8") as f:
            yaml_file = yaml.safe_load(f)
        functions = yaml_file["function"]
        current_frame = inspect.currentframe()
        if current_frame is not None:
            previous_frame = current_frame.f_back
            if previous_frame is not None:
                label = functions.get(previous_frame.f_code.co_name, None)
                label_value = label[key]
    except (FileNotFoundError, TypeError, KeyError):
        pass
    return label_value


def check_source_paths(paths: Iterable[str | Path]) -> tuple[list[Path], str]:
    """Check if source paths exist and are either all files or all folders.
    
    Parameters
    ----------
    paths : Iterable[str | Path]
        List of paths to check.
    
    Returns
    -------
    checked_paths : tuple[list[Path], str]
        A tuple containing the list of checked paths and a string indicating
        whether they are 'file' or 'folder'.
    """
    # Create a list to hold the checked paths
    checked_paths = []
    # Loop through the paths and check if they exist. If the given path does not exist, check
    # if it exists in the ANALYSIS_DATA folder.
    for p in paths:
        path = Path(p)
        if not path.exists():
            file_path = ANALYSIS_DATA / path
            if not file_path.exists():
                # Raise an error if the path does not exist in either location
                raise FileNotFoundError(f"Data path {p} does not exist.")
            path = file_path
        checked_paths.append(path)
    if not checked_paths:
        raise ValueError("No valid paths provided.")
    # Check if all paths are either files or folders
    is_file = [p.is_file() for p in checked_paths]
    is_folder = [p.is_dir() for p in checked_paths]
    # Return the checked paths and their type
    if all(is_file):
        return checked_paths, "file"
    if all(is_folder):
        return checked_paths, "folder"
    raise ValueError("All source paths must be either files or folders.")


@dataclass(frozen=True)
class AnalysisRecord:
    """Index entry describing a saved analysis run."""
    run_id: str
    mode: str
    manifest_path: Path
    run_directory: Path
    created_at: str | None
    acquisition_dates: list[str]
    wafers: list[str]
    structures: list[str]


class AnalysisRun:
    """Reader for a single analysis run manifest file."""

    def __init__(self, manifest_path: str | Path):
        self.manifest_path = Path(manifest_path)
        if not self.manifest_path.exists():
            raise FileNotFoundError(f"Manifest file {self.manifest_path} does not exist.")
        if self.manifest_path.name != "analysis_run.yaml":
            raise ValueError("Manifest file must be named 'analysis_run.yaml'.")
        with open(self.manifest_path, encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}

    @property
    def data(self) -> dict[str, Any]:
        """Raw manifest dictionary."""
        return self._data

    @property
    def run(self) -> dict[str, Any]:
        """Run metadata block."""
        return self._data.get("run", {})

    @property
    def mode(self) -> str:
        """Run mode: single or folders."""
        return str(self.run.get("mode", "unknown"))

    @property
    def run_id(self) -> str:
        """Run identifier string."""
        return str(self.run.get("run_id", self.manifest_path.parent.name))

    @property
    def created_at(self) -> str | None:
        """Run creation timestamp in ISO format if available."""
        value = self.run.get("created_at")
        return str(value) if value is not None else None

    def _single_sources(self) -> dict[str, Any]:
        """Source dictionary for single-mode runs."""
        return self._data.get("sources", {})

    def _folders_sources(self) -> dict[str, Any]:
        """Flatten source dictionaries for folders-mode runs."""
        out: dict[str, Any] = {}
        folders = self._data.get("folders", {})
        for folder_name, folder_payload in folders.items():
            sources = folder_payload.get("sources", {})
            for source_name, source_payload in sources.items():
                key = f"{folder_name}/{source_name}"
                out[key] = source_payload
        return out

    def sources(self) -> dict[str, Any]:
        """Flattened source metadata across run modes."""
        if self.mode == "folders":
            return self._folders_sources()
        return self._single_sources()

    @staticmethod
    def _normalized_unique(values: Iterable[Any]) -> list[str]:
        """Normalize iterables into sorted unique string values."""
        clean = {
            str(v).strip() for v in values
            if v not in (None, "", "Unknown")
        }
        return sorted(clean)

    def acquisition_dates(self) -> list[str]:
        """Acquisition dates extracted from source metadata."""
        dates = [src.get("date") for src in self.sources().values()]
        return self._normalized_unique(dates)

    def wafers(self) -> list[str]:
        """Wafer values extracted from source metadata."""
        wafers = [src.get("wafer") for src in self.sources().values()]
        return self._normalized_unique(wafers)

    def structures(self) -> list[str]:
        """Structure values extracted from source metadata."""
        structures = [src.get("structure") for src in self.sources().values()]
        return self._normalized_unique(structures)

    def to_record(self) -> AnalysisRecord:
        """Build an index record for this run."""
        return AnalysisRecord(
            run_id=self.run_id,
            mode=self.mode,
            manifest_path=self.manifest_path,
            run_directory=self.manifest_path.parent,
            created_at=self.created_at,
            acquisition_dates=self.acquisition_dates(),
            wafers=self.wafers(),
            structures=self.structures(),
        )


class AnalysisIndex:
    """Scan and query saved analysis manifests for GUI retrieval."""

    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)
        if not self.root_dir.exists():
            raise FileNotFoundError(f"Results directory {self.root_dir} does not exist.")
        self._records: list[AnalysisRecord] = []

    @property
    def records(self) -> list[AnalysisRecord]:
        """Current in-memory index records."""
        return self._records

    def build(self) -> list[AnalysisRecord]:
        """Build index by scanning analysis_run.yaml files recursively."""
        manifest_paths = sorted(self.root_dir.rglob("analysis_run.yaml"))
        records: list[AnalysisRecord] = []
        for manifest_path in manifest_paths:
            try:
                record = AnalysisRun(manifest_path).to_record()
                records.append(record)
            except (FileNotFoundError, ValueError, TypeError):
                # Ignore malformed entries and keep the index usable.
                continue
        self._records = records
        return records

    @staticmethod
    def _match_any(record_values: list[str], selected_values: set[str] | None) -> bool:
        """Return True if any value in record matches current filter."""
        if selected_values is None:
            return True
        if not selected_values:
            return True
        return any(v in selected_values for v in record_values)

    def filter(
        self,
        acquisition_dates: Iterable[str] | None = None,
        wafers: Iterable[str] | None = None,
        structures: Iterable[str] | None = None,
    ) -> list[AnalysisRecord]:
        """Filter records by acquisition date, wafer, and structure."""
        dates_set = set(acquisition_dates) if acquisition_dates is not None else None
        wafers_set = set(wafers) if wafers is not None else None
        structures_set = set(structures) if structures is not None else None
        out: list[AnalysisRecord] = []
        for record in self._records:
            if not self._match_any(record.acquisition_dates, dates_set):
                continue
            if not self._match_any(record.wafers, wafers_set):
                continue
            if not self._match_any(record.structures, structures_set):
                continue
            out.append(record)
        return out

    def available_values(self) -> dict[str, list[str]]:
        """Return all available unique values for each filter key."""
        dates = sorted({v for r in self._records for v in r.acquisition_dates})
        wafers = sorted({v for r in self._records for v in r.wafers})
        structures = sorted({v for r in self._records for v in r.structures})
        return {
            "acquisition_dates": dates,
            "wafers": wafers,
            "structures": structures,
        }

    @staticmethod
    def records_to_rows(records: Iterable[AnalysisRecord]) -> list[dict[str, Any]]:
        """Convert records into table-friendly dictionaries for UI."""
        rows: list[dict[str, Any]] = []
        for r in records:
            rows.append({
                "run_id": r.run_id,
                "mode": r.mode,
                "created_at": r.created_at,
                "acquisition_dates": ", ".join(r.acquisition_dates),
                "wafers": ", ".join(r.wafers),
                "structures": ", ".join(r.structures),
                "manifest_path": str(r.manifest_path),
                "run_directory": str(r.run_directory),
            })
        return rows
