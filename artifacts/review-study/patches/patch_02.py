"""Candidate tests."""

import pytest
import semver

def test_case_version_parse():
    """Detects: semver/version.py:637 in Version.parse: `%` -> `*` (arithmetic)

     expected values
    
    """
    with pytest.raises(TypeError) as excinfo:
        semver.Version.parse(3.14)
    assert str(excinfo.value) == "not expecting type '<class 'float'>'"

def test_case_version_is_compatible():
    """Detects: semver/version.py:729 in Version.is_compatible: `4` -> `5` (constant)

     expected values
    
    """
    assert repr(semver.Version.parse("0.0.0+0").is_compatible(semver.Version.parse("0.0.0"))) == 'True'

def test_case_version_match():
    """Detects: semver/version.py:598 in Version.match: `0` -> `1` (constant)

     expected values
    
    """
    assert repr(semver.Version.parse("0.0.0").match(">=0.0.0")) == 'True'
    assert repr(semver.Version.parse("0.0.0").match(">=0.0.0+0")) == 'True'
    assert repr(semver.Version.parse("0.0.0+0").match(">=0.0.0")) == 'True'

def test_case_version_is_compatible():
    """Detects: semver/version.py:730 in Version.is_compatible: `False` -> `None` (return_value)

     expected values
    
    """
    assert repr(semver.Version.parse("0.0.0").is_compatible(semver.Version.parse("0.0.0-alpha"))) == 'False'
    assert repr(semver.Version.parse("0.0.0-alpha").is_compatible(semver.Version.parse("0.0.0"))) == 'False'

def test_case_version_is_compatible():
    """Detects: semver/version.py:729 in Version.is_compatible: `4` -> `5` (constant)

     expected values
    
    """
    assert repr(semver.Version.parse("0.0.0").is_compatible(semver.Version.parse("0.0.0+0"))) == 'True'

def test_case_version_match():
    """Detects: semver/version.py:599 in Version.match: `0` -> `1` (constant)

     expected values
    
    """
    assert repr(semver.Version.parse("0.0.0").match("<=0.0.0")) == 'True'
    assert repr(semver.Version.parse("0.0.0").match("<=0.0.0+0")) == 'True'
    assert repr(semver.Version.parse("0.0.0+0").match("<=0.0.0")) == 'True'
