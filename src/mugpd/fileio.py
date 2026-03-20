"""Module to handle reading of different types of file and analyze specific type of signals.
"""

import datetime
import inspect
import re
from collections.abc import Iterable
from pathlib import Path

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
        filtered = [_f for _f in self.input_files if re.search(r"B\d+", _f.name)]

        def numeric_sort_key(p: Path):
            """Sort the files with numerical order.
            """
            numbers = [int(x) for x in re.findall(r"\d+", p.stem)]
            return numbers[-1]  # sort by the last number

        return sorted(filtered, key=numeric_sort_key)

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
