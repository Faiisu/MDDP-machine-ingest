import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


SERVICE_DIR = Path(__file__).parents[1]
SIM_DIR = SERVICE_DIR / "sim-data"
sys.path.insert(0, str(SERVICE_DIR))


def load_simulator():
    spec = importlib.util.spec_from_file_location("machine_simulator", SIM_DIR / "simulator.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


simulator = load_simulator()
from machine_ml import infer_latest, read_json, train_model  # noqa: E402


def simulated_frame(config, duration=300):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for elapsed in range(duration):
        timestamp = start + timedelta(seconds=elapsed)
        values = simulator.values_for_channels(config["channels"], elapsed, config["machine"])
        rows.extend((timestamp, channel, value) for channel, value in values.items())
    return pd.DataFrame(rows, columns=["time", "channel", "value"])


def test_machine_faults_raise_related_sensor_values():
    machine = {"cycle_seconds": 300, "normal_fraction": 0.6, "warning_fraction": 0.25}
    healthy_vibration = simulator.machine_signal_value("vibration_mm_s", 60, machine)
    critical_vibration = simulator.machine_signal_value("vibration_mm_s", 280, machine)
    healthy_temperature = simulator.machine_signal_value("bearing_temperature_c", 60, machine)
    critical_temperature = simulator.machine_signal_value("bearing_temperature_c", 280, machine)

    assert simulator.machine_signal_value("health_state", 60, machine) == 0
    assert simulator.machine_signal_value("health_state", 210, machine) == 1
    assert simulator.machine_signal_value("health_state", 280, machine) == 2
    assert critical_vibration > healthy_vibration
    assert critical_temperature > healthy_temperature


def test_model_learns_relationships_and_classifies_machine_quality():
    config = read_json(SIM_DIR / "config.json")
    frame = simulated_frame(config)
    model, report = train_model(frame, config)

    assert model["schema"] == "machine-quality-model/v1"
    assert model["thresholds"]["source"] == "simulator_ground_truth_channel_90"
    assert report["strongest_relationships"]
    start = frame["time"].min()
    assert infer_latest(frame[frame["time"] <= start + timedelta(seconds=60)], model)["machine_quality"]["status"] == "healthy"
    assert infer_latest(frame[frame["time"] <= start + timedelta(seconds=210)], model)["machine_quality"]["status"] == "warning"
    assert infer_latest(frame[frame["time"] <= start + timedelta(seconds=280)], model)["machine_quality"]["status"] == "critical"


if __name__ == "__main__":
    test_machine_faults_raise_related_sensor_values()
    test_model_learns_relationships_and_classifies_machine_quality()
    print("machine quality tests passed")
