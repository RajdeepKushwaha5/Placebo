"""An unedited pull request of agent-written tests.

Assembled by scripts/build_as_generated_patch.py from the raw output of every
generation condition in this project. No test was hand-written, reordered by
quality, or removed. This is the input to `scripts/run_audit.py`.
"""

import pytest
import semver



# fault detected: semver/version.py:475 in Version.__lt__: `<` -> `<=` (comparison_boundary)
# mutant id: 03fe90d993fa6512
def test_ai_d_01():
    """Detects: semver/version.py:475 in Version.__lt__: `<` -> `<=` (comparison_boundary)"""
    assert repr(semver.Version.parse("1.0.0") < semver.Version.parse("1.0.0")) == 'False'


# fault detected: semver/version.py:292 in Version.bump_minor: `1` -> `2` (constant)
# mutant id: 0311cef58a002912
def test_ai_d_02():
    """Detects: semver/version.py:292 in Version.bump_minor: `1` -> `2` (constant)"""
    assert repr(semver.Version.parse("3.4.5").bump_minor()) == 'Version(major=3, minor=5, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("2.9.9").bump_minor()) == 'Version(major=2, minor=10, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("3.4.9").bump_minor()) == 'Version(major=3, minor=5, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.0.0").bump_minor()) == 'Version(major=1, minor=1, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("3.4.0").bump_minor()) == 'Version(major=3, minor=5, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("3.3.9").bump_minor()) == 'Version(major=3, minor=4, patch=0, prerelease=None, build=None)'


# fault detected: semver/version.py:636 in Version.parse: `not ` -> `` (negation)
# mutant id: 5c7e1209a4ecd4ba
def test_ai_d_03():
    """Detects: semver/version.py:636 in Version.parse: `not ` -> `` (negation)"""
    assert repr(semver.Version.parse("1.0.0").major) == '1'
    assert repr(semver.Version.parse("1.0.0").minor) == '0'
    assert repr(semver.Version.parse("1.0.0").patch) == '0'
    assert repr(semver.Version.parse("1.0.0-pre").prerelease) == "'pre'"
    assert repr(semver.Version.parse("1.0.0+build").build) == "'build'"
    with pytest.raises(AttributeError):
        semver.Version.parse("1.2.3").is_prerelease


# fault detected: semver/version.py:554 in Version.finalize_version: `cls(self.major, self.minor, self.patch)` -> `None` (return_value)
# mutant id: 0723feea7643f22a
def test_ai_d_04():
    """Detects: semver/version.py:554 in Version.finalize_version: `cls(self.major, self.minor, self.patch)` -> `None` (return_value)"""
    assert repr(semver.Version.parse("1.2.3-rc.5").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3+build.4").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3-alpha.1").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3-beta.99").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3-0.3.7").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3+04").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'


# fault detected: semver/version.py:514 in Version.__getitem__: `and` -> `or` (boolean_logic)
# mutant id: 2efccfe40d947649
def test_ai_d_05():
    """Detects: semver/version.py:514 in Version.__getitem__: `and` -> `or` (boolean_logic)"""
    assert repr(semver.Version.parse("1.0.0")[0]) == '1'
    assert repr(semver.Version.parse("1.0.0")[slice(None, None, -1)]) == '(0, 0, 1)'
    assert repr(semver.Version.parse("1.0.0")[1]) == '0'


# fault detected: semver/version.py:483 in Version.__gt__: `>` -> `>=` (comparison_boundary)
# mutant id: 085c382c12637d90
def test_ai_d_06():
    """Detects: semver/version.py:483 in Version.__gt__: `>` -> `>=` (comparison_boundary)"""
    assert repr(semver.VersionInfo(1, 0, 0) > semver.VersionInfo(1, 0, 0)) == 'False'


# fault detected: semver/version.py:580 in Version.match: `0` -> `1` (constant)
# mutant id: 05cc88d0e0cba70d
def test_ai_d_07():
    """Detects: semver/version.py:580 in Version.match: `0` -> `1` (constant)"""
    assert repr(semver.Version.parse("1.0.0").match(">1.0.0")) == 'False'
    assert repr(semver.Version.parse("1.0.0").match("<1.0.0")) == 'False'
    assert repr(semver.Version.parse("2.0.0").match(">1.0.0")) == 'True'
    assert repr(semver.Version.parse("0.0.0").match("<1.0.0")) == 'True'


# fault detected: semver/version.py:292 in Version.bump_minor: `1` -> `2` (constant)
# mutant id: 0311cef58a002912
def test_ai_c_01():
    ver = semver.Version.parse("3.4.5")
    expected_version = semver.Version(major=3, minor=5, patch=0, prerelease=None, build=None)
    actual_version = ver.bump_minor()
    assert actual_version == expected_version


# fault detected: semver/version.py:554 in Version.finalize_version: `cls(self.major, self.minor, self.patch)` -> `None` (return_value)
# mutant id: 0723feea7643f22a
def test_ai_c_02():
    version = semver.Version.parse('1.2.3-rc.5')
    assert str(version.finalize_version()) == '1.2.3'


# fault detected: semver/version.py:483 in Version.__gt__: `>` -> `>=` (comparison_boundary)
# mutant id: 085c382c12637d90
def test_ai_c_03():
    # Define a version object and an equivalent version for comparison
    v1 = semver.VersionInfo.parse("1.0.0")
    v2 = semver.VersionInfo.parse("1.0.0")

    # The correct implementation should return False because the versions are equal
    assert not v1.__gt__(v2)


# fault detected: semver/version.py:580 in Version.match: `0` -> `1` (constant)
# mutant id: 05cc88d0e0cba70d
def test_ai_c_04():
    version = semver.Version.parse("2.0.0")
    assert version.match(">1.0.0") == True
    assert version.match("<3.0.0") == True
    assert version.match(">=2.0.0") == True
    assert version.match("<=2.0.0") == True
    assert version.match("==2.0.0") == True
    assert version.match("!=1.0.0") == True


# fault detected: semver/version.py:292 in Version.bump_minor: `1` -> `2` (constant)
# mutant id: 0311cef58a002912
def test_ai_b_01():
    ver = semver.VersionInfo.parse("3.4.5")
    expected = semver.VersionInfo(major=3, minor=5, patch=0)
    assert ver.bump_minor() == expected


# fault detected: semver/version.py:554 in Version.finalize_version: `cls(self.major, self.minor, self.patch)` -> `None` (return_value)
# mutant id: 0723feea7643f22a
def test_ai_b_02():
    version1 = semver.Version.parse('1.2.3-rc.5')
    version2 = semver.Version.parse('1.2.3')

    assert str(version1.finalize_version()) == '1.2.3'
    assert version1.finalize_version() != None


# fault detected: semver/version.py:514 in Version.__getitem__: `and` -> `or` (boolean_logic)
# mutant id: 2efccfe40d947649
def test_ai_b_03():
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


# fault detected: semver/version.py:483 in Version.__gt__: `>` -> `>=` (comparison_boundary)
# mutant id: 085c382c12637d90
def test_ai_b_04():
    version1 = semver.VersionInfo.parse("1.0.0")
    version2 = semver.VersionInfo.parse("1.0.0")

    # The correct implementation returns False for equality, but the regression
    # changes it to return True.
    assert not version1 > version2


# fault detected: semver/version.py:580 in Version.match: `0` -> `1` (constant)
# mutant id: 05cc88d0e0cba70d
def test_ai_b_05():
    version = semver.Version.parse("1.0.0")
    match_expr = ">1.0.0"
    
    # Correct behavior: should return False
    assert not version.match(match_expr)

    match_expr = "<1.0.0"
    
    # Correct behavior: should return False
    assert not version.match(match_expr)


# fault detected: semver/version.py:292 in Version.bump_minor: `1` -> `2` (constant)
# mutant id: 0311cef58a002912
def test_ai_b1_01():
    ver = semver.VersionInfo.parse("3.4.5")
    expected = semver.VersionInfo(major=3, minor=5, patch=0)
    assert ver.bump_minor() == expected


# fault detected: semver/version.py:483 in Version.__gt__: `>` -> `>=` (comparison_boundary)
# mutant id: 085c382c12637d90
def test_ai_b1_02():
    version1 = semver.VersionInfo.parse("1.0.0")
    version2 = semver.VersionInfo.parse("1.0.0")

    # The correct implementation returns False for equality
    assert not version1 > version2

    # The incorrect implementation returns True for equality
    assert version1 >= version2 and not (version1 > version2)


# fault detected: semver/version.py:580 in Version.match: `0` -> `1` (constant)
# mutant id: 05cc88d0e0cba70d
def test_ai_b1_03():
    version = semver.Version.parse("1.0.0")
    match_expr = ">1.0.0"
    
    # Correct behavior: should return False because it's not greater than 1.0.0
    assert not version.match(match_expr)


# fault detected: semver/version.py:598 in Version.match: `0` -> `1` (constant)
# mutant id: 7c644c64bde4883c
def test_ai_gap_01():
    """Detects: semver/version.py:598 in Version.match: `0` -> `1` (constant)"""
    assert repr(semver.Version.parse("1.0.0").match(">=1.0.0")) == 'True'


# fault detected: semver/version.py:730 in Version.is_compatible: `False` -> `None` (return_value)
# mutant id: 95f32034b4f97f3d
def test_ai_gap_02():
    """Detects: semver/version.py:730 in Version.is_compatible: `False` -> `None` (return_value)"""
    assert repr(semver.Version.parse("0.1.0").is_compatible(semver.Version.parse("0.0.1"))) == 'False'
    assert repr(semver.Version.parse("0.0.1").is_compatible(semver.Version.parse("0.1.0"))) == 'False'


# fault detected: semver/version.py:599 in Version.match: `0` -> `1` (constant)
# mutant id: bad59b17cefa1f72
def test_ai_gap_03():
    """Detects: semver/version.py:599 in Version.match: `0` -> `1` (constant)"""
    assert repr(semver.Version.parse("1.0.0").match("<=1.0.0")) == 'True'
    assert repr(semver.Version.parse("1.0.0").match("<=0.9.9")) == 'False'
    assert repr(semver.Version.parse("2.0.0").match("<=1.0.0")) == 'False'
    assert repr(semver.Version.parse("1.0.0").match("<=1.0.0-alpha")) == 'False'
    assert repr(semver.Version.parse("1.0.0").match("<=1.0.0+build.1")) == 'True'


def test_ai_raw_01():
    version = semver.VersionInfo.parse("1.2.3")
    
    # Test with a non-existent part key
    try:
        result = version.replace(unknown_part="test")
    except TypeError as e:
        assert str(e) == "replace() got 1 unexpected keyword argument(s): unknown_part"
    else:
        assert False, "Expected a TypeError but did not get one"

    # Test with multiple non-existent part keys
    try:
        result = version.replace(unknown_part="test", another_unknown="value")
    except TypeError as e:
        assert str(e) == "replace() got 2 unexpected keyword argument(s): unknown_part, another_unknown"
    else:
        assert False, "Expected a TypeError but did not get one"

    # Test with valid part keys
    result = version.replace(major=2)
    assert str(result) == "2.0.0"

    result = version.replace(minor=4)
    assert str(result) == "1.4.0"

    result = version.replace(patch=5)
    assert str(result) == "1.2.5"

    # Test with a mix of valid and non-existent part keys
    try:
        result = version.replace(major=2, unknown_part="test")
    except TypeError as e:
        assert str(e) == "replace() got 1 unexpected keyword argument(s): unknown_part"
    else:
        assert False, "Expected a TypeError but did not get one"

    # Test with valid part keys and non-string values
    result = version.replace(major=2, minor="4")
    assert str(result) == "2.4.0"

    try:
        result = version.replace(build="test")
    except TypeError as e:
        assert str(e) == "replace() got 1 unexpected keyword argument(s): build"
    else:
        assert False, "Expected a TypeError but did not get one"

    # Test with valid part keys and None values
    result = version.replace(major=None)
    assert str(result) == "0.2.3"

    result = version.replace(minor=None)
    assert str(result) == "1.0.3"


def test_ai_raw_02():
    # Test with integer and string inputs where the integer is less than a numeric part of the prerelease tag
    assert semver.cmp_prerelease_tag(1, "2") == -1
    
    # Test with integer and string inputs where the integer is greater than a numeric part of the prerelease tag
    assert semver.cmp_prerelease_tag(3, "2") == 1
    
    # Test with two strings that are not integers
    assert semver.cmp_prerelease_tag("a", "b") == -1
    
    # Test with integer and string inputs where the integer is equal to a numeric part of the prerelease tag
    assert semver.cmp_prerelease_tag(2, "2") == 0
    
    # Test with two integers that are not parts of a prerelease tag
    assert semver.cmp_prerelease_tag(1, 2) == -1
    
    # Test with integer and string inputs where the string is less than an integer part of the prerelease tag
    assert semver.cmp_prerelease_tag("1", "2") == -1
    
    # Test with integer and string inputs where the string is greater than an integer part of the prerelease tag
    assert semver.cmp_prerelease_tag("3", "2") == 1
    
    # Test with two strings that are integers but not parts of a prerelease tag
    assert semver.cmp_prerelease_tag("1", "0") == -1


def test_ai_raw_03():
    # Test with edge case where both versions are equal
    assert not semver.VersionInfo.parse("1.0.0").__lt__(semver.VersionInfo.parse("1.0.0"))
    
    # Test with a version that is strictly less than the other
    assert semver.VersionInfo.parse("1.0.0").__lt__(semver.VersionInfo.parse("1.0.1"))
    
    # Test with versions that differ only in pre-release or build metadata
    assert semver.VersionInfo.parse("1.0.0-alpha").__lt__(semver.VersionInfo.parse("1.0.0"))
    assert not semver.VersionInfo.parse("1.0.0").__lt__(semver.VersionInfo.parse("1.0.0-alpha"))
    
    # Test with versions that differ only in pre-release or build metadata
    assert semver.VersionInfo.parse("1.0.0+build").__lt__(semver.VersionInfo.parse("1.0.0"))
    assert not semver.VersionInfo.parse("1.0.0").__lt__(semver.VersionInfo.parse("1.0.0+build"))
    
    # Test with versions that differ only in major, minor, and patch
    assert semver.VersionInfo.parse("2.0.0").__lt__(semver.VersionInfo.parse("3.0.0"))
    assert not semver.VersionInfo.parse("3.0.0").__lt__(semver.VersionInfo.parse("2.0.0"))
    
    # Test with versions that differ only in pre-release or build metadata
    assert semver.VersionInfo.parse("1.0.0-rc.1").__lt__(semver.VersionInfo.parse("1.0.0"))
    assert not semver.VersionInfo.parse("1.0.0").__lt__(semver.VersionInfo.parse("1.0.0-rc.1"))


def test_ai_raw_04():
    # Test case: Bumping minor from a version with prerelease and build information
    ver = semver.VersionInfo.parse("3.4.5-alpha+01")
    new_ver = ver.bump_minor()
    assert str(new_ver) == "3.5.0-alpha+01"
    
    # Test case: Bumping minor from a version with only major and minor parts
    ver = semver.VersionInfo.parse("2.8")
    new_ver = ver.bump_minor()
    assert str(new_ver) == "2.9"
    
    # Test case: Bumping minor from a version with prerelease but no build information
    ver = semver.VersionInfo.parse("1.0.0-rc1")
    new_ver = ver.bump_minor()
    assert str(new_ver) == "1.1.0-rc1"
    
    # Test case: Bumping minor from a version with only major part
    ver = semver.VersionInfo.parse("4")
    new_ver = ver.bump_minor()
    assert str(new_ver) == "4.1"


def test_ai_raw_05():
    # Test case: Incrementing a version with a prerelease and patch part
    version = semver.VersionInfo.parse("1.2.3-rc.5")
    new_version = version.next_version("patch", "beta")
    assert str(new_version) == "1.2.4-rc.5"

    # Test case: Incrementing to a major prerelease from a patch
    version = semver.VersionInfo.parse("0.9.9-rc.3")
    new_version = version.next_version("major", "beta")
    assert str(new_version) == "1.0.0-beta.1"

    # Test case: Incrementing to a minor prerelease from a patch
    version = semver.VersionInfo.parse("2.3.4-rc.2")
    new_version = version.next_version("minor", "beta")
    assert str(new_version) == "2.4.0-beta.1"

    # Test case: Incrementing to a major prerelease from a minor
    version = semver.VersionInfo.parse("1.2.3-rc.1")
    new_version = version.next_version("major", "beta")
    assert str(new_version) == "2.0.0-beta.1"

    # Test case: Incrementing to a major prerelease from a patch
    version = semver.VersionInfo.parse("0.9.9-rc.4")
    new_version = version.next_version("major", "beta")
    assert str(new_version) == "1.0.0-beta.1"

    # Test case: Incrementing to a minor prerelease from a major
    version = semver.VersionInfo.parse("2.3.4-rc.1")
    new_version = version.next_version("minor", "beta")
    assert str(new_version) == "2.4.0-beta.1"

    # Test case: Incrementing to a patch prerelease from a major
    version = semver.VersionInfo.parse("1.2.3-rc.1")
    new_version = version.next_version("patch", "beta")
    assert str(new_version) == "1.2.4-beta.1"

    # Test case: Incrementing to a patch prerelease from a minor
    version = semver.VersionInfo.parse("0.9.9-rc.3")
    new_version = version.next_version("patch", "beta")
    assert str(new_version) == "0.9.10-beta.1"


def test_ai_raw_06():
    # Test with a version string that has no minor and patch parts
    assert str(semver.Version.parse('1', optional_minor_and_patch=True)) == 'Version(major=1, minor=0, patch=0)'
    
    # Test with a version string that has only the major part
    assert str(semver.Version.parse('2.3.4-pre.2+build.4', optional_minor_and_patch=True)) == 'Version(major=2, minor=3, patch=4, prerelease="pre.2", build="build.4")'
    
    # Test with a version string that has only the major and minor parts
    assert str(semver.Version.parse('10-rc.5+build.9', optional_minor_and_patch=True)) == 'Version(major=10, minor=0, patch=0, prerelease="rc.5", build="build.9")'
    
    # Test with a version string that has only the major and patch parts
    assert str(semver.Version.parse('2-rc+build', optional_minor_and_patch=True)) == 'Version(major=2, minor=0, patch=0, prerelease="rc", build="build")'
    
    # Test with a version string that has no valid semver format but optional parts
    assert str(semver.Version.parse('alpha.1+beta', optional_minor_and_patch=True)) == 'Version(major=0, minor=0, patch=0, prerelease="alpha.1", build="beta")'
    
    # Test with a version string that has only the major part and no optional parts
    assert str(semver.Version.parse('5', optional_minor_and_patch=False)) == pytest.raises(ValueError, match="'5' is not valid SemVer string")


def test_ai_raw_07():
    # Test with a version that has both prerelease and build metadata
    version = semver.Version.parse('1.2.3-rc.5+build.1')
    assert str(version.finalize_version()) == '1.2.3'
    
    # Test with a version that only has a prerelease tag
    version = semver.Version.parse('1.2.3-rc.5')
    assert str(version.finalize_version()) == '1.2.3'
    
    # Test with a version that only has build metadata
    version = semver.Version.parse('1.2.3+build.1')
    assert str(version.finalize_version()) == '1.2.3'
    
    # Test with a version that has both prerelease and build metadata, but different order
    version = semver.Version.parse('+build.1-rc.5')
    assert str(version.finalize_version()) == '1.0.0'
    # Note: This test assumes the implementation treats '+build.1' as part of the version string,
    #       and '-rc.5' as metadata to be removed.
    
    # Test with a version that has no prerelease or build metadata
    version = semver.Version.parse('1.2.3')
    assert str(version.finalize_version()) == '1.2.3'


def test_ai_raw_08():
    # Test case: Incrementing a string with leading zeros
    assert semver._increment_string("version_001") == "version_002"
    
    # Test case: Incrementing the last number in the string
    assert semver._increment_string("v1.2.3") == "v1.2.4"
    
    # Test case: Incrementing a single digit at the end of the string
    assert semver._increment_string("release-5") == "release-6"
    
    # Test case: Incrementing when there are multiple numbers in the string
    assert semver._increment_string("build_12345") == "build_12346"
    
    # Test case: Incrementing a string with no digits at all
    assert semver._increment_string("no_numbers_here") == "no_numbers_here"
    
    # Test case: Incrementing the last number in a string with trailing characters
    assert semver._increment_string("patch-12a") == "patch-13a"
    
    # Test case: Incrementing when there are no numbers to increment
    assert semver._increment_string("no_numbers_here_either") == "no_numbers_here_either"
    
    # Test case: Incrementing a string with multiple groups of numbers
    assert semver._increment_string("version_123_456") == "version_123_457"


def test_ai_raw_09():
    # Test case for when index is at the boundary of slice start and stop
    version = semver.Version.parse("3.4.5")
    assert version[0:1] == (3,)
    assert version[1:2] == (4,)
    assert version[2:3] == (5,)

    # Test case for when index is out of bounds on the stop
    with pytest.raises(IndexError):
        version[3:4]

    # Test case for when index is out of bounds on the start
    with pytest.raises(IndexError):
        version[-1:0]

    # Test case for when both start and stop are out of bounds
    with pytest.raises(IndexError):
        version[-2:-1]


def test_ai_raw_10():
    # Test with edge case where both versions are equal
    assert not semver.VersionInfo.parse("1.0.0").__gt__(semver.VersionInfo.parse("1.0.0"))

    # Test with a very large version number to check for potential overflow or precision issues
    assert semver.VersionInfo.parse("9999999999.9999999999.9999999999").__gt__(semver.VersionInfo.parse("1.0.0"))

    # Test with a version that has only major and minor parts
    assert semver.VersionInfo.parse("2.3").__gt__(semver.VersionInfo.parse("1.3"))

    # Test with a version that has only major part
    assert semver.VersionInfo.parse("4").__gt__(semver.VersionInfo.parse("3"))

    # Test with a version that has extra padding in the string representation
    assert semver.VersionInfo.parse("5.0.0").__gt__(semver.VersionInfo.parse("4.9.9"))

    # Test with a version that has pre-release tags
    assert semver.VersionInfo.parse("1.0.0-alpha").__gt__(semver.VersionInfo.parse("0.9.9"))

    # Test with a version that has build metadata
    assert semver.VersionInfo.parse("2.3.4+build.meta").__gt__(semver.VersionInfo.parse("2.3.3"))


def test_ai_raw_12():
    # Test case: Incrementing build number with a non-empty token
    ver = semver.VersionInfo.parse("3.4.5-rc.1+build.9")
    new_ver = ver.bump_build(token="01")
    assert str(new_ver) == "3.4.5-rc.1+build.10"

    # Test case: Incrementing build number with an empty token
    ver = semver.VersionInfo.parse("3.4.5-rc.1+build.9")
    new_ver = ver.bump_build(token="")
    assert str(new_ver) == "3.4.5-rc.1+build.0"

    # Test case: Incrementing build number with None token
    ver = semver.VersionInfo.parse("3.4.5-rc.1+build.9")
    new_ver = ver.bump_build(token=None)
    assert str(new_ver) == "3.4.5-rc.1+build.0"

    # Test case: Incrementing build number with a None token and existing build
    ver = semver.VersionInfo.parse("3.4.5-rc.1+build.9")
    new_ver = ver.bump_build(token=None)
    assert str(new_ver) == "3.4.5-rc.1+build.0"

    # Test case: Incrementing build number with a token that results in no change
    ver = semver.VersionInfo.parse("3.4.5-rc.1+build.9")
    new_ver = ver.bump_build(token="9")
    assert str(new_ver) == "3.4.5-rc.1+build.10"

    # Test case: Incrementing build number with a token that results in no change and existing build
    ver = semver.VersionInfo.parse("3.4.5-rc.1+build.9")
    new_ver = ver.bump_build(token="9")
    assert str(new_ver) == "3.4.5-rc.1+build.10"

