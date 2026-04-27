"""Semantic signal-selector helpers shared by preprocessing and widgets."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Optional

from bodaqs_analysis.sensor_aliases import canonical_end, canonical_sensor_id, end_from_sensor

logger = logging.getLogger(__name__)


SIGNAL_SELECTOR_FIELDS = {"sensor", "end", "quantity", "domain", "unit"}


def selector_matches_signal(signal_info: Mapping[str, Any], selector: Mapping[str, Any]) -> bool:
    """Return True when a signal-registry entry satisfies a semantic selector."""
    for key in ("sensor", "end", "quantity", "domain", "unit"):
        expected = selector.get(key)
        if expected is None or (isinstance(expected, str) and not expected.strip()):
            continue

        actual = signal_info.get(key)
        if key == "sensor":
            if canonical_sensor_id(actual) != canonical_sensor_id(expected):
                return False
        elif key == "end":
            expected_end = canonical_end(expected) or end_from_sensor(expected)
            actual_end = canonical_end(actual) or end_from_sensor(signal_info.get("sensor"))
            if not expected_end or expected_end != actual_end:
                return False
        elif key == "unit":
            if str(actual or "").strip() != str(expected).strip():
                return False
        else:
            if str(actual or "").strip().lower() != str(expected).strip().lower():
                return False

    return True


def resolve_signal_selector(
    session: Mapping[str, Any],
    selector: Optional[Mapping[str, Any]],
    *,
    purpose: str,
    allow_missing: bool = True,
) -> Optional[str]:
    """Resolve a selector to exactly one dataframe column in ``session['meta']['signals']``."""
    if selector is None:
        return None
    if not isinstance(selector, Mapping) or not selector:
        raise ValueError(f"{purpose} selector must be a non-empty object")

    signals = ((session.get("meta") or {}).get("signals") or {})
    if not isinstance(signals, Mapping):
        signals = {}

    matches = [
        str(col)
        for col, info in signals.items()
        if isinstance(info, Mapping) and selector_matches_signal(info, selector)
    ]
    if not matches:
        if allow_missing:
            logger.info("%s selector did not match any signal: selector=%s", purpose, dict(selector))
            return None
        raise ValueError(f"{purpose} selector did not match any signal: selector={dict(selector)!r}")
    if len(matches) > 1:
        raise ValueError(f"{purpose} selector matched multiple signals: selector={dict(selector)!r} matches={matches}")
    return matches[0]
