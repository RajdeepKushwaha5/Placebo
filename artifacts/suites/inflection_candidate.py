"""A candidate test patch for the inflection subject.

Written by hand to exercise Placebo's audit on a second repository. It mixes a
test that pins real behaviour with one that asserts almost nothing, which is
what a generated patch typically looks like.
"""

import inflection


def test_camelize_upper_first():
    assert inflection.camelize("device_type") == "DeviceType"


def test_camelize_lower_first():
    assert inflection.camelize("device_type", False) == "deviceType"


def test_underscore_round_trip():
    assert inflection.underscore("DeviceType") == "device_type"


def test_pluralize_is_a_string():
    # Deliberately weak: true for almost any implementation.
    assert isinstance(inflection.pluralize("post"), str)
