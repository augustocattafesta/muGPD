"""Test for the fileio module.
"""

import datetime

import numpy as np

from mugpd.fileio import PulsatorFile, SourceFile


def test_pulse(datadir):
    """Test the PulsatorFile class for reading pulse file data."""
    file_path = datadir / "folder0/live_data_chip18112025_ci5-10-15_hvon.mca"
    pulses = PulsatorFile(file_path)

    assert np.array_equal(pulses.voltage, [5, 10, 15])
    assert pulses.num_pulses == len(pulses.voltage)


def test_source(datadir):
    """Test the SourceFile class for reading source file data."""
    file_source_path = datadir / "folder0/live_data_chip18112025_D1000_B370.mca"
    source = SourceFile(file_source_path)
    real_time = source.real_time

    assert source.drift_voltage == 1000.0
    assert source.voltage == 370.0
    assert np.isclose(real_time, 163.800000)
    assert source.start_time ==  datetime.datetime(2025, 11, 18, 11, 57, 6)
