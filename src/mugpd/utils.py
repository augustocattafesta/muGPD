"""Module containing various methods to estimate physical quantities or find properties of a
signal.
"""

import importlib

import aptapy
import aptapy.models
import numpy as np
import scipy.signal
import xraydb
from aptapy.modeling import line_forest
from uncertainties import UFloat

ELEMENTARY_CHARGE = 1.609e-19   # Coulomb
ELECTRONS_IN_1FC = 1e-15 / ELEMENTARY_CHARGE  # Number of electrons in 1 fC
W_ARGON = 26.   # eV

SIGMA_TO_FWHM = 2 * np.sqrt(2 * np.log(2))


def weighted_energy(element: str, *lines: str) -> float:
    """Compute the intensity-weighted mean energy of specified X-ray lines of an element.

    The data are retrieved from the X-ray database at https://xraydb.seescience.org/.

    Arguments
    ----------
    element : str
        Atomic symbol of the element.
    lines : str
        Lines to consider in the weighted mean.
    
    Returns
    -------
    energy : float
        Intensity-weighted mean energy of the lines.
    """
    line_data = [xraydb.xray_line(element=element, line=line) for line in lines]
    total_intensity = sum(line.intensity for line in line_data)

    return sum(line.energy * line.intensity for line in line_data) / total_intensity


KALPHA = weighted_energy('Mn', 'Ka1', 'Ka2', 'Ka3') * 1e-3  # keV
KBETA = weighted_energy('Mn', 'Kb1', 'Kb3', 'Kb5') * 1e-3   # keV
AR_ESCAPE = weighted_energy("Ar", "Ka1", "Ka2", "Ka3", "Kb1", "Kb3") * 1e-3 # keV


@line_forest(KALPHA - AR_ESCAPE, KBETA - AR_ESCAPE)
class ArEscape(aptapy.models.GaussianForestBase):
    pass


def find_peaks_iterative(xdata: np.ndarray, ydata: np.ndarray,
                            npeaks: int) -> tuple[np.ndarray, np.ndarray]:
    """Find the position and height of a fixed number of peaks in a sample of data

    Arguments
    ---------
    xdata : ArrayLike,
        The x values of the sample.
    ydata : ArrayLike,
        The y values of the sample.
    npeaks : int,
        Maximum number of peaks to find in the sample.

    Returns
    -------
    xpeaks : ArrayLike
        The position of the peaks on the x axis.
    ypeaks : ArrayLike
        The height of the peaks.
    """
    min_width, max_width = 1., len(ydata)
    peaks, properties = scipy.signal.find_peaks(ydata, width=(min_width, max_width))
    widths = properties['widths']
    while len(peaks) > npeaks:
        min_width = min(widths)*1.1
        peaks, properties = scipy.signal.find_peaks(ydata, width=(min_width, max_width), distance=5)
        widths = properties['widths']

    return xdata[peaks], ydata[peaks]


def average_repeats(x: np.ndarray, y: np.ndarray, yerr: np.ndarray
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate the average of values on the y axis for each unique value on the x axis.

    Parameters
    ---------
    x : np.ndarray
        Array of x values.
    y : np.ndarray
        Array of y values.
    yerr : np.ndarray
        Array of uncertainties on the y values.

    Returns
    -------
    x_unique : np.ndarray
        Unique x values.
    y_mean : np.ndarray
        Mean y values for each unique x value.
    yerr_mean : np.ndarray
        Uncertainties on the mean y values for each unique x value.
    """
    # Find unique x values and indices to reconstruct the original array
    x_unique, inverse = np.unique(x, return_inverse=True)
    # Use np.bincount to sum y values and yerr^2 for each unique x value
    counts = np.bincount(inverse)
    y_sum = np.bincount(inverse, weights=y)
    yerr_sq_sum = np.bincount(inverse, weights=yerr**2)
    # Calculate the mean and uncertainty for each unique x value
    y_mean = y_sum / counts
    yerr_mean = np.sqrt(yerr_sq_sum) / counts
    return x_unique, y_mean, yerr_mean


def gain(w: float, line_val: np.ndarray | UFloat, energy: float) -> np.ndarray:
    """Estimate the gain of the detector from the analysis of a spectral emission line.

    Arguments
    ----------
    w : float
        W-value of the gas inside the detector.
    line_val : np.ndarray | UFloat
        Position of the peak of the emission line in charge (fC).
    energy : float
        Energy of the emission line (in keV).
    """
    exp_electrons = energy / (w * 1e-3)
    meas_electrons = line_val * ELECTRONS_IN_1FC
    return meas_electrons / exp_electrons


def energy_resolution(line_val: np.ndarray | UFloat, sigma: np.ndarray | UFloat
                      ) -> np.ndarray | UFloat:
    """Estimate the energy resolution of the detector, using the position and the sigma of a
    spectral emission line.

    Arguments
    ----------
    line_val : np.ndarray | UFloat
        Position of the peak of the emission line in charge (fC).
    sigma : np.ndarray | UFloat
        Sigma of the emission line.
    """
    return sigma * 2 * np.sqrt(2 * np.log(2)) / line_val * 100


def energy_resolution_escape(line_val_main: np.ndarray, line_val_escape: np.ndarray,
                             sigma_main: np.ndarray) -> np.ndarray:
    """Estimate the energy resolution of the detector using the main line and the escape peak.

    Arguments
    ----------
    line_val_main : np.ndarray
        Position of the peak of the main emission line.
    line_val_escape : np.ndarray
        Position of the peak of the escape line.
    sigma_main : np.ndarray
        Sigma of the main emission line.
    """
    fwhm = sigma_main * SIGMA_TO_FWHM
    return fwhm * (KALPHA - AR_ESCAPE) / (line_val_main - line_val_escape) / KALPHA * 100


def amptek_accumulate_time(start_times: np.ndarray, real_times: np.ndarray) -> np.ndarray:
    """Compute the accumulated acquisition time for Amptek MCA data, taking into account the
    start times of each acquisition and integration times. The times are expressed in seconds.

    Arguments
    ---------
    start_times : np.ndarray
        Array of datetime objects representing the start time of each acquisition.
    real_times : np.ndarray
        Array of real (integration) times for each acquisition.
    
    Returns 
    -------
    accumulated_times : np.ndarray
        Array of accumulated acquisition times.
    """
    t = np.zeros(len(start_times))
    t[0] = real_times[0]
    t_acc = 0.0
    for i in range(1, len(start_times)):
        if start_times[i] == start_times[i-1]:
            t_acc += real_times[i]
        else:
            dt_gap = (start_times[i] - start_times[0]).total_seconds()
            t_acc = dt_gap + real_times[i]
        t[i] = t_acc

    t -= real_times / 2
    return t


def _load_single_class(class_path: str) -> type[aptapy.modeling.AbstractFitModel]:
    """Load a single class from a given class path.

    Arguments
    ---------
    class_path : str
        The class path to load.
    
    Returns
    -------
    cls : type[aptapy.modeling.AbstractFitModel]
        The loaded class.
    """
    cls = None
    if "." not in class_path:
        if hasattr(aptapy.models, class_path):
            cls = getattr(aptapy.models, class_path)
        else:
            raise ImportError(f"Class '{class_path}' not found in aptapy.modeling.")
    else:
        module_name, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
    return cls


def load_class(class_path: str) -> list[type[aptapy.modeling.AbstractFitModel]]:
    """Load one or more classes from a given class path or multiple class paths separated by '+'.
    
    Arguments
    ---------
    class_path : str
        The class path(s) to load. Multiple class paths can be separated by '+'.
    
    Returns
    -------
    classes : list[type[aptapy.modeling.AbstractFitModel]]
        The list of loaded classes.
    """
    class_paths = [p.strip() for p in class_path.split("+")]
    return [_load_single_class(p) for p in class_paths]
