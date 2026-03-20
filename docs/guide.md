# **Analysis and configuration guide**

## Run the analysis

After the installation, the CLI can be used with the command:
```bash
mugpd config paths
```

To run the analysis, the requested arguments are the .yaml configuration file path and the data files or folders paths. The .yaml configuration file path is always the first argument.

To analyze one or more source files, the command needs a sequence of source file paths and a calibration with pulsed data as the last argument. This is an example of the analysis of two source files using the same calibration file:

```bash
mugpd path_config path_file0 path_file1 path_calibration
```

To analyze one or more folders, the order of the arguments is the same as the previous case, with the exception that no calibration file has to be specified, as it is supposed that each folder contains its own calibration file:

```bash
mugpd path_config path_folder0 path_folder1
```

The default directory to search for data files or folders is the data directory in the package root. If a file or a folder is inside this directory, there is no need to specify all the path of the folder, but the relative path from the data directory is enough to locate it.

It is also possible to save the analysis results (e.g. plots and numerical values) inside the results directory, which is automatically created in the user's home. This option can be enabled using the optional argument `-s` (or `--save`) in the CLI command. It is also possible to choose the format to use to save the plots (pdf or png). An example of command to save the results is:

```bash
mugpd path_config path_folder0 -s -f png
```

### File naming

To correctly analyze the data, the files have to be named in a specific way, to correctly identify file type, the voltages and also the chronological order.

#### Calibration files

For calibration files, the name has to be of the form (case-insensitive):

```txt
[any_prefix]ci[voltages][any_literal_suffix].mca
```

where voltages is a sequence of integers separated by `-` or `_`. An example of correct file name is `data_ci1-2-3-4mV.mca`.


#### Source files
For source files, the name must contain the information about the back `B[back_voltage]` and the drift `D[drift_voltage]` voltages. The order in which they appear and where they are written are not important, but in this case it is case-sensitive, so `B` and `D` must be capital letters. An example of correct name is `data_D1000_B300.mca`


#### Time trend files
When analyzing data and the chronological order is important, the naming convention is similar to that of source files, with the exceptions that the order of the voltages matters. In particular, the back voltage must be the last to be specified, and after that an index that indicates the order has to be written. The name should be of the following form:

```txt
[any_prefix]B[voltage]_[index].mca
```

An example of correct file name is `data_D1000B380_40.mca`


## Write the configuration file

To run the analysis, a configuration file must always be specified. This section explains how to write a correct configuration file.

The configuration file is a .yaml file which contains all the information to run the analysis and also for the plot style. This file allows to write an analysis pipeline in which each task can be configured.

**Warning:**  when a key is optional and you want to set it to the default value, all the line must be deleted, not only the value, otherwise a type error can be raised or a `None` value can be assigned to the key.

<!-- ### Acquisition

The acquisition dictionary stores information about the acquisition, such as the date of the acquisition, the name and type of the chip and other detector and source properties. These properties are stored as keys of the dictionary, and a value is assigned to each of them. 

The acquisition dictionary is optional and none of its field is mandatory

**Note:** currently these info are not being used for any purpose, but in the future they can be useful for some tasks.

```yaml
acquisition:
  date: 2026-01-01
  chip: W1a
  structure: 86.6 um
  gas: Ar
  w: 26.
  element: Fe55
  e_peak: 5.9
```
 -->

### Source

The source dictionary allows to set the properties of the source, such as the energy of the main emission line, and also the detector constants, such as the W-value of the gas.

This dictionary is optional, and none of its field is mandatory. In case a key is not specified, the analysis use the default value.

```yaml
source:
  energy: 5.9   # Optional, default is K-alpha of Fe55
  w: 26.0       # Optional, default is w-value of Ar
```


### Pipeline

The pipeline is the core of the analysis, where everything that has to be calculated is defined. Each step of the pipeline is a task that contains all the properties that are needed to configure and execute it. The pipeline is structured as a sequence of tasks. Each task is a dictionary, with its own key-value pairs. A task is defined by its name, and the other keys define its behaviour.

The tasks order in the configuration file does not affect execution, as priority is automatically assigned to the `calibration` task (which is mandatory for the pipeline) followed by the `fit_spec` task (which is optional, e.g. if you only want to plot the data without doing any analysis).

Apart from the `calibration` and `fit_spec` tasks, which are executed once at the beginning of the analysis, all the other tasks can be written multiple times, specifying different `target` or configuration parameters. As an example, if you have multiple emission lines in a spectrum and you want to estimate the resolution from each of them independently, it is possible to write a `resolution` task for each of them by specifying the target declared during the `fit_spec` subtasks. See the next sections for more details.

For a complete description of the possible keys of each task, please see [Tasks](configs.md).

#### Calibration

This task performs the calibration between the ADC counts of the multi-channel analyzer and the charge (or voltage). It is performed using the calibration pulse file specified in the command or located into the folder. This file contains data at fixed known voltages (which must be written in the name), and after fitting each pulse with a Gaussian curve, a linear fit of the peak positions is performed to find the conversion parameters.

```yaml
pipeline:

  - task: calibration
    charge_conversion: true     # Optional, whether to convert to voltage or charge
    show: false                 # Optional, plot the calibration results
```

#### Spectral fitting

This task performs the spectral fitting on one or multiple emission lines at the same time. The task is divided into subtasks, each of them defined by the `target` (a name given to the subtask), and the `model` to use for the emission line fit (which must be *Gaussian* or *Fe55Forest*). These keys are mandatory for all the subtasks.

A subtask also has another optional key, which is `fit_pars`, that allows to specify some properties of the fitting procedure. If the `fit_pars` key is written in the configuration file, at least one property must be specified, but none of them is mandatory.

```yaml
  - task: fit_spec
    subtasks:
      - target: main_peak
        model: Fe55Forest

      - target: escape_peak
        model: Gaussian
        fit_pars:               # Optional
          xmin: 2.0             # Optional, left range limit for the fit
          xmax: 4.              # Optional, right range limit for the fit
          num_sigma_left: 1.    # Optional, number of sigma to the left of the line center for the fit
          num_sigma_right: 1.   # Optional, number of sigma to the right of the line center for the fit
          absoulute_sigma: true # Optional, set absolute sigma
          p0: [1., 1., 1.]      # Optional, init parameters for the line fit
```

#### Gain estimate

This task performs the estimate of the gain using the spectral fitting results of a given `target`, previously specified during the *fit_spec* task.

If the analysis is performed on a single file, there are no other keys to specify. If the analysis is performed on multiple files or on one or multiple folders, the `fit` and `plot` can be specified. 

**Note:** no error is raised if these optional keys are specified during the analysis of a single file, but no fit will be performed and no plot will be shown.

```yaml
  - task: gain
    target: main_peak
    fit: true            # Optional, fit the data with an exponential model
    show: true           # Optional, plot gain vs back voltage
```

#### Gain trend with time

This task performs the study of the gain as a function of time. The gain is estimated in the same way as the *gain* task. For each source file, the time and the length of the acquisition are extracted from the header. The time info are combined together to get the variation of the gain with time.

The gain trend can also be analyzed using fitting subtasks, which allow to fit the data with a model or a composition of models from *aptapy.models*. These subtasks share the same syntax of the spectral fitting subtasks.

If more than one trend is visible in the same data, multiple targets can be specified, and the fit range can be adjusted to each trend.

```yaml
  - task: gain_trend
    target: main_peak
    subtasks:                         # Optional, fitting subtasks
      target: trend                   
      model: Exponential + Constant   # Composition of models 
```

#### Gain compare between folders

This task allows to compare the gain results of two or more different folders on the same plot. To execute this task, it is required that at least a `gain` task has been completed on a given `target` emission line.

It is also possible to combine the gain estimates from a list of folders specified in the `combine` key, and also perform a single exponential fit on the data from these folders.

If there are multiple data taken at a given voltage, the mean of the gain estimated from these files is calculated.

```yaml
  - task: compare_gain
    target: main_peak
    combine:                     # Optional, combine the data of the specified folders
      - folder0
      - folder1
```


#### Drift varying


#### Resolution estimate

This task performs the estimate of the resolution of the detector using the spectral fitting results of a given `target`, previously specified during the *fit_spec* task. This estimate is made using only the fitted FWHM of the line and the calibrated charge of the line center:
$$
\frac{\Delta E}{E} = \frac{\text{FWHM}}{E}.
$$
The result is reported as a percentage.

As for the gain task, the `show` key works only if the analysis is performed on multiple files or folders

```yaml
  - task: resolution
    target: main_peak
    show: true            # Optional, plot resolution vs back voltage
```

#### Resolution estimate with escape peak

This task performs the estimate of the resolution of the detector using the spectral fitting results of a main line emission and the correspondent escape peak. The two emission lines are specified by the `target_main` and `target_escape` keys. The resolution is estimated as:
$$
\frac{\Delta E}{E} = \frac{\text{FWHM}}{E_{main}} \frac{E_{main} - E_{peak}}{x_{main} - x_{peak}},
$$
where $E_{main}$ and $E_{peak}$ are the theoretical emission energies of the main and the escape peaks, and $x_{main}$ and $x_{peak}$ are the fitted line center positions. This estimate and the previous lead to the same result if the charge calibration has been correctly performed.

The `show` and `fit` keys can be specified if working on multiple files.

```yaml
  - task: resolution_escape
    target_main: main_peak
    target_escape: escape_peak
```

#### Resolution compare between folders

This task allows to compare the energy resolution between different folders. As for `compare_gain` task, you need first to perform a `resolution` task on a `target` to compare the results. 

You can combine the results of different folders by specifying a list with the names of folders to combine in the `combine` key.

```yaml
  - task: compare_resolution
    target: main_peak
    combine:      # Optional, combine the results from the specified folders
      - folder0
      - folder1
```

#### Plot the spectrum

This task is used to plot the spectrum of all the analyzed files. It is possible to plot the spectrum without performing the spectral fitting before writing only the name of the task.

In the case of spectral fitting and physical quantities estimate, it is possible to specify the `target` to plot, the general `label` of the plot, if you want to show the quantity estimates in the legend using `task_labels` and where to show the legend with `loc`. It is also possible to set a specific x-axis range for the plot using `xrange` or modify the automatic one by a factor on the left and/or on the right with `xmin_factor` and `xmax_factor`. If the `xrange` has been specified, it has the priority over the other two keys. You can decide whether to show the plots with the `show` key.

```yaml
  - task: plot
    targets:              # Optional, target fit to show
      - main_peak
      - escape_peak
    task_labels:          # Optional, estimated quantities to show in the legend
      - gain
    xrange: [0., 3.]      # Optional, the x-axis range to show on the plot
    xmin_fac: 0.5         # Optional, scale the automatic xrange left limit by a factor
    xmax_fac: 1.5         # Optional, scale the automatic xrange right limit by a factor
    show: true            # Optional, whether to show the plot. If false, they can still be saved.
```

### Style

The style dictionary allows to set the style, labels and titles of the plots. The main keys of this dictionary are `tasks` and `folders`. To each of them can be assigned other dictionaries, whose key is the name of a task or a folder. Inside the latter dictionaries, the style settings of the plots can be specified.

The `tasks` dictionary allows to modify the style and labels of the plots produced during tasks (e.g. `gain`, `resolution`, etc...).

The `folders` dictionary is useful when producing plots with comparison between different folders. The labels, color, marker and line style of data points and best-fit curves can be configured. It is also possible to configure the label and style of combined results specifying the key `combine`.

```yaml
style:
  # For tasks the syntax is the following  
  tasks:
    # Name of the task
    plot:
      # Configure the settings
      title: $^{55}$Fe spectrum
      legend_label: Chip
      label: null
  
  # For folders
  folders:
    # Specify the name of the folder
    folder0:  
      label: Folder 0 Data
      marker: .
      color: black
      linestyle: "-"
```

