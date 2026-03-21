from aptapy.plotting import plt

from mugpd.runner import run
from mugpd import ANALYSIS_DOCS

DOCS_PATH = ANALYSIS_DOCS
FIGURES_PATH = DOCS_PATH / "figures"
EXAMPLES_PATH = DOCS_PATH / "examples"

source_file_path = EXAMPLES_PATH / "data/single_file/source_w1a_D1000B340.mca"
calibration_file_path = EXAMPLES_PATH / "data/single_file/calibration_ci2-4-6-10mv.mca"
single_config_file_path = EXAMPLES_PATH / "single_example_config.yaml"
context = run(single_config_file_path, source_file_path, calibration_file_path)
single_example_fig = context._figures["source_w1a_D1000B340"]
single_example_fig.savefig(FIGURES_PATH / "single_example.png")

folder_path = EXAMPLES_PATH / "data/folder"
folder_conig_path = EXAMPLES_PATH / "folder_example_config.yaml"
context = run(folder_conig_path, folder_path)
folder_gain_fig = context._figures["gain"]
folder_gain_fig.savefig(FIGURES_PATH / "folder_gain.png")
folder_resolution_fig = context._figures["resolution"]
folder_resolution_fig.savefig(FIGURES_PATH / "folder_resolution.png")

plt.close("all")
gain_trend_path = EXAMPLES_PATH / "data/gain_trend"
gain_trend_config_path = EXAMPLES_PATH / "gain_trend_example_config.yaml"
context = run(gain_trend_config_path, gain_trend_path)
gain_trend_fig = context._figures["gain"]
gain_trend_fig.savefig(FIGURES_PATH / "gain_trend.png")

folder1_path = EXAMPLES_PATH / "data/folder1"
compare_config_path = EXAMPLES_PATH / "folder_comparison_example_config.yaml"
context = run(compare_config_path, folder_path, folder1_path)
compare_gain_fig = context._figures["compare_gain"]
compare_gain_fig.savefig(FIGURES_PATH / "compare_gain.png")
compare_resolution_fig = context._figures["compare_resolution"]
compare_resolution_fig.savefig(FIGURES_PATH / "compare_resolution.png")


