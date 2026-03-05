"""Classes for configuration options of the analysis."""

import pathlib
from dataclasses import dataclass
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from .utils import KALPHA


@dataclass(frozen=True)
class CalibrationDefaults:
    """Default values for the calibration task.
    """
    charge_conversion: bool = True
    show: bool = False


class CalibrationConfig(BaseModel):
    """Perform the detector calibration using pulse data at fixed voltages.

    Attributes
    ----------
    task : str
        Name of the task, to perform it must be 'calibration'.
    charge_conversion : bool, optional
        Whether to convert the calibration to charge (fC) or leave it in voltage (mV). Default
        is True.
    show : bool, optional
        Whether to generate and show the plots of the calibration process. Default is False.
    """
    task: Literal["calibration"]
    charge_conversion: bool = CalibrationDefaults.charge_conversion
    show: bool = CalibrationDefaults.show


@dataclass(frozen=True)
class FitPeakDefaults:
    """Defaults values for the peak fitting subtasks.
    """
    xmin: float = float("-inf")
    xmax: float = float("inf")
    num_sigma_left: float = 1.5
    num_sigma_right: float = 1.5
    absolute_sigma: bool = True
    p0: list[float] | None = None


class FitPars(BaseModel):
    """Parameters for spectrum fitting subtasks.

    Attributes
    ----------
    xmin : float, optional
        Minimum x value to consider for the fit. Default is -inf.
    xmax : float, optional
        Maximum x value to consider for the fit. Default is inf.
    num_sigma_left : float, optional
        Number of sigma to the left of the peak to consider for the fit. Default is 1.5.
    num_sigma_right : float, optional
        Number of sigma to the right of the peak to consider for the fit. Default is 1.5.
    absolute_sigma : bool, optional
        Whether to use absolute sigma for the fit. Default is True.
    p0 : list[float], optional
        Initial guess for the fit parameters. Default is None, which means that the initial guess
        will be automatically calculated from the data.
    """
    xmin: float = FitPeakDefaults.xmin
    xmax: float = FitPeakDefaults.xmax
    num_sigma_left: float = FitPeakDefaults.num_sigma_left
    num_sigma_right: float = FitPeakDefaults.num_sigma_right
    absolute_sigma: bool = FitPeakDefaults.absolute_sigma
    p0: list[float] | None = FitPeakDefaults.p0


class FitSubtaskConfig(BaseModel):
    """Define a subtask for fitting data.

    Attributes
    ----------
    target: str
        Assign a name to the fitting subtask. The target name can then be used to use the fit
        results in other tasks (e.g. plot or gain).
    model: str
        The name of the model to use for the fit. If spectrum fitting is performed, the model must
        be one between Gaussian and Fe55Forest defined in aptapy.models. When fitting other data,
        any model or composite model defined in aptapy.models can be used. To specify a composite
        model, the syntax is "Model1 + Model2 + ...".
    fit_pars: FitPars, optional
        Fit parameters for the fitting subtask. Default values are defined in FitPars.
    """
    target: str
    model: str
    fit_pars: FitPars = Field(default_factory=FitPars)


class FitSpecConfig(BaseModel):
    """Perform the spectrum fitting for each source file using the model and the fit parameters
    defined in the fitting subtasks.

    Attributes
    ----------
    task: str
        Name of the task, to perform it must be 'fit_spec'.
    subtasks: list[FitSubtask]
        List of fitting subtasks to perform. Each subtask defines the model and the fit parameters
        to use for the fit.
    """
    task: Literal["fit_spec"]
    subtasks: list[FitSubtaskConfig]


@dataclass(frozen=True)
class SourceDefaults:
    """Default values for the source acquisition parameters.
    """
    energy: float = KALPHA
    w: float = 26.0


class SourceConfig(BaseModel):
    """Set the acquisition parameters of the source and the detector.

    Attributes
    ----------
    energy : float
        The energy of the main emission line, expressed in keV. Default is K-alpha of Fe55
        (5.9keV).
    w : float
        W-value of the gas used in the detector, expressed in eV. Default is 26.0 eV, which
        is the W-value of Argon.
    """
    energy: float = SourceDefaults.energy
    w: float = SourceDefaults.w


@dataclass(frozen=True)
class TaskDefaults:
    """Default values for the analysis tasks.
    """
    xaxis: str = "back"
    fit: bool = True
    show: bool = True
    energy_threshold: float = 1.5 # keV
    show_rate: bool = True


class GainConfig(BaseModel):
    """Perform the gain calculation for each source file using the results of the fitting subtasks.
    The gain is calculated as the ratio between the inferred charge from the fit results and the
    expected number of electrons for the given peak energy.
    
    Attributes
    ----------
    task: str
        Name of the task, to perform it must be 'gain'.
    target: str
        The target name of the fitting subtask to use for the gain calculation.
    xaxis: str, optional
        The x-axis to use for the gain plot. The choices are between 'back', 'drift', 'time' and
        'pressure'. Default is 'back'.
    fit: bool, optional
        Whether to fit the gain values with an exponential function of the voltage. If a single
        source file is analyzed, the fit is not performed. Default is True.
    show: bool, optional
        Whether to generate and show the plot of the gain values as a function of the back voltage.
        If a single source file is analyzed, the plot is not generated. Default is True.
    """
    task: Literal["gain"]
    target: str
    xaxis: str = TaskDefaults.xaxis
    fit: bool = TaskDefaults.fit    # TODO: remove this option when subtasks are implemented
    subtasks: list[FitSubtaskConfig] | None = Field(default=None)
    show: bool = TaskDefaults.show

class DriftConfig(BaseModel):
    """Perform the analysis of the gain as a function of drift voltage for each source file using
    the results of the fitting subtasks. The gain is calculated as the ratio between the inferred
    charge from the fit results and the expected number of electrons for the given peak energy.
    If specified, analyze the rate of events above a given energy threshold as a function of the
    drift voltage.
    
    Attributes
    ----------
    task: str
        Name of the task, to perform it must be 'drift'.
    target: str
        The target name of the fitting subtask to use for the gain calculation.
    energy_threshold: float, optional
        Energy threshold to consider for the rate calculation. Default is 1.5 keV.
    show: bool, optional
        Whether to generate and show the plot of the gain and rate values as a function of the
        drift voltage. If a single source file is analyzed, the plot is not generated. Default
        is True.
    show_rate: bool, optional
        Whether to show the rate values as a function of the drift voltage on the same plot of
        the gain. Default is True.
    """
    task: Literal["drift"]
    target: str
    energy_threshold: float = TaskDefaults.energy_threshold
    show_rate: bool = TaskDefaults.show_rate
    show: bool = TaskDefaults.show


class ResolutionConfig(BaseModel):
    """Perform the resolution calculation for each source file using the results of the fitting
    subtasks. The resolution is calculated using the charge calibrated spectra as the FWHM of the
    peak divided by the peak position.

    Attributes
    ----------
    task: str
        Name of the task, to perform it must be 'resolution'.
    target: str
        The target name of the fitting subtask to use for the resolution calculation.
    xaxis: str, optional
        The x-axis to use for the resolution plot. The choices are between 'back', 'drift' 'time'
        and 'pressure'. Default is 'back'.
    show: bool, optional
        Whether to generate and show the plot of the resolution values as a function of the back
        voltage. If a single source file is analyzed, the plot is not generated. Default is True.
    """
    task: Literal["resolution"]
    target: str
    xaxis: str = TaskDefaults.xaxis
    show: bool = TaskDefaults.show


class ResolutionEscapeConfig(BaseModel):
    """Perform the resolution escape calculation for each source file using the results of the
    fitting subtasks. The resolution escape is calculated as the FWHM of the main peak divided
    by the peak position, normalized to the ratio between the distance between the main peak and
    the escape peak and the energy difference between them.
    When using a charge calibrated spectrum, this estimate is equivalent to the previous one.

    Attributes
    ----------
    task: str
        Name of the task, to perform it must be 'resolution_escape'.
    target_main: str
        The target name of the fitting subtask to use for the main peak.
    target_escape: str
        The target name of the fitting subtask to use for the escape peak.
    show: bool, optional
        Whether to generate and show the plot of the resolution escape values as a function of the
        back voltage. If a single source file is analyzed, the plot is not generated. Default is
        True.
    """
    task: Literal["resolution_escape"]
    target_main: str
    target_escape: str
    show: bool = TaskDefaults.show


@dataclass(frozen=True)
class CompareTaskDefaults:
    """Default values for the comparison tasks.
    """
    combine: list[str] = Field(default_factory=list)


class CompareGainConfig(BaseModel):
    """Compare the gain vs back voltage curves for multiple source folders. A gain task must be
    performed before the compare gain task.

    Attributes
    ----------
    task: str
        Name of the task, to perform it must be 'compare_gain'.
    target: str
        The target name of the fitting subtask to use for the gain calculation.
    combine: list[str], optional
        List of folder names to combine in the same curve. If a folder name is not specified,
        another curve will be generated in the same plot. Default is an empty list, which means
        that no folders will be combined.
    show: bool, optional
        Whether to generate and show the plot of the gain comparison. Default is True.
    """
    task: Literal["compare_gain"]
    target: str
    xaxis: str = TaskDefaults.xaxis
    combine: list[str] = CompareTaskDefaults.combine
    show: bool = TaskDefaults.show


class CompareResolutionConfig(BaseModel):
    """Compare the resolution vs back voltage curves for multiple source folders. A resolution task
    must be performed before the compare resolution task.

    Attributes
    ----------
    task: str
        Name of the task, to perform it must be 'compare_resolution'.
    target: str
        The target name of the fitting subtask to use for the resolution calculation.
    combine: list[str], optional
        List of folder names to combine in the same curve. If a folder name is not specified,
        another curve will be generated in the same plot. Default is an empty list, which means
        that no folders will be combined.
    show: bool, optional
        Whether to generate and show the plot of the resolution comparison. Default is True.
    """
    task: Literal["compare_resolution"]
    target: str
    combine: list[str] = CompareTaskDefaults.combine
    show: bool = TaskDefaults.show


class CompareTrendConfig(BaseModel):
    """Compare the gain trends as a function of time for multiple folders. A gain trend task must
    be performed before the compare trend task.

    Attributes
    ----------
    task: str
        Name of the task, to perform it must be 'compare_trend'.
    target: str
        The target name of the fitting subtask to use for the gain trend calculation.
    show: bool, optional
        Whether to generate and show the plot of the gain trend comparison. Default is True.
    """
    task: Literal["compare_trend"]
    target: str
    show: bool = TaskDefaults.show


@dataclass(frozen=True)
class PlotDefaults:
    """Default values for the plot task.
    """
    task_labels: list[str] | None = None
    voltage: bool = False
    xrange: list[float] | None = Field(None, min_length=2, max_length=2)
    xmin_factor: float = 1.
    xmax_factor: float = 1.
    show: bool = True


class PlotConfig(BaseModel):
    """Plot the spectra and the fit results for each source file. It is possible to specify
    different plotting options and choose which fit results to show.

    Attributes
    ----------
    task: str
        Name of the task, to perform it must be 'plot'.
    targets: list[str] | None
        List of target names of the fitting subtasks to show in the plot. If None, the entire
        spectrum is shown, with no best-fit curve. Default is None.
    task_labels: list[str] | None
        List of analysis task result labels to show in the plot legend. If None, no result is
        shown in the legend. Default is None.
    voltage: bool, optional
        Whether to show the source voltage information in the plot legend. Default is False.
    xrange: list[float] | None
        Range of x values to show in the plot. If None, the range is automatically determined from
        the best-fit results, taking 5 sigma around the peak(s) position(s). Default is None.
    xmin_factor: float
        Factor to multiply the automatically determined minimum x value for the plot. Default is 1.
    xmax_factor: float
        Factor to multiply the automatically determined maximum x value for the plot. Default is 1.
    show: bool, optional
        Whether to show the generated plot. Default is True.
    """
    task: Literal["plot"]
    targets: list[str] | None = None
    task_labels: list[str] | None = PlotDefaults.task_labels
    voltage: bool = PlotDefaults.voltage
    xrange: list[float] | None = PlotDefaults.xrange
    xmin_factor: float = PlotDefaults.xmin_factor
    xmax_factor: float = PlotDefaults.xmax_factor
    show: bool = PlotDefaults.show


@dataclass(frozen=True)
class PlotStyleDefaults:
    """Default values for the plot style.
    """
    xscale: Literal["linear", "log"] = "linear"
    yscale: Literal["linear", "log"] = "linear"
    title: str | None = None
    label: str = "Data"
    legend_label: str | None = None
    legend_loc: str = "best"
    marker: str = "."
    linestyle: str = "-"
    color: str | None = None
    fit_output: bool = False
    annotate_min: bool = False


class PlotStyleConfig(BaseModel):
    """Configure the style of the plots. These settings can be configured for each task and folder
    analyzed during the pipeline analysis.

    Attributes
    ----------
    xscale : str
        Set the scale of the x-axis of the plot. The choices are between `linear` and `log`.
        Default is `linear`.
    yscale : str
        Set the scale of the y-axis of the plot. The choices are between `linear` and `log`.
        Default is `linear`.
    title : str | None
        Set the title shown at the top of the plot. Default is None.
    label : str | None
        Set the label associated to data to show in the legend. Default is 'Data'.
    legend_label : str | None
        Set the label to show at the top of the legend. This setting is useful to add information
        to the legend. Default is None.
    legend_loc : str
        Set the position of the legend in the plot. See matplotlib docs for the possible choices.
        Default is `best`.
    marker : str
        Set the marker style for the data points. See matplotlib docs for the possible choices.
        Default is `.`.
    linestyle : str
        Set the line style for the best-fit curve. See matplotlib docs for the possible choices.
        Default is `-`.
    color : str
        Set the color of the marker and of the line. See matplotlib docs for the possible choices.
        Default is `black`.
    fit_output : bool
        Whether to show the best-fit parameters and information in the legend. Default is False.
    annotate_min : bool
        Whether to show a textbox with the value of the minimum of the plot near the point. Default
        is False.
    """
    xscale: Literal["linear", "log"] = PlotStyleDefaults.xscale
    yscale: Literal["linear", "log"] = PlotStyleDefaults.yscale
    title: str | None = PlotStyleDefaults.title
    label: str | None = PlotStyleDefaults.label
    legend_label: str | None = PlotStyleDefaults.legend_label
    legend_loc: str = PlotStyleDefaults.legend_loc
    marker: str = PlotStyleDefaults.marker
    linestyle: str = PlotStyleDefaults.linestyle
    color: str | None = PlotStyleDefaults.color
    fit_output: bool = PlotStyleDefaults.fit_output
    annotate_min: bool = PlotStyleDefaults.annotate_min


class StyleConfig(BaseModel):
    """Define the style of the tasks performed during the analysis pipeline and configure the style
    for each folder. See the guide or the example in the package documentation for more
    informations.

    Attributes
    ----------
    tasks : dict[str, PlotStyleConfig]
        Write a .yaml dictionary to configure the style for each task.
    folders : dict[str, PlotStyleConfig]
        Write a .yaml dictionary to configure the style of each folder analyzed during the
        analysis. 
    """
    tasks: dict[str, PlotStyleConfig] = Field(default_factory=dict)
    folders: dict[str, PlotStyleConfig] = Field(default_factory=dict)


class Acquisition(BaseModel):
    date: str | None = None
    chip: str | None = None
    structure: str | None = None
    gas: str | None = None
    w: float = 26.0
    element: str | None = None
    e_peak: float = KALPHA


TaskType = CalibrationConfig | FitSpecConfig | GainConfig | ResolutionConfig | \
    ResolutionEscapeConfig | PlotConfig | DriftConfig | CompareGainConfig | \
    CompareResolutionConfig | CompareTrendConfig


class AppConfig(BaseModel):
    acquisition: Acquisition = Field(default_factory=Acquisition)
    # Change source name to avoid confusion with context.source
    source: SourceConfig = Field(default_factory=SourceConfig)
    pipeline: list[TaskType]
    style: StyleConfig = Field(default_factory=StyleConfig)

    @classmethod
    def from_yaml(cls, path: str | pathlib.Path) -> "AppConfig":
        with open(path, encoding="utf-8") as f:
            return cls(**yaml.safe_load(f))

    def to_yaml(self, path: str | pathlib.Path) -> None:
        data = self.model_dump()
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)

    @property
    def calibration(self) -> CalibrationConfig:
        _config = next((t for t in self.pipeline if isinstance(t, CalibrationConfig)), None)
        if not _config:
            raise RuntimeError("No calibration task found in the pipeline. Make sure to specify a" \
            " calibration task.")
        return _config

    @property
    def fit_spec(self) -> FitSpecConfig | None:
        return next((t for t in self.pipeline if isinstance(t, FitSpecConfig)), None)

    @property
    def plot(self) -> PlotConfig | None:
        return next((t for t in self.pipeline if isinstance(t, PlotConfig)), None)
