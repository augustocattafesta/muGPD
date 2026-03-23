from typing import Any

import aptapy.models
import numpy as np
from aptapy.modeling import AbstractFitModel, FitModelSum
from aptapy.plotting import last_line_color, plt
from uncertainties import unumpy

from .context import TargetContext
from .fileio import SourceFile

XAXIS_LABELS = dict(
    back="Voltage [V]",
    drift="Drift Voltage [V]",
    time="Time [hours]",
    pressure="Pressure [mbar]"
)


def write_legend(label: str | None, *axs: plt.Axes | None, loc: str = "best" ) -> None:
    # pylint: disable=protected-access
    valid_axs: list[plt.Axes] = [ax for ax in axs if ax is not None]
    if not valid_axs:
        valid_axs = [plt.gca()]
    headers: list[Any] = []
    labels: list[str] = []
    zorders: list[float] = []
    for ax in valid_axs:
        _header, _label = ax.get_legend_handles_labels()
        headers.extend(_header)
        labels.extend(_label)
        zorders.append(int(ax.get_zorder()))
        zorders.append(ax.get_zorder())
    if len(valid_axs) > 1:
        valid_axs[0].set_zorder(max(zorders) + 1)
        valid_axs[0].set_frame_on(False)
    if headers and labels:
        leg = valid_axs[0].legend(headers, labels, loc=loc, title=label, title_fontsize=11)
        leg._legend_box.align = "bottom"    # type: ignore[attr-defined]


def get_xrange(source: SourceFile, models: list[AbstractFitModel]) -> list[float]:
    """Determine the x-axis range for plotting the source spectrum and fitted models.
    
    Arguments
    ---------
    source : SourceFile
        The source data file containing the histogram to plot.
    models : list[AbstractFitModel]
        The list of fitted models to consider for determining the x-axis range.
    Returns
    -------
    xrange : list[float]
        The x-axis range `[xmin, xmax]` for plotting.
    """
    # Get the histogram range with counts > 0 and get the range
    content = np.insert(source.hist.content, -1, 0)
    edges = source.hist.bin_edges()[content > 0]
    xmin, xmax = edges[0], edges[-1]
    m_mins = []
    m_maxs = []
    # Get the plotting range of all models, if any
    for model in models:
        low, high = model.default_plotting_range()
        m_mins.append(low)
        m_maxs.append(high)
    # Determine the final xrange including all models. If no model is given, use the
    # histogram range
    if len(models) > 0:
        xmin = max(xmin, min(m_mins))
        xmax = min(xmax, max(m_maxs))
    return [xmin, xmax]


def get_label(task_labels: list[str] | None, target_ctx: TargetContext) -> str | None:
    """Generate a label for the plot based on the specified task labels and the target context.

    Arguments
    ---------
    task_labels : list[str]
        The list of task names whose labels should be included in the plot legend.
    target_context : dict
        The context dictionary containing the labels for each task.

    Returns
    -------
    label : str | None
        The generated label for the plot, or None if no task labels are provided.
    """
    # Check if task_labels is provided
    if task_labels is None:
        return None
    label = ""
    # Iterate over the task labels and append the corresponding labels from the target context
    for task in task_labels:
        task_label = target_ctx.task_label(task)
        if task_label is not None:
            label += f"{task_label}\n"
    # Remove the trailing newline character
    label = label[:-1]
    return label


def get_model_label(task: str, model: AbstractFitModel) -> str:
    """Generate a label for the fitted model based on the analysis task and the model parameters.
    
    Arguments
    ---------
    task : str
        The name of the analysis task being performed.
    model : AbstractFitModel
        The fitted model for which to generate the label.
    """
    # If gain task, return the scale parameter of the exponential
    if task in ("gain", "compare_gain", "compare"):
        if isinstance(model, aptapy.models.Exponential):
            return f"Scale: {-model.scale.ufloat()} V"
        return model.name()
    # If gain trend task, think about what to return.
    if task == "gain_trend":
        return "IDK"
    raise NotImplementedError(f"Model label generation not implemented for task '{task}' and "
                              f"model type '{type(model)}'.")


def plot_task(xdata: np.ndarray, ydata: np.ndarray, *models: AbstractFitModel,
              **kwargs) -> plt.Figure:
    """Plot the data and fitted models for a given analysis task.

    Arguments
    ---------
    xdata : np.ndarray
        The x-axis data points.
    ydata : np.ndarray
        The y-axis data points, which may include uncertainties.
    models : AbstractFitModel
        The fitted models to plot alongside the data.
    kwargs : dict
        Additional keyword arguments for customizing the plot, such as labels, titles, and scales.
    
    Returns
    -------
    fig : plt.Figure
        The matplotlib figure object containing the plot.
    """
    # Extract the nominal values and standard deviations. Note that even if ydata is not a unumpy
    # array with nominal values and std devs, these functions will still work correctly, and the
    # output of std devs is an array full of zeros.
    ydata_vals = unumpy.nominal_values(ydata)
    ydata_errs = unumpy.std_devs(ydata)
    # Create the figure object
    fig = plt.figure(kwargs.get("fig_name"))
    # Plot the data
    plt.errorbar(
        xdata,
        ydata_vals,
        yerr=ydata_errs,
        marker=kwargs["marker"],
        linestyle="",
        label=kwargs["label"],
        color=kwargs["color"]
    )
    # Plot all models
    for i, model in enumerate(models):
        if model is None:
            continue
        model_label = kwargs.get(f"model{i}_label")
        fit_output = kwargs.get("fit_output", False)
        if isinstance(model, FitModelSum):
            plot_components = False
            model.plot(fit_output=fit_output,
                       label=model_label,
                       linestyle=kwargs["linestyle"],
                       color=last_line_color(),
                       plot_components=plot_components)
        else:
            model.plot(fit_output=fit_output,
                       label=model_label,
                       linestyle=kwargs["linestyle"],
                       color=last_line_color())
    # Annotate the minimum y value if requested
    if kwargs["annotate_min"]:
        min_idx = np.argmin(ydata_vals)
        plt.annotate(f"{ydata_vals[min_idx]:.2f}",
                    xy=(xdata[min_idx],
                    ydata_vals[min_idx]),
                    xytext=(0, 30),
                    textcoords="offset points",
                    ha="center", va="top",
                    fontsize=12)
    # Set the labels and scales
    plt.xlabel(kwargs.get("xlabel", "X axis"))
    plt.ylabel(kwargs.get("ylabel", "Y axis"))
    plt.xscale(kwargs["xscale"])
    plt.yscale(kwargs["yscale"])
    # Set the title if provided
    if "title" in kwargs:
        plt.title(kwargs["title"])
    # Write the legend with the provided label
    write_legend(kwargs["legend_label"], loc=kwargs["legend_loc"])
    plt.tight_layout()
    # Close the plot if specified
    if not kwargs.get("show", True):
        plt.close()
    return fig


def plot_compare_task(ax: plt.Axes, xdata: np.ndarray, ydata: np.ndarray,
                 model: AbstractFitModel | None = None, **kwargs) -> None:
    """Plot the data and fitted model for a comparison task on the given axes.
    
    Arguments
    ---------
    ax : plt.Axes
        The matplotlib axes on which to plot the data and model.
    xdata : np.ndarray
        The x-axis data points.
    ydata : np.ndarray
        The y-axis data points, which may include uncertainties.
    model : AbstractFitModel, optional
        The fitted model to plot alongside the data, by default None.
    kwargs : dict
        Additional keyword arguments for customizing the plot, such as labels, titles, and scales.
    """
    # Extract the nominal values and standard deviations. Note that even if ydata is not a unumpy
    # array with nominal values and std devs, these functions will still work correctly, and the
    # output of std devs is an array full of zeros.
    ydata_vals = unumpy.nominal_values(ydata)
    ydata_errs = unumpy.std_devs(ydata)
    # Plot the data with error bars on the provided axes
    ax.errorbar(
        xdata,
        ydata_vals,
        yerr=ydata_errs,
        marker=kwargs["marker"],
        linestyle="",
        label=kwargs["label"],
        color=kwargs["color"]
    )
    # Plot the model if provided
    if model:
        model_label = kwargs.get("model_label")
        model.plot(label=model_label,
                   linestyle=kwargs["linestyle"],
                   color=last_line_color())
