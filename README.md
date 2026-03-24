# μGPD Analysis tool

This package provides a CLI tool to analyze spectra from a *Microgap Gas Pixel Detectors* (μGPDs) and infer the characteristics of the detector, such as gain and energy resolution.

## Installation

To install and use the package, follow these steps:

1. **Clone the repository**

```bash
git clone https://github.com/augustocattafesta/muGPD.git
```

2. **Install the package**

```bash
cd muGPD
pip install .
```

3. **Check if the installation is successfull**

```bash
mugpd --help
```
If no error is raised, the package has been correctly installed.

## Use the analysis tool

To analyze data from the detector, the command to run is:

```bash
mugpd config_path data_path
```

For more instructions on how to run an analysis, take a look at the [documentation](https://augustocattafesta.github.io/muGPD/).


## Web User Interface

The analysis tool includes a web UI to see the analysis results, with the possibility to filter between various properties of the detector. To launch the web UI, you have to run:

```bash
mugpd-web
```

The web app searches for analysis results in the default folder in the home directory. It is possible to indicate a different folder, as well as the host and the port where to run the app:

```bash
mugpd-web --results "$HOME/results" --host 127.0.0.1 --port 7860
```