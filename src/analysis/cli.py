import argparse

from aptapy.plotting import plt

from analysis import ANALYSIS_RESULTS
from analysis.runner import run

__description__ = """
Analysis CLI tool for processing and visualizing data collected with μGPDs. The workflow starts
with a calibration step using pulsed data files. The resulting calibrated data is then used to
perform the analysis of the provided spectra. The results produced by the analysis can be used
to characterize the detector.
The tasks to execute are defined in the provided configuration .yaml file. To see how to
create the configuration file, refer to the documentation: 
https://augustocattafesta.github.io/master_thesis/
"""

def main():
    """Main function for the analysis CLI."""
    parser = argparse.ArgumentParser(
        prog="analysis",
        description=__description__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )

    parser.add_argument(
        "config",
        help="Path to the analysis configuration .yaml file.")

    parser.add_argument(
        "paths",
        nargs="+",
        help="Paths to source and calibration files or folders. If multiple files are provided, " \
        "the calibration file should always be the last file. If folders are provided, there is" \
        "no need to specify calibration files separately as they will be searched for in each" \
        "folder.")

    parser.add_argument(
        "-s", "--save",
        action="store_true",
        help=f"Save figures and results to the analysis results folder {ANALYSIS_RESULTS}"
    )

    parser.add_argument(
        "-f", "--format",
        default="png",
        choices=["png", "pdf"],
        help="Format of the saved figures"
    )

    args = parser.parse_args()
    # Run the analysis pipeline with the provided configuration and paths
    context = run(args.config, *args.paths)
    # Plot results if available
    plt.tight_layout()
    # Save results if specified
    if args.save:
        context.save(ANALYSIS_RESULTS, fig_format=args.format)
    plt.show()


if __name__ == "__main__":
    main()
