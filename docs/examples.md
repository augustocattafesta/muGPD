# **Examples of Analysis**

To run the analysis, first you need to write the configuration file following the [Analysis and Configuration Guide](guide.md).

## Single file analysis

In this example, a basic analysis of a single source file is performed. See the configuration YAML file snippet for more details.

```yaml
--8<-- "docs/examples/single_example_config.yaml"
```

After writing the configuration file, the analysis can be launched from the command line interface with:

```bash
mugpd path_config path_source path_calibration
```

After the analysis is completed, the result is the following plot, showing the main emission line and the escape peak, along with the fit models and the legend showing the gain and energy resolution results:

![Fit](figures/single_example.png)

## Folder analysis

In this example, the analysis of a folder is performed. You can see from the configuration YAML file snippet below that the configuration file doesn't differ much from that for the single file analysis. Indeed, the configuration files are quite flexible and most of the tasks can be executed both on single and multiple files or folders. The main difference for some tasks is the possibility to specify particular keys that work only on multiple files, otherwise nothing is done.

```yaml
--8<-- "docs/examples/folder_example_config.yaml"
```

The command to run is:
```bash
mugpd path_config path_folder
```

Setting the `show` key to `true` for the `gain` and `resolution` tasks, the output plots are the following:

![Fit](figures/folder_gain.png)
![Fit](figures/folder_resolution.png)


## Noise spectrum fitting

In this example, a folder containing only a source file and a calibration file is analyzed to characterize the noise spectrum. The configuration file is similar to the previous ones, with the exception of the models used in the fitting subtasks. When a model different from a Gaussian or a line forest is used, the tool fits all the spectrum, with the exception of the first bin with positive content (this is useful for this task because the first bin doesn't have all the statistics, due to the MCA threshold). The analysis is performed with the following configuration file.

```yaml
--8<-- "docs/examples/noise_fit_config.yaml"
```

To run the analysis, the command is the same of all the others folder analysis:

```bash
mugpd path_config path_folder
```

In this example, the noise spectrum is fitted with an exponential model and a power-law model. The resulting plot is the following:

![Fit](figures/noise_fit.png)

## Analysis of gain variation with time

In this example, the analysis of a folder to study the gain variation with time is performed. The gain is estimated during the task, so it is not necessary to execute a `gain` task before. The gain is fitted in a fixed range with a composite model `StrecthedExponential + Constant`.

```yaml
--8<-- "docs/examples/gain_trend_example_config.yaml"
```

The command to run is the same as the [Folder Analysis](#folder-analysis) example. The output of the program is the following:

![Fit](figures/gain_trend.png)

## Gain and resolution comparison of two folders

In this example, two folders are analyzed to compare the gain and the energy resolution estimates. The gain data is combined together and fitted with a single exponential. The energy resolution is only compared. 

**Note:** to execute these tasks, it is necessary to first execute the `gain` or `resolution` tasks, and then

```yaml
--8<-- "docs/examples/folder_comparison_example_config.yaml"
```

To run this analysis the command is:

```bash
mugpd path_config path_folder0 path_folder1
```

The output is the following:

![Fit](figures/compare_gain.png)

![Fit](figures/compare_resolution.png)
