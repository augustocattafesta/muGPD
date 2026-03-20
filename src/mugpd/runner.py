from collections.abc import Callable
from pathlib import Path

from ._logger import log
from .config import AppConfig
from .context import Context, FoldersContext
from .fileio import Folder, PulsatorFile, SourceFile, check_source_paths
from .tasks import (
    calibration,
    compare_gain,
    compare_resolution,
    compare_trend,
    drift,
    fit_peak,
    gain_task,
    plot_spectrum,
    resolution_escape,
    resolution_task,
)

TaskFunction = Callable[..., Context]
TaskFunctionFolders = Callable[..., FoldersContext]

TASK_REGISTRY: dict[str, TaskFunction] = {
    "gain": gain_task,
    "resolution": resolution_task,
    "resolution_escape": resolution_escape,
    "drift": drift,
    "plot": plot_spectrum,
}


FOLDERS_TASK_REGISTRY: dict[str, TaskFunctionFolders] = {
    "compare_gain": compare_gain,
    "compare_resolution": compare_resolution,
    "compare_trend": compare_trend,
}


def _run_single(
        config: AppConfig,
        *paths: str | Path
        ) -> Context:
    """Run the analysis pipeline defined in the configuration file on the given data files or
    folder.
    
    Arguments
    ----------
    config : AppConfig
        Configuration object.
    *paths : str | Path
        Paths to the data files or folder. If only one path is given, it is assumed to be a folder
        containing source files and at least a pulse file. Otherwise, the last path is assumed to
        be the pulse file and all preceding ones are source files.

    Returns
    -------
    context : Context
        Context object containing all the info and results of the analysis pipeline.
    """
    # Initialize the context with the configuration
    context = Context(config)
    # If only one path is given, we assume it is a folder containing source files and a pulse file.
    # Otherwise, the last path is the pulse file and all preceding ones are source files.
    if len(paths) == 1:
        data_folder = Folder(Path(paths[0]))
        source_file_paths = data_folder.source_files
        pulse_file_path = data_folder.pulse_file
    else:
        source_file_paths = [Path(p) for p in paths[:-1]]
        pulse_file_path = Path(paths[-1])
    context.paths = list(source_file_paths)
    # Run calibration task on the pulse file
    cal_config = config.calibration
    if cal_config is not None:
        log.info(f"Running calibration task on pulse file {pulse_file_path}")
        pulse = PulsatorFile(pulse_file_path)
        context.pulse = pulse
        context = calibration(context)
    else:
        raise RuntimeError("No calibration task found in configuration")
    # Load source files with the calculated calibration model
    calibration_model = context.conversion_model
    sources = [SourceFile(Path(p), calibration_model) for p in source_file_paths]
    # Run all fitting subtasks defined in the configuration file for each source file
    spec_fit_config = config.fit_spec
    for source in sources:
        log.info(f"Processing source file {source.file_path}")
        context.add_source(source)
        if spec_fit_config is not None:
            # Execute all fitting subtasks defined in the configuration file
            for subtask in spec_fit_config.subtasks:
                context = fit_peak(context=context, subtask=subtask)
    log.info("All source files processed for current folder")
    # Now we run all the tasks defined in the configuration file. The pipeline is sorted
    # so that the plotting task is always executed at the end (to compute resolution or gain).
    pipeline = sorted(config.pipeline, key=lambda t: 1 if t.task == "plot" else 0)
    for task in pipeline:
        # Skip tasks already executed and those marked to be skipped
        # We skip plot here because we want all the results to be in the context
        core_tasks = ["calibration", "spectrum_fitting"]
        if task.task in core_tasks or getattr(task, "skip", False):
            continue
        # Select the appropriate task function from the registry
        func = TASK_REGISTRY.get(task.task)
        if func:
            log.info(f"Task {task.task}: executing")
            context = func(context, task)
            log.success(f"Task {task.task}: completed")
    return context


def _run_folders(
        config: AppConfig,
        *folder_paths: Path
        ) -> FoldersContext:
    """Run the analysis pipeline defined in the configuration file on multiple data folders.

    Arguments
    ---------
    config : AppConfig
        Configuration object.
    *folder_paths: Path
        Paths to the data folders.
    
    Returns
    -------
    context : FoldersContext
        FoldersContext object containing all the info and results of the analysis pipeline for
        each folder.
    """
    # Initialize the folders context with the configuration
    context = FoldersContext(config)
    # Execute the analysis pipeline for each folder
    context.paths = list(folder_paths)
    for folder_path in folder_paths:
        log.info(f"Running analysis for folder {folder_path}")
        folder_ctx = _run_single(
            config,
            folder_path
        )
        log.success(f"Analysis completed for folder {folder_path}")
        context.add_folder(folder_path, folder_ctx)
    # After that all the folders have been analyzed, we can run the folder-level tasks
    pipeline = sorted(config.pipeline, key=lambda t: 1 if t.task == "plot" else 0)
    for task in pipeline:
        if task.task not in FOLDERS_TASK_REGISTRY:
            continue
        # Select the appropriate task function from the registry
        func = FOLDERS_TASK_REGISTRY.get(task.task)
        if func:
            log.info(f"Folder-level task: {task.task} executing")
            context = func(context, task)
            log.success(f"Folder-level task: {task.task} completed")
    return context


def run(config_file_path: str | Path,
        *paths: str | Path
        ) -> Context | FoldersContext:
    """Run the analysis pipeline defined in the configuration file on the given data files or
    folder. If only one path is given, it is assumed to be a folder containing source files and at
    least a pulse file. Otherwise, the last path is assumed to be the pulse file and all
    preceding ones are source files.

    Arguments
    ----------
    config_file_path : str | Path
        Path to the configuration file.
    *paths : str | Path
        Paths to the data files or folder.

    Returns
    -------
    context : Context | FoldersContext
        Context object containing all the info and results of the analysis pipeline.
    """
    # Load the configuration file
    log.info(f"Opening configuration file {Path(config_file_path).absolute()}")
    config = AppConfig.from_yaml(config_file_path)
    log.info(f"Configuration file loaded:\n{config}")
    # Check if the given paths are files or folders and run the appropriate analysis pipeline
    file_paths, path_type = check_source_paths(paths)
    input_paths = [str(Path(p)) for p in paths]
    config_path = str(Path(config_file_path).absolute())
    context: Context | FoldersContext
    if path_type == "file":
        log.info("Running analysis on single files")
        context = _run_single(config, *file_paths)
    elif path_type == "folder":
        log.info("Running analysis on folder(s)")
        context = _run_folders(config, *file_paths)
    else:
        raise ValueError("Invalid path type. Paths must be either all files or all folders.")
    context.set_run_metadata(config_path=config_path,
                             input_paths=input_paths,
                             path_type=path_type)
    return context
