"""Unit conversion tables for extraction `quantity` fields.

Implements openspec:data-extraction#units. Pure: no I/O.
"""

from __future__ import annotations

import math
import re
from typing import Any


class UnitError(ValueError):
    """E_UNIT: an unknown, unconvertible, or disallowed unit."""


# Dimensions and base units
_DIMENSIONS = {
    "time": "seconds",
    "mass": "grams",
    "length": "metres",
    "dose": "milligrams per kilogram",
}

# Canonical units and their factors to the dimension's base unit
_CANONICAL_UNITS = {
    "time": {
        "milliseconds": 0.001,
        "seconds": 1,
        "minutes": 60,
        "hours": 3600,
        "days": 86400,
        "weeks": 604800,
        "months": 2629800,
        "years": 31557600,
    },
    "mass": {
        "micrograms": 1e-6,
        "milligrams": 1e-3,
        "grams": 1,
        "kilograms": 1000,
        "ounces": 28.349523125,
        "pounds": 453.59237,
    },
    "length": {
        "micrometres": 1e-6,
        "millimetres": 0.001,
        "centimetres": 0.01,
        "metres": 1,
        "kilometres": 1000,
        "inches": 0.0254,
        "feet": 0.3048,
        "yards": 0.9144,
        "miles": 1609.344,
    },
    "dose": {
        "micrograms per kilogram": 0.001,
        "milligrams per kilogram": 1,
        "grams per kilogram": 1000,
    },
}

# Aliases and plural/singular forms
_ALIASES = {
    "time": {
        "ms": "milliseconds",
        "msec": "milliseconds",
        "s": "seconds",
        "sec": "seconds",
        "secs": "seconds",
        "second": "seconds",
        "min": "minutes",
        "mins": "minutes",
        "minute": "minutes",
        "h": "hours",
        "hr": "hours",
        "hrs": "hours",
        "hour": "hours",
        "d": "days",
        "day": "days",
        "wk": "weeks",
        "wks": "weeks",
        "week": "weeks",
        "mo": "months",
        "mos": "months",
        "month": "months",
        "y": "years",
        "yr": "years",
        "yrs": "years",
        "year": "years",
    },
    "mass": {
        "ug": "micrograms",
        "mcg": "micrograms",
        "microgram": "micrograms",
        "mg": "milligrams",
        "milligram": "milligrams",
        "g": "grams",
        "gm": "grams",
        "gram": "grams",
        "kg": "kilograms",
        "kilogram": "kilograms",
        "oz": "ounces",
        "ounce": "ounces",
        "lb": "pounds",
        "lbs": "pounds",
        "pound": "pounds",
    },
    "length": {
        "um": "micrometres",
        "micrometer": "micrometres",
        "micron": "micrometres",
        "micrometre": "micrometres",
        "mm": "millimetres",
        "millimeter": "millimetres",
        "millimetre": "millimetres",
        "cm": "centimetres",
        "centimeter": "centimetres",
        "centimetre": "centimetres",
        "m": "metres",
        "meter": "metres",
        "metre": "metres",
        "km": "kilometres",
        "kilometer": "kilometres",
        "kilometre": "kilometres",
        "in": "inches",
        "inch": "inches",
        "ft": "feet",
        "foot": "feet",
        "yd": "yards",
        "yard": "yards",
        "mi": "miles",
        "mile": "miles",
    },
    "dose": {
        "ug/kg": "micrograms per kilogram",
        "mcg/kg": "micrograms per kilogram",
        "mg/kg": "milligrams per kilogram",
        "g/kg": "grams per kilogram",
    },
}

# Pre-calculate all valid canonical names and aliases for collision checking
_ALL_CANONICAL: set[str] = set()
for dim_units in _CANONICAL_UNITS.values():
    _ALL_CANONICAL.update(dim_units.keys())
for dim_aliases in _ALIASES.values():
    _ALL_CANONICAL.update(dim_aliases.keys())
    _ALL_CANONICAL.update(dim_aliases.values())


class UnitRegistry:
    def __init__(self, extensions: dict[str, dict[str, float]] | None = None):
        self.extensions = extensions or {}
        # Merge built-in units with extensions
        self.units = {}
        for dim, units in _CANONICAL_UNITS.items():
            self.units[dim] = units.copy()

        if extensions:
            seen: set[str] = set()
            for dim, ext_units in extensions.items():
                if dim not in self.units:
                    raise UnitError(f"Unknown dimension: {dim}")
                for raw_name, factor in ext_units.items():
                    name = raw_name.strip().lower()
                    if not name:
                        raise UnitError("An extension unit needs a name.")
                    if name in _ALL_CANONICAL or name in seen:
                        raise UnitError(f"Extension name '{name}' collides with another unit.")
                    seen.add(name)
                    if not (
                        isinstance(factor, (int, float)) and math.isfinite(factor) and factor > 0
                    ):
                        raise UnitError(
                            f"Extension factor for '{name}' must be a positive finite number."
                        )
                    self.units[dim][name] = factor

    def normalise_unit_name(self, raw: str) -> str:
        if not raw:
            raise UnitError("Empty unit name")
        s = raw.strip().lower()
        # Handle micro signs
        s = s.replace("\u00b5", "u").replace("\u03bc", "u")

        # Check if it's a canonical name directly
        if (
            s in self.units.get("time", {})
            or s in self.units.get("mass", {})
            or s in self.units.get("length", {})
            or s in self.units.get("dose", {})
        ):
            return s

        # Check aliases
        for dim, _ in self.units.items():
            aliases = _ALIASES.get(dim, {})
            if s in aliases:
                return aliases[s]

        raise UnitError(f"Unknown unit: {raw}")

    def dimension_of(self, unit: str) -> str:
        norm = self.normalise_unit_name(unit)
        for dim, units in self.units.items():
            if norm in units:
                return dim
        raise UnitError(f"Unit '{unit}' does not belong to any known dimension.")

    def units_in(self, dimension: str) -> list[str]:
        if dimension not in self.units:
            raise UnitError(f"Unknown dimension: {dimension}")
        # Return canonical names sorted by factor ascending
        sorted_units = sorted(self.units[dimension].items(), key=lambda x: x[1])
        return [name for name, factor in sorted_units]

    def convert(self, value: float, from_unit: str, to_unit: str) -> float:
        dim_from = self.dimension_of(from_unit)
        dim_to = self.dimension_of(to_unit)
        if dim_from != dim_to:
            raise UnitError(f"Cannot convert {from_unit} ({dim_from}) to {to_unit} ({dim_to})")

        norm_from = self.normalise_unit_name(from_unit)
        norm_to = self.normalise_unit_name(to_unit)

        factor_from = self.units[dim_from][norm_from]
        factor_to = self.units[dim_to][norm_to]

        return value * factor_from / factor_to

    def parse_quantity(self, text: str) -> tuple[float, str]:
        # Match: (number) (optional space) (unit)
        # Supports scientific notation and negative numbers
        match = re.match(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(\S.*?)\s*$", text)
        if not match:
            raise UnitError(f"Could not parse quantity: {text}")

        try:
            value = float(match.group(1))
            unit = self.normalise_unit_name(match.group(2))
            return value, unit
        except ValueError:
            raise UnitError(f"Invalid number in quantity: {text}") from None

    def to_quantity_record(
        self, entered: str, *, target_unit: str, accepts_units: list[str] | None = None
    ) -> dict[str, Any]:
        try:
            val, unit = self.parse_quantity(entered)
        except UnitError:
            raise UnitError(f"Invalid entered quantity: {entered}") from None

        norm_unit = self.normalise_unit_name(unit)

        if accepts_units is not None:
            # Normalise all accepted units
            norm_accepts = [self.normalise_unit_name(u) for u in accepts_units]
            if norm_unit not in norm_accepts:
                raise UnitError(f"Unit '{unit}' not in accepts_units")

        norm_target = self.normalise_unit_name(target_unit)

        # Convert to target
        converted_val = self.convert(val, norm_unit, norm_target)

        # Rounding logic
        if math.isclose(converted_val, round(converted_val), abs_tol=1e-9):
            final_val: int | float = int(round(converted_val))
        else:
            final_val = round(converted_val, 10)

        return {
            "value": final_val,
            "unit": norm_target,
            "entered": entered,
        }


# Default registry for module-level functions
_DEFAULT_REGISTRY = UnitRegistry()


def normalise_unit_name(raw: str) -> str:
    return _DEFAULT_REGISTRY.normalise_unit_name(raw)


def dimension_of(unit: str) -> str:
    return _DEFAULT_REGISTRY.dimension_of(unit)


def units_in(dimension: str) -> list[str]:
    return _DEFAULT_REGISTRY.units_in(dimension)


def convert(value: float, from_unit: str, to_unit: str) -> float:
    return _DEFAULT_REGISTRY.convert(value, from_unit, to_unit)


def parse_quantity(text: str) -> tuple[float, str]:
    return _DEFAULT_REGISTRY.parse_quantity(text)


def to_quantity_record(
    entered: str, *, target_unit: str, accepts_units: list[str] | None = None
) -> dict[str, Any]:
    return _DEFAULT_REGISTRY.to_quantity_record(
        entered, target_unit=target_unit, accepts_units=accepts_units
    )
