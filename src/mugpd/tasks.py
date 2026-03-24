"""Analysis tasks.
"""

import aptapy.models
import numpy as np
from aptapy.modeling import AbstractFitModel
from aptapy.plotting import last_line_color, plt
from uncertainties import unumpy

from ._logger import log
from .config import (
    CompareConfig,
    DriftConfig,
    FitSubtaskConfig,
    GainConfig,
    NoiseConfig,
    PlotConfig,
    PlotStyleConfig,
    ResolutionConfig,
    ResolutionEscapeConfig,
)
from .context import Context, FoldersContext, TargetContext
from .plotting import (
    XAXIS_LABELS,
    YAXIS_LABELS,
    get_label,
    get_model_label,
    get_xrange,
    plot_compare_task,
    plot_task,
    write_legend,
)
from .utils import (
    SIGMA_TO_FWHM,
    amptek_accumulate_time,
    average_repeats,
    energy_resolution,
    energy_resolution_escape,
    find_peaks_iterative,
    gain,
    load_class,
)

XAXIS_DICT = dict(
    back="voltages",
    drift="drift_voltages",
    pressure="pressures",
    time="times"
)


def _fit_subtask(xdata: np.ndarray, ydata: np.ndarray,
                 subtask: FitSubtaskConfig) -> AbstractFitModel:
    """Fit the data with the model specified in the subtask configuration.

    Parameters
    ----------
    xdata : np.ndarray
        The x data to fit.
    ydata : np.ndarray
        The y data to fit.
    subtask : FitSubtaskConfig
        The configuration of the fitting subtask.

    Returns
    -------
    model : AbstractFitModel
        The fitted model.
    """
    # Load the model and create the instance
    model_list = load_class(subtask.model)
    model = model_list[0]()
    for m in model_list[1:]:
        model += m()
    # Load the fit parameters and fit the model to the data
    fit_pars = subtask.fit_pars.model_dump(exclude={"num_sigma_left", "num_sigma_right"})
    y_nom = unumpy.nominal_values(ydata)
    y_err = unumpy.std_devs(ydata)
    model.fit(xdata, y_nom, sigma=y_err, **fit_pars)
    return model


def calibration(context: Context) -> Context:
    """Perform the calibration of the detector using pulse data at fixed voltages.

    Parameters
    ----------
    context : Context
        The context object containing the pulse data in `context.pulse` as an instance
        of the class PulsatorFile.
    
    Returns
    -------
    context : Context
        The updated context object containing the calibration results in
        `context.conversion_model`.
    """
    # Get the CalibrationConfig
    config = context.config.calibration.model_dump()
    # Get the histogram of the data and plot it
    pulse = context.pulse
    hist = pulse.hist
    pulse_fig = plt.figure(pulse.file_path.name)
    hist.plot()
    # Find pulses and fit them with Gaussian models to find their positions
    xpeaks, _ = find_peaks_iterative(hist.bin_centers(), hist.content, pulse.num_pulses)
    log.info(f"Found {len(xpeaks)} peaks in the pulse data")
    mu_peak = np.zeros(pulse.num_pulses, dtype=object)
    log.info("Fitting pulses")
    for i, xpeak in enumerate(xpeaks):
        peak_model = aptapy.models.Gaussian()
        xmin = xpeak - np.sqrt(xpeak)
        xmax = xpeak + np.sqrt(xpeak)
        peak_model.fit_iterative(hist, xmin=xmin, xmax=xmax, absolute_sigma=True)
        mu_peak[i] = peak_model.mu.ufloat()
        peak_model.plot(fit_output=True)
    log.success("Pulse fitting completed")
    plt.legend()
    # Fit the data to find the calibration parameters
    ylabel = "Charge [fC]" if config["charge_conversion"] else "Voltage [mV]"
    model = aptapy.models.Line("Calibration", "ADC Channel", ylabel)
    xdata = unumpy.nominal_values(mu_peak)
    ydata = pulse.voltage
    log.info("Fitting calibration model")
    model.fit(xdata, ydata)
    log.success("Calibration model fitted")
    # Plot the calibration results
    cal_fig = plt.figure("Calibration")
    plt.errorbar(xdata, ydata, fmt=".k", label="Data")
    model.plot(fit_output=True, color=last_line_color())
    plt.legend()
    if not config["show"]:
        plt.close(pulse_fig)
        plt.close(cal_fig)
    # Update the context with the calibration model
    context.conversion_model = model
    # Update the context with the figures
    context.add_figure("pulse", pulse_fig)
    context.add_figure("calibration", cal_fig)
    return context


def subtract_noise(context: Context, noise_config: NoiseConfig) -> Context:
    """Subtract the noise from the spectrum fitting with the model specified in the configuration
    file. The noise model is fitted to the first bins of the spectrum and then is subtracted.

    Parameters
    ----------
    context : Context
        The context object containing the source data in `context.last_source` as an instance
        of the class SourceFile.
    noise_config : NoiseConfig
        The noise configuration instance containing the parameters for the noise fitting and
        subtraction.
    
    Returns
    -------
    context : Context
        The updated context object containing the noise-subtracted spectrum in
        `context.last_source.hist`.
    """
    # Access the last source data added to the context and get the histogram
    source = context.last_source
    if source.noise_subtracted is False:
        hist = source.hist
        content = hist.content
        bin_centers = hist.bin_centers()
        noise_model = load_class(noise_config.model)[0]()
        log.info(f"Subtracting noise from the spectrum fitting with {noise_model.name()} model")
        # Freeze the parameters of the noise model according to the configuration
        for param, value in noise_config.freeze.items():
            attr = getattr(noise_model, param)
            attr.freeze(value)
            log.info(f"Freezing parameter {param} to value {value} in noise" \
                      f" {noise_model.name()} model")
        # Find the index of the bins with content > 0
        idx = np.where(content > 0)[0]
        # Fit the first n bins with an exponential
        x_noise = bin_centers[idx][1:noise_config.nbins + 1]
        y_noise = content[idx][1:noise_config.nbins + 1]
        noise_model.fit(x_noise, y_noise, sigma=np.sqrt(y_noise))
        # Subtract the noise model from the histogram
        subtracted_content = content.copy()
        # Set the content of the first bin to 0 because the MCA threshold lose some counts
        subtracted_content[idx[0]] = 0
        # Subtract the noise model from the bins with content > 0, starting from the second bin
        subtracted_content[idx[1:]] -= noise_model(bin_centers[idx[1:]])
        # Set any negative content to 0
        subtracted_content[subtracted_content < 0] = 0
        hist.set_content(subtracted_content)
        # Updating the source object to avoid multiple noise subtractions if multiple fitting
        # subtasks are defined in the configuration file
        source.noise_subtracted = True
        log.success("Noise subtraction completed")
    return context


def _fit_peak(context: Context, subtask: FitSubtaskConfig) -> Context:
    """Perform the fitting of a spectral emission line in the source data. If requested, the noise
    can be fitted and subtracted from the spectrum before fitting the peak. 

    Parameters
    ----------
    context : Context
        The context object containing the source data in `context.last_source` as an instance
        of the class SourceFile.
    subtask : FitSubtaskConfig
        The configuration of the fitting subtask, containing the target name, the model class and
        the fit parameters.
    
    Returns
    -------
    context : Context
        The updated context object containing the fit results.
    """
    # Access target
    target = subtask.target
    # Access the last source data added to the context and get the histogram
    source = context.last_source
    hist = source.hist
    bin_centers = hist.bin_centers()
    # Load the model and fit parameters
    model = load_class(subtask.model)[0]()
    fit_pars = subtask.fit_pars
    log.info(f"Fitting target {target} with model {model.name()}")
    # Without a proper initialization of xmin and xmax the fit doesn't converge
    kwargs = fit_pars.model_dump()
    x_peak = bin_centers[hist.content > 0][5:][np.argmax(hist.content[hist.content > 0][5:])]
    if fit_pars.xmin == float("-inf") and fit_pars.xmax == float("inf"):
        kwargs["xmin"] = x_peak - 0.3 * np.sqrt(x_peak)
        kwargs["xmax"] = x_peak + 0.3 * np.sqrt(x_peak)
    log.info(f"Starting fitting range: {kwargs['xmin']} to {kwargs['xmax']}")
    # Fit the data. We only support Gaussian and Fe55Forest models.
    if isinstance(model, aptapy.models.Fe55Forest):
        model.intensity1.freeze(0.16)   # type: ignore[attr-defined]
    model.fit_iterative(hist, **kwargs) # type: ignore[attr-defined]
    # Extract the line value and sigma from the fit results
    if isinstance(model, aptapy.models.Gaussian):
        line_val = model.status.correlated_pars[1]
        sigma = model.status.correlated_pars[2]
    elif isinstance(model, aptapy.models.Fe55Forest):
        reference_energy: float = model.energies[0]   # type: ignore [attr-defined]
        line_val = reference_energy / model.status.correlated_pars[1]
        sigma = model.status.correlated_pars[2]
    else:
        raise TypeError(f"Model of type {model.name()} not supported in fit_peak task")
    log.success(f"Fitting of target {target} completed")
    # Update the context with the fit results
    target_ctx = TargetContext(target, line_val, sigma, source.voltage, model)
    target_ctx.energy = context.config.source.energy
    # Add the fwhm to the target context
    target_ctx.fwhm_val = SIGMA_TO_FWHM * sigma
    # Save the target context in the main context
    context.add_target_ctx(source, target_ctx)
    return context


def _fit_noise(context: Context, subtask: FitSubtaskConfig) -> Context:
    """Perform the fitting of the noise in a source data containing only noise.

    Parameters
    ----------
    context : Context
        The context object containing the source data in `context.last_source` as an instance
        of the class SourceFile.
    subtask : FitSubtaskConfig
        The configuration of the fitting subtask, containing the target name, the model class and
        the fit parameters.
    
    Returns
    -------
    context : Context
        The updated context object containing the fit results.
    """
    target = subtask.target
    # Access the source data and get the histogram
    source = context.last_source
    hist = source.hist
    content = hist.content
    bin_centers = source.hist.bin_centers()
    # Find the index of the bins with content > 0 and fit the noise model to those bins. We
    # exclude the first bin because the MCA threshold lose some counts. thus is lower than the
    # second bin.
    idx = np.where(content > 0)[0]
    x_noise = bin_centers[idx[1:]]
    y_noise = content[idx[1:]]
    # Load the model and fit parameters and then fit the data
    model = load_class(subtask.model)[0]()
    fit_pars = subtask.fit_pars.model_dump(exclude={"num_sigma_left", "num_sigma_right"})
    model.fit(x_noise, y_noise, sigma=np.sqrt(y_noise), **fit_pars)
    # Update the context with the fit results
    target_ctx = TargetContext(target, 0., 0., 0., model)
    context.add_target_ctx(source, target_ctx)
    return context


def fit_spec(context: Context, subtask: FitSubtaskConfig) -> Context:
    """Fit the spectrum of a source file with the model specified in the subtask configuration.
    This function is a wrapper to dispatch the fitting to the appropriate fit function based on
    the fit model type. In case the model is a Gaussian or a Fe55Forest, the fitting is performed
    with the `_fit_peak` function, otherwise it is performed with the `_fit_noise` function.

    Parameters
    ----------
    context : Context
        The context object containing the source data in `context.last_source` as an instance
        of the class SourceFile.
    subtask : FitSubtaskConfig
        The configuration of the fitting subtask, containing the target name, the model class and
        the fit parameters.
    
    Returns
    -------
    context : Context
        The updated context object containing the fit results.
    """
    if subtask.model in ["Gaussian", "Fe55Forest"]:
        return _fit_peak(context, subtask)
    return _fit_noise(context, subtask)


def gain_task(context: Context, task: GainConfig) -> Context:
    """Calculate the gain of the detector vs the back voltage using the fit results obtained from
    the source data of multiple files.

    Parameters
    ----------
    context : Context
        The context object containing the fit results.
    task : GainConfig
        The gain configuration instance.
        
    Returns
    -------
    context : Context
        The updated context object containing the gain results.
    """
    name = task.task
    target = task.target
    xaxis = task.xaxis
    # Get the file names from the fit context keys
    file_names = context.file_names
    # Create empty arrays to store gain values and voltages
    gain_vals = np.zeros(len(file_names), dtype=object)
    voltages = np.zeros(len(file_names))
    drift_voltages = np.zeros(len(file_names))
    pressures = np.zeros(len(file_names))
    start_times = np.zeros(len(file_names), dtype=object)
    real_times = np.zeros(len(file_names))
    # Iterate over all files and calculate the gain
    for i, file_name in enumerate(file_names):
        source = context.source(file_name)
        start_times[i] = source.start_time
        real_times[i] = source.real_time
        drift_voltages[i] = source.drift_voltage
        pressures[i] = source.pressure
        target_ctx = context.target_ctx(file_name, target)
        line_val = target_ctx.line_val
        voltages[i] = target_ctx.voltage
        target_ctx.gain_val = gain(context.config.source.w,
                                   line_val,
                                   context.config.source.energy)
        gain_vals[i] = target_ctx.gain_val
    # Save the results in the context
    times = amptek_accumulate_time(start_times, real_times) / 3600
    xaxis_data = dict(
        back=voltages,
        drift=drift_voltages,
        pressure=pressures,
        time=times
    )
    context.add_task_results(name, target, dict(voltages=voltages,
                                                drifts=drift_voltages,
                                                pressures=pressures,
                                                times=times,
                                                gain_vals=gain_vals))
    # If only a single file is analyzed, return the context without plotting or fitting
    if len(file_names) == 1:
        return context
    models = []
    model_labels = dict()
    if task.subtasks:
        for i, subtask in enumerate(task.subtasks):
            xdata = xaxis_data[xaxis]
            ydata = gain_vals
            model = _fit_subtask(xdata, ydata, subtask)
            models.append(model)
            model_labels[f"model{i}_label"] = get_model_label(name, model)
            # Update the context with the fit results
            context.add_subtask_fit_model(name, target, subtask.target, model)
    # Define the plot keyword arguments for style and labels
    style = context.config.style.tasks.get(name, PlotStyleConfig()).model_dump()
    plot_kwargs = dict(
        xlabel=XAXIS_LABELS[xaxis],
        ylabel="Gain",
        fig_name=f"gain_{target}",
        show=task.show,
        **model_labels,
        **style)
    # Create the figure for the gain
    xaxis_data = dict(
        back=voltages,
        drift=drift_voltages,
        pressure=pressures,
        time=times
    )
    fig = plot_task(xaxis_data[xaxis], gain_vals, *models, **plot_kwargs)
    # Add the figure to the context
    context.add_figure(name, fig)
    return context


def resolution_task(context: Context, task: ResolutionConfig) -> Context:
    """Calculate the energy resolution of the detector using the fit results obtained from the
    source data. This estimate is based on the position and the width of the target spectral
    line.

    Parameters
    ---------
    context : Context
        The context object containing the fit results.
    task : ResolutionConfig
        The resolution configuration instance.
    
    Returns
    -------
    context : Context
        The updated context object containing the resolution results.
    """
    name = task.task
    target = task.target
    xaxis = task.xaxis
    # Get the file names from the fit context keys
    file_names = context.file_names
    # Create empty arrays to store resolution values and voltages
    res_vals = np.zeros(len(file_names), dtype=object)
    voltages = np.zeros(len(file_names))
    drift_voltages = np.zeros(len(file_names))
    pressures = np.zeros(len(file_names))
    start_times = np.zeros(len(file_names), dtype=object)
    real_times = np.zeros(len(file_names))
    # Iterate over all files and calculate the gain
    for i, file_name in enumerate(file_names):
        # Access the target context and extract line value, sigma and voltage
        source = context.source(file_name)
        target_ctx = context.target_ctx(file_name, target)
        line_val = target_ctx.line_val
        sigma = target_ctx.sigma
        start_times[i] = source.start_time
        real_times[i] = source.real_time
        pressures[i] = source.pressure
        drift_voltages[i] = source.drift_voltage
        voltages[i] = target_ctx.voltage
        target_ctx.res_val = energy_resolution(line_val, sigma)
        res_vals[i] = target_ctx.res_val
    # Save the results in the context
    times = amptek_accumulate_time(start_times, real_times) / 3600
    context.add_task_results(name, target, dict(voltages=voltages,
                                                drifts=drift_voltages,
                                                pressures=pressures,
                                                times=times,
                                                res_vals=res_vals))
    # If only a single file is analyzed, return the context without plotting
    if len(file_names) == 1:
        return context
    # Define the plot keyword arguments for style and labels
    style = context.config.style.tasks.get(name, PlotStyleConfig()).model_dump()
    plot_kwargs = dict(
        xlabel=XAXIS_LABELS[xaxis],
        ylabel=r"$\Delta$E/E",
        fig_name=f"resolution_{target}",
        show=task.show,
        **style)
    # Create the figure for the resolution trend
    xaxis_data = dict(
        back=voltages,
        drift=drift_voltages,
        pressure=pressures,
        time=times,
    )
    fig = plot_task(xaxis_data[xaxis], res_vals, **plot_kwargs)
    # Add the figure to the context
    context.add_figure(name, fig)
    return context


def resolution_escape(context: Context, task: ResolutionEscapeConfig) -> Context:
    """Calculate the energy resolution of the detector using the fit results obtained from the
    source data. This calculation is based on the position and width of the main spectral line and
    the position of the escape peak.

    Parameters
    ---------
    context : Context
        The context object containing the fit results.
    task : ResolutionEscapeConfig
        The resolution escape configuration instance.
    
    Returns
    -------
    context : Context
        The updated context object containing the resolution results.
    """
    name = task.task
    target_main = task.target_main
    target_escape = task.target_escape
    # Get the single file names from the fit context keys
    file_names = context.file_names
    # Create empty arrays to store resolution values and voltages
    res_vals = np.zeros(len(file_names), dtype=object)
    voltages = np.zeros(len(file_names))
    for i, file_name in enumerate(file_names):
        # Access the target contexts and extract line values and sigma
        target_ctx = context.target_ctx(file_name, target_main)
        line_val_main = target_ctx.line_val
        sigma_main = target_ctx.sigma
        voltages[i] = target_ctx.voltage
        line_val_esc = context.target_ctx(file_name, target_escape).line_val
        # Calculate the energy resolution using the escape peak and update the context
        target_ctx.res_escape_val = energy_resolution_escape(line_val_main,
                                                             line_val_esc,
                                                             sigma_main)
        res_vals[i] = target_ctx.res_escape_val
    # Save the results in the context
    context.add_task_results(name, target_main, dict(voltages=voltages, res_vals=res_vals))
    # If only a single file is analyzed, return the context without plotting
    if len(file_names) == 1:
        return context
    # Create the figure for the resolution trend
    style = context.config.style.tasks.get(name, PlotStyleConfig()).model_dump()
    plot_kwargs = dict(
        xlabel="Voltage [V]",
        ylabel=r"$\Delta$E/E (escape)",
        fig_name=f"resolution_esc_{target_main}",
        show=task.show,
        **style)
    fig = plot_task(voltages, res_vals, **plot_kwargs)
    context.add_figure(name, fig)
    return context


def compare(context: FoldersContext, task: CompareConfig) -> FoldersContext:
    name = task.task
    quantity = task.quantity
    combine = task.combine
    task_results = dict(
        gain="gain_vals",
        resolution="res_vals",
        drift="drift_voltages",
    )
    plot_styles = context.config.style.folders
    # Create empty arrays to store x and y values
    y = np.zeros(len(combine), dtype=object)
    yerr = np.zeros(len(combine), dtype=object)
    x = np.zeros(len(combine), dtype=object)
    # Create the figure for the comparison
    fig, ax = plt.subplots(num=f"{quantity}_comparison")
    # Iterate over all folders and plot the quantity values
    combine_index = 0
    for folder_name in context.folder_names:
        folder_ctx = context.folder_ctx(folder_name)
        quantity_results = folder_ctx.task_results(quantity, task.target)
        xdata = quantity_results[XAXIS_DICT[task.xaxis]]
        ydata = quantity_results[task_results[quantity]]
        # If not aggregating, plot each folder separately
        model = None
        if folder_name not in combine:
            folder_style = plot_styles.get(folder_name, PlotStyleConfig()).model_dump()
            models = [v['model'] for v in quantity_results.values()
                      if isinstance(v, dict) and 'model' in v]
            if models:
                model = models[0]
            plot_kwargs = dict(
                model_label=get_model_label(name, model) if model else None,
                **folder_style)
            plot_compare_task(ax, xdata, ydata, model, **plot_kwargs)
        # If aggregating, store the data together for later plotting
        else:
            y[combine_index] = unumpy.nominal_values(ydata)
            yerr[combine_index] = unumpy.std_devs(ydata)
            x[combine_index] = xdata
            combine_index += 1
    if combine:
        # Concatenate all data
        y = np.concatenate(y)
        yerr = np.concatenate(yerr)
        x = np.concatenate(x)
        x, y, yerr = average_repeats(x, y, yerr)
        if task.subtasks:
            model = _fit_subtask(x, unumpy.uarray(y, yerr), task.subtasks[0])
            model_label = get_model_label(name, model)
        plot_kwargs = dict(
            model_label=model_label if task.subtasks else None,
            **plot_styles.get("combine", PlotStyleConfig()).model_dump())
        plot_compare_task(ax, x, unumpy.uarray(y, yerr), model, **plot_kwargs)
    # Define the task plot keyword arguments for style and labels
    task_style = context.config.style.tasks.get(f"{name}_{quantity}",
                                                PlotStyleConfig()).model_dump()
    # Set the title of the plot
    if task_style["title"] is not None:
        plt.title(task_style["title"])
    # Set the labels and the axis scales
    plt.xlabel(XAXIS_LABELS[task.xaxis])
    plt.ylabel(YAXIS_LABELS.get(quantity, quantity))
    plt.xscale(task_style["xscale"])
    plt.yscale(task_style["yscale"])
    # Write the legend and show the plot
    write_legend(task_style["legend_label"], loc=task_style["legend_loc"])
    plt.tight_layout()
    if not task.show:
        plt.close(fig)
    # Add the figure to the context
    context.add_figure(f"compare_{quantity}", fig)
    return context


def drift(context: Context, task: DriftConfig) -> Context:
    """Calculate the gain and rate of the detector vs the drift voltage using the fit results
    obtained from the source data of multiple files.

    Parameters
    ---------
    context : Context
        The context object containing the fit results.
    task : DriftConfig
        The drift configuration instance.
    
    Returns
    -------
    context : Context
        The updated context object containing the drift results.
    """
    name = task.task
    target = task.target
    style = context.config.style.tasks.get(name, PlotStyleConfig()).model_dump()
    # Get the different file names and create arrays to store rate values and drift voltages
    file_names = context.file_names
    rates = np.zeros(len(file_names), dtype=object)
    drift_voltages = np.zeros(len(file_names))
    gain_vals = np.zeros(len(file_names), dtype=object)
    # Iterate over all files and calculate the rate values
    for i, file_name in enumerate(file_names):
        source = context.source(file_name)
        drift_voltages[i] = source.drift_voltage
        integration_time = source.real_time
        target_ctx = context.target_ctx(file_name, target)
        line_val = target_ctx.line_val
        gain_vals[i] = gain(context.config.source.w, line_val,
                            context.config.source.energy)
        # Calculate the threshold in charge and calculate the rate
        charge_thr = (task.energy_threshold / context.config.source.energy) * line_val
        hist = source.hist
        counts = hist.content[hist.bin_centers() > charge_thr.n].sum()
        rates[i] = counts / integration_time
    context.add_task_results(name, target, dict(drift_voltages=drift_voltages,
                                               gain_vals=gain_vals,
                                               rates=rates))
    # Prepare the quantities for plotting
    y = unumpy.nominal_values(gain_vals)
    yerr = unumpy.std_devs(gain_vals)
    y_rate = unumpy.nominal_values(rates)
    yerr_rate = unumpy.std_devs(rates)
    # Plot the gain vs drift voltage
    fig, ax1 = plt.subplots(num="drift_voltage")
    ax1.errorbar(drift_voltages, y, yerr=yerr, fmt=".k", label="Gain")
    ax1.set_xlabel("Drift Voltage [V]")
    ax1.set_ylabel("Gain", color=last_line_color())
    ax1.tick_params(axis="y", labelcolor=last_line_color())
    ax1.set_yscale(style["yscale"])
    # Plot the rate on a secondary y-axis if requested
    if task.show_rate:
        color = "red"
        ax2 = ax1.twinx()
        ax2.errorbar(drift_voltages, y_rate, yerr=yerr_rate, fmt=".", color=color, label="Rate")
        ax2.set_ylabel("Rate [counts/s]", color=color)
        ax2.tick_params(axis="y",labelcolor=color)
    axs = (ax1, ax2) if task.show_rate else (ax1, )
    write_legend(style["legend_label"], *axs, loc=style["legend_loc"])
    if not task.show:
        plt.close(fig)
    # Add the figure to the context
    context.add_figure(name, fig)
    return context


def plot_spectrum(context: Context, task: PlotConfig) -> Context:
    """Plot the spectra from the source data and overlay the fitted models for the specified
    targets.
    
    Parameters
    ---------
    context : Context
        The context object containing the source data the fit results.
    task : PlotConfig
        The plot configuration instance.

    Returns
    -------
    context : Context
        The context object (in future it will be updated with the figures).
    """
    # Get the file names from the sources keys
    name = task.task
    targets = task.targets
    file_names = context.file_names
    style = context.config.style.tasks.get(name, PlotStyleConfig()).model_dump()
    # Iterate over all files and plot the spectra with fitted models, if desired
    for file_name in file_names:
        source = context.source(file_name)
        # Create the plot figure and plot the spectrum and set the title
        fig = plt.figure(f"{source.file_path.stem}_{targets}")
        if style["title"] is not None:
            plt.title(style["title"])
        source.hist.plot(label=style["label"])
        # Plot the fitted models for the specified targets and get labels
        models = []
        if targets is not None:
            for target in targets:
                target_ctx = context.target_ctx(file_name, target)
                model = target_ctx.model
                model_label = get_label(task.task_labels, target_ctx)
                if style["fit_output"] and model_label is None:
                    model_label = f"{model.name()}"
                # Save the model for automatic xrange calculation
                models.append(model)
                model.plot(label=model_label, fit_output=style["fit_output"])
        # Set the x-axis range
        plt.xlim(task.xrange)
        if task.xrange is None:
            _xrange = get_xrange(source, models)
            plt.xlim(_xrange[0] * task.xmin_factor, _xrange[1] * task.xmax_factor)
        _label = style["legend_label"]
        # If voltage info is requested, add it to the legend
        if task.voltage and _label is not None:
            _label += f"\nBack: {source.voltage:>4.0f} V\nDrift: {source.drift_voltage:>4.0f} V"
        write_legend(_label, loc=style["legend_loc"])
        # Add the figure to the context
        context.add_figure(file_name, fig)
        plt.tight_layout()
        if not task.show:
            plt.close(fig)
    return context
