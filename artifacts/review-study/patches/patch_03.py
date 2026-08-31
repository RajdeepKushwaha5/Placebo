"""Candidate tests."""

import pytest
import semver

def test_case_version___lt():
    """Detects: semver/version.py:475 in Version.__lt__: `<` -> `<=` (comparison_boundary)"""
    assert repr(semver.Version.parse("1.0.0") < semver.Version.parse("1.0.0")) == 'False'

def test_case_version_bump_minor():
    """Detects: semver/version.py:292 in Version.bump_minor: `1` -> `2` (constant)"""
    assert repr(semver.Version.parse("3.4.5").bump_minor()) == 'Version(major=3, minor=5, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("2.9.9").bump_minor()) == 'Version(major=2, minor=10, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("3.4.9").bump_minor()) == 'Version(major=3, minor=5, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.0.0").bump_minor()) == 'Version(major=1, minor=1, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("3.4.0").bump_minor()) == 'Version(major=3, minor=5, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("3.3.9").bump_minor()) == 'Version(major=3, minor=4, patch=0, prerelease=None, build=None)'

def test_case_version_parse():
    """Detects: semver/version.py:636 in Version.parse: `not ` -> `` (negation)"""
    assert repr(semver.Version.parse("1.0.0").major) == '1'
    assert repr(semver.Version.parse("1.0.0").minor) == '0'
    assert repr(semver.Version.parse("1.0.0").patch) == '0'
    assert repr(semver.Version.parse("1.0.0-pre").prerelease) == "'pre'"
    assert repr(semver.Version.parse("1.0.0+build").build) == "'build'"
    with pytest.raises(AttributeError):
        semver.Version.parse("1.2.3").is_prerelease

def test_case_version_finalize_version():
    """Detects: semver/version.py:554 in Version.finalize_version: `cls(self.major, self.minor, self.patch)` -> `None` (return_value)"""
    assert repr(semver.Version.parse("1.2.3-rc.5").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3+build.4").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3-alpha.1").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3-beta.99").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3-0.3.7").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3+04").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'

def test_case_version___getitem():
    """Detects: semver/version.py:514 in Version.__getitem__: `and` -> `or` (boolean_logic)"""
    assert repr(semver.Version.parse("1.0.0")[0]) == '1'
    assert repr(semver.Version.parse("1.0.0")[slice(None, None, -1)]) == '(0, 0, 1)'
    assert repr(semver.Version.parse("1.0.0")[1]) == '0'

def test_case_version___gt():
    """Detects: semver/version.py:483 in Version.__gt__: `>` -> `>=` (comparison_boundary)"""
    assert repr(semver.VersionInfo(1, 0, 0) > semver.VersionInfo(1, 0, 0)) == 'False'

def test_case_version_match():
    """Detects: semver/version.py:580 in Version.match: `0` -> `1` (constant)"""
    assert repr(semver.Version.parse("1.0.0").match(">1.0.0")) == 'False'
    assert repr(semver.Version.parse("1.0.0").match("<1.0.0")) == 'False'
    assert repr(semver.Version.parse("2.0.0").match(">1.0.0")) == 'True'
    assert repr(semver.Version.parse("0.0.0").match("<1.0.0")) == 'True'
