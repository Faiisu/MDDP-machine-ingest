"""Shared per-channel output-rate validation and decimation helpers."""

import math
import re


_CHANNEL_KEY_RE = re.compile(r'^(AI|DI)(\d+)$')


def normalize_channel_sample_rates(raw_rates, hardware_rate, section_length=500):
    """Return validated per-channel output-rate overrides.

    ``None``/empty values mean "inherit the source rate" and are omitted from
    the normalized mapping. AI channels can be stored no faster than the
    hardware clock. DI is an instant snapshot, so its source rate is one
    snapshot per acquisition section.
    """
    if raw_rates in (None, ''):
        return {}
    if not isinstance(raw_rates, dict):
        raise ValueError('CHANNEL_SAMPLE_RATES must be an object.')

    hardware_rate = float(hardware_rate)
    section_length = int(section_length)
    if not math.isfinite(hardware_rate) or hardware_rate <= 0:
        raise ValueError('CLOCK_RATE must be greater than zero.')
    if section_length < 1:
        raise ValueError('SECTION_LENGTH must be greater than zero.')

    normalized = {}
    for raw_key, raw_value in raw_rates.items():
        key = str(raw_key).upper()
        match = _CHANNEL_KEY_RE.fullmatch(key)
        if not match:
            raise ValueError(f'Invalid channel rate key: {raw_key}. Use AI0-AI15 or DI0-DI7.')

        channel_type = match.group(1)
        channel_number = int(match.group(2))
        max_channel = 15 if channel_type == 'AI' else 7
        if channel_number > max_channel:
            raise ValueError(f'{key} is outside the supported USB-4716 channel range.')

        if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
            continue
        try:
            rate = float(raw_value)
        except (TypeError, ValueError):
            raise ValueError(f'{key} sample rate must be a number or empty.')

        if not math.isfinite(rate) or rate <= 0:
            raise ValueError(f'{key} sample rate must be greater than zero.')

        source_rate = hardware_rate if channel_type == 'AI' else hardware_rate / section_length
        if rate > source_rate + 1e-9:
            raise ValueError(
                f'{key} sample rate cannot exceed its source rate ({source_rate:g} Hz).'
            )

        normalized[key] = int(rate) if rate.is_integer() else rate

    return normalized


class ChannelRateLimiter:
    """Emit source samples at configured lower rates using source timestamps."""

    def __init__(self, channel_rates=None):
        self.period_ns = {
            str(key).upper(): int(round(1_000_000_000 / float(rate)))
            for key, rate in (channel_rates or {}).items()
            if rate is not None and float(rate) > 0
        }
        self.next_emit_ns = {}

    def should_emit(self, channel_key, timestamp_ns):
        """Return True when this source sample should be persisted."""
        key = str(channel_key).upper()
        period_ns = self.period_ns.get(key)
        if period_ns is None:
            return True

        timestamp_ns = int(timestamp_ns)
        next_emit_ns = self.next_emit_ns.get(key)
        if next_emit_ns is None or timestamp_ns < next_emit_ns - period_ns:
            next_emit_ns = timestamp_ns

        if timestamp_ns < next_emit_ns:
            self.next_emit_ns[key] = next_emit_ns
            return False

        missed_periods = ((timestamp_ns - next_emit_ns) // period_ns) + 1
        next_emit_ns += missed_periods * period_ns
        self.next_emit_ns[key] = next_emit_ns
        return True
