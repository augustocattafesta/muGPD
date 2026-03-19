"""Module to handle logging for the analysis pipeline.
"""

import sys
import time

from loguru import logger


class AnalysisLogger:
    """Logger class for the analysis pipeline.
    """
    def __init__(self, level="INFO") -> None:
        """Class constructor.
        """
        self.start_time = time.time()
        self.level = level
        self._configure()

    def _elapsed_format(self) -> str:
        """Format the elapsed time since the start of the analysis pipeline.
        """
        seconds = time.time() - self.start_time
        minutes, seconds = divmod(seconds, 60)
        return f"{int(minutes):02d}:{seconds:05.2f}"

    def _patcher(self, record) -> None:
        """Patcher function for the loguru logger to add the elapsed time to the log record.
        """
        record["extra"]["elapsed"] = self._elapsed_format()

    def _configure(self):
        """Configure the loguru logger to use the custom patcher and format.
        """
        logger.remove()
        fmt = (
            "<green>[{extra[elapsed]}]</green> | "
            "<level>{level: <8}</level> |"
            " <cyan>{message}</cyan>"
        )
        logger.configure(patcher=self._patcher)
        logger.add(sys.stderr, format=fmt, colorize=True, level=self.level)

    def reset_timer(self):
        """Reset the timer for the elapsed time.
        """
        self.start_time = time.time()

    @property
    def log(self):
        """Return the logger instance.
        """
        return logger

log = AnalysisLogger().log
