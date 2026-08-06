# DAQ and machine telemetry simulator

Run the two backend services from this directory:

```bash
python config_service.py   # frontend API, port 8090
python simulator.py        # generates samples every second
```

The frontend reads and updates `config.json` through `GET /api/config`,
`PUT /api/config`, or `PATCH /api/config`. The simulator reloads the file every
five seconds. A `digital` channel progresses through the configured `stages`
(each stage is `0` or `1`) every `stage_period_seconds`; for example,
`"stages": [0, 1, 1, 0]` with a period of `2` holds each value for two
seconds. An `equation` channel evaluates a math expression using `t` (elapsed
seconds), `pi`, and functions from Python's `math` module.

A `machine` channel selects a named sensor model. All machine channels share
the same operating load and fault severity, so vibration, temperature,
current, displacement, and acoustic values change together in realistic ways.
The default configuration also writes simulator-only channel 90 as known
ground truth (`0=healthy`, `1=warning`, `2=critical`). Generate three complete
cycles immediately with:

```bash
../.venv/bin/python generate_training_data.py
```

See the parent [README](../README.md) for model training and real-time quality
inference instructions.

To add the live value of another simulated channel, set `depends_on` to its
channel number. The output is the channel's own digital/equation value plus the
sum of each dependency. A dependency can include a multiplier; for example,
`"depends_on": [{"channel": 1, "multiplier": 10}]` adds ten times channel 1.
In the frontend, enter this as `10 * channel 1`. Dependencies may chain, but
must not form a cycle.
