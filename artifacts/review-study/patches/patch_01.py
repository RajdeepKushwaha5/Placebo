"""Candidate tests."""

import pytest
import semver

def test_case_version_bump_minor():
    ver = semver.VersionInfo.parse("3.4.5")
    expected = semver.VersionInfo(major=3, minor=5, patch=0)
    assert ver.bump_minor() == expected

def test_case_version_finalize_version():
    version1 = semver.Version.parse('1.2.3-rc.5')
    version2 = semver.Version.parse('1.2.3')

    assert str(version1.finalize_version()) == '1.2.3'
    assert version1.finalize_version() != None

def test_case_version___getitem():
    ver = semver.Version.parse("3.4.5")
    
    # Test with negative slice start
    try:
        part = ver[-1:0]
        assert False, "Expected IndexError but got no exception"
    except IndexError:
        pass
    
    # Test with positive slice start and stop
    part = ver[0:2]
    assert part == (3, 4)

def test_case_version___gt():
    version1 = semver.VersionInfo.parse("1.0.0")
    version2 = semver.VersionInfo.parse("1.0.0")

    # The correct implementation returns False for equality, but the regression
    # changes it to return True.
    assert not version1 > version2

def test_case_version_match():
    version = semver.Version.parse("1.0.0")
    match_expr = ">1.0.0"
    
    # Correct behavior: should return False
    assert not version.match(match_expr)

    match_expr = "<1.0.0"
    
    # Correct behavior: should return False
    assert not version.match(match_expr)
