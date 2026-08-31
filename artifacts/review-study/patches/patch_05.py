"""Candidate tests."""

import pytest
import semver

def test_case_version_bump_minor():
    ver = semver.Version.parse("3.4.5")
    expected_version = semver.Version(major=3, minor=5, patch=0, prerelease=None, build=None)
    actual_version = ver.bump_minor()
    assert actual_version == expected_version

def test_case_version_finalize_version():
    version = semver.Version.parse('1.2.3-rc.5')
    assert str(version.finalize_version()) == '1.2.3'

def test_case_version___gt():
    # Define a version object and an equivalent version for comparison
    v1 = semver.VersionInfo.parse("1.0.0")
    v2 = semver.VersionInfo.parse("1.0.0")

    # The correct implementation should return False because the versions are equal
    assert not v1.__gt__(v2)

def test_case_version_match():
    version = semver.Version.parse("2.0.0")
    assert version.match(">1.0.0") == True
    assert version.match("<3.0.0") == True
    assert version.match(">=2.0.0") == True
    assert version.match("<=2.0.0") == True
    assert version.match("==2.0.0") == True
    assert version.match("!=1.0.0") == True
