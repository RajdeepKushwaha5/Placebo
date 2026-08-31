"""Candidate tests."""

import pytest
import semver

def test_case_version_match():
    """Detects: semver/version.py:598 in Version.match: `0` -> `1` (constant)"""
    assert repr(semver.Version.parse("1.0.0").match(">=1.0.0")) == 'True'

def test_case_version_is_compatible():
    """Detects: semver/version.py:730 in Version.is_compatible: `False` -> `None` (return_value)"""
    assert repr(semver.Version.parse("0.1.0").is_compatible(semver.Version.parse("0.0.1"))) == 'False'
    assert repr(semver.Version.parse("0.0.1").is_compatible(semver.Version.parse("0.1.0"))) == 'False'

def test_case_version_match():
    """Detects: semver/version.py:599 in Version.match: `0` -> `1` (constant)"""
    assert repr(semver.Version.parse("1.0.0").match("<=1.0.0")) == 'True'
    assert repr(semver.Version.parse("1.0.0").match("<=0.9.9")) == 'False'
    assert repr(semver.Version.parse("2.0.0").match("<=1.0.0")) == 'False'
    assert repr(semver.Version.parse("1.0.0").match("<=1.0.0-alpha")) == 'False'
    assert repr(semver.Version.parse("1.0.0").match("<=1.0.0+build.1")) == 'True'
