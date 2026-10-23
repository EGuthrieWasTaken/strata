"""Acceptance tests for strata.extract.units (openspec:data-extraction#units)."""

from __future__ import annotations

import itertools

import pytest

from strata.extract import units


def test_unit_error_is_a_value_error() -> None:
    assert issubclass(units.UnitError, ValueError)


def test_one_week_is_168_hours() -> None:
    assert units.convert(1, "weeks", "hours") == pytest.approx(168)


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("hr", "hours"),
        ("HRS", "hours"),
        (" Hour ", "hours"),
        ("wk", "weeks"),
        ("min", "minutes"),
        ("sec", "seconds"),
        ("yr", "years"),
        ("µg", "micrograms"),
        ("μg", "micrograms"),
        ("mcg", "micrograms"),
        ("ug", "micrograms"),
        ("lbs", "pounds"),
        ("cm", "centimetres"),
        ("centimeter", "centimetres"),
        ("feet", "feet"),
        ("foot", "feet"),
        ("inch", "inches"),
        ("m", "metres"),
        ("mg/kg", "milligrams per kilogram"),
        ("ug/kg", "micrograms per kilogram"),
        ("µg/kg", "micrograms per kilogram"),
    ],
)
def test_alias_normalisation(raw: str, canonical: str) -> None:
    assert units.normalise_unit_name(raw) == canonical


def test_dimension_of() -> None:
    assert units.dimension_of("hours") == "time"
    assert units.dimension_of("kg") == "mass"
    assert units.dimension_of("miles") == "length"
    assert units.dimension_of("mg/kg") == "dose"


def test_units_in_each_dimension() -> None:
    assert units.units_in("time") == [
        "milliseconds",
        "seconds",
        "minutes",
        "hours",
        "days",
        "weeks",
        "months",
        "years",
    ]
    assert set(units.units_in("mass")) == {
        "micrograms",
        "milligrams",
        "grams",
        "kilograms",
        "ounces",
        "pounds",
    }
    assert units.units_in("length")[0] == "micrometres"
    assert units.units_in("length")[-1] == "miles"  # 1609 m sorts after 1000 m
    assert units.units_in("dose") == [
        "micrograms per kilogram",
        "milligrams per kilogram",
        "grams per kilogram",
    ]


@pytest.mark.parametrize(
    ("value", "src", "dst", "expected"),
    [
        (90, "minutes", "hours", 1.5),
        (1, "days", "hours", 24),
        (2.5, "kilograms", "grams", 2500),
        (1, "pounds", "kilograms", 0.45359237),
        (1, "inches", "centimetres", 2.54),
        (1, "miles", "kilometres", 1.609344),
        (500, "micrograms", "milligrams", 0.5),
        (5, "mg/kg", "ug/kg", 5000),
        (1, "months", "days", 30.4375),
        (1, "years", "days", 365.25),
        (3, "hours", "hours", 3),
    ],
)
def test_known_conversions(value: float, src: str, dst: str, expected: float) -> None:
    assert units.convert(value, src, dst) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("dimension", ["time", "mass", "length", "dose"])
def test_round_trip_every_pair(dimension: str) -> None:
    names = units.units_in(dimension)
    assert len(names) >= 3
    for a, b in itertools.permutations(names, 2):
        there = units.convert(7.3, a, b)
        assert units.convert(there, b, a) == pytest.approx(7.3, rel=1e-12)


def test_cross_dimension_conversion_is_an_error() -> None:
    with pytest.raises(units.UnitError):
        units.convert(1, "hours", "grams")
    with pytest.raises(units.UnitError):
        units.convert(1, "mg/kg", "mg")


def test_unknown_unit_is_an_error() -> None:
    with pytest.raises(units.UnitError):
        units.convert(1, "fortnights", "hours")
    with pytest.raises(units.UnitError):
        units.dimension_of("furlongs")
    with pytest.raises(units.UnitError):
        units.normalise_unit_name("")
    with pytest.raises(units.UnitError):
        units.units_in("luminosity")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 week", (1.0, "weeks")),
        ("1.5h", (1.5, "hours")),
        ("30 min", (30.0, "minutes")),
        ("  2 days ", (2.0, "days")),
        ("-3 hrs", (-3.0, "hours")),
        ("1e2 s", (100.0, "seconds")),
        ("5 mg/kg", (5.0, "milligrams per kilogram")),
    ],
)
def test_parse_quantity(text: str, expected: tuple[float, str]) -> None:
    assert units.parse_quantity(text) == expected


@pytest.mark.parametrize("text", ["week", "", "abc", "1 2 weeks", "1 parsecs", "3"])
def test_parse_quantity_rejects_bad_text(text: str) -> None:
    with pytest.raises(units.UnitError):
        units.parse_quantity(text)


def test_quantity_record_week_to_hours() -> None:
    record = units.to_quantity_record(
        "1 week", target_unit="hours", accepts_units=["minutes", "hours", "days", "weeks"]
    )
    assert record == {"value": 168, "unit": "hours", "entered": "1 week"}
    assert isinstance(record["value"], int)


def test_quantity_record_keeps_fractions() -> None:
    record = units.to_quantity_record("90 min", target_unit="hours")
    assert record == {"value": 1.5, "unit": "hours", "entered": "90 min"}
    assert isinstance(record["value"], float)


def test_quantity_record_rounds_float_noise() -> None:
    record = units.to_quantity_record("1 min", target_unit="hours")
    assert record["value"] == pytest.approx(1 / 60, abs=1e-10)
    assert len(str(record["value"]).split(".")[1]) <= 10


def test_quantity_record_target_unit_may_be_an_alias() -> None:
    record = units.to_quantity_record("1 week", target_unit="hrs")
    assert record["unit"] == "hours"
    assert record["value"] == 168


def test_quantity_record_accepts_units_may_be_aliases() -> None:
    record = units.to_quantity_record("1 wk", target_unit="hours", accepts_units=["hrs", "wk"])
    assert record["value"] == 168


def test_quantity_record_rejects_unit_outside_accepts_units() -> None:
    with pytest.raises(units.UnitError):
        units.to_quantity_record(
            "2 months", target_unit="hours", accepts_units=["minutes", "hours", "days", "weeks"]
        )


def test_quantity_record_rejects_unknown_unit() -> None:
    with pytest.raises(units.UnitError):
        units.to_quantity_record("1 fortnight", target_unit="hours")


def test_quantity_record_rejects_unconvertible_unit() -> None:
    with pytest.raises(units.UnitError):
        units.to_quantity_record("2 kg", target_unit="hours")


def test_project_extension_adds_a_unit() -> None:
    registry = units.UnitRegistry({"time": {"fortnights": 1209600.0}})
    assert registry.dimension_of("fortnights") == "time"
    assert registry.convert(1, "fortnights", "days") == pytest.approx(14)
    assert registry.parse_quantity("2 fortnights") == (2.0, "fortnights")
    assert registry.to_quantity_record("2 fortnights", target_unit="days") == {
        "value": 28,
        "unit": "days",
        "entered": "2 fortnights",
    }
    assert "fortnights" in registry.units_in("time")


def test_project_extension_does_not_leak_into_the_default_registry() -> None:
    units.UnitRegistry({"time": {"fortnights": 1209600.0}})
    with pytest.raises(units.UnitError):
        units.convert(1, "fortnights", "days")


def test_extension_in_another_dimension() -> None:
    registry = units.UnitRegistry({"length": {"furlongs": 201.168}})
    assert registry.convert(1, "furlongs", "metres") == pytest.approx(201.168)


@pytest.mark.parametrize(
    "extensions",
    [
        {"luminosity": {"candela": 1.0}},
        {"time": {"hours": 3601.0}},
        {"time": {"hr": 3601.0}},
        {"time": {"zero": 0}},
        {"time": {"negative": -5.0}},
        {"time": {"infinite": float("inf")}},
        {"time": {"nan": float("nan")}},
    ],
)
def test_bad_extensions_are_rejected(extensions: dict[str, dict[str, float]]) -> None:
    with pytest.raises(units.UnitError):
        units.UnitRegistry(extensions)


def test_extension_names_are_lowercased_and_stripped() -> None:
    registry = units.UnitRegistry({"time": {"  Fortnights ": 1209600.0}})
    assert registry.convert(1, "FORTNIGHTS", "days") == pytest.approx(14)


@pytest.mark.parametrize(
    "extensions",
    [{"time": {"  ": 5.0}}, {"time": {"fortnights": 5.0}, "length": {"fortnights": 5.0}}],
)
def test_empty_and_duplicate_extension_names_are_rejected(
    extensions: dict[str, dict[str, float]],
) -> None:
    with pytest.raises(units.UnitError):
        units.UnitRegistry(extensions)


def test_multi_word_units_parse() -> None:
    assert units.parse_quantity("5 milligrams per kilogram") == (5.0, "milligrams per kilogram")
    assert units.parse_quantity("3. hours") == (3.0, "hours")
    assert units.parse_quantity(".5 h") == (0.5, "hours")
