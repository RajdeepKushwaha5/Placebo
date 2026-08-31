# Trajectory — condition `baseline_A`

- **Context condition**: `A`
- **Max attempts**: 1
- **Discovery faults attempted**: 12
- **Admitted**: 0
- **Model cost**: 12 calls, 3976 output tokens, 613 model-seconds, $0.00

Every attempt below was judged by executing pytest, never by asking the model to grade itself. The admission gates are:

- `static` — static checks (parses, defines a test, no forbidden patterns, has an assertion)
- `clean_head` — passes against the CORRECT implementation
- `kills_target` — FAILS against the injected fault — the test detects it
- `repeat_stable` — same verdict on repeat runs

---

## Fault 1/12 — `0a016d6d36518355` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (472 tokens in 69.64s):*

```python
import semver

def test_placebo_candidate():
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
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 2/12 — `1ac3986cca492880` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (335 tokens in 48.41s):*

```python
import semver

def test_placebo_candidate():
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
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 3/12 — `03fe90d993fa6512` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (416 tokens in 59.3s):*

```python
import semver

def test_placebo_candidate():
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
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 4/12 — `0311cef58a002912` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (245 tokens in 36.24s):*

```python
import semver

def test_placebo_candidate():
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
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 5/12 — `1486704c2686bc4b` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (538 tokens in 82.29s):*

```python
import semver

def test_placebo_candidate():
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
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 6/12 — `5c7e1209a4ecd4ba` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (388 tokens in 57.96s):*

```python
import semver

def test_placebo_candidate():
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
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 7/12 — `0723feea7643f22a` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (299 tokens in 44.35s):*

```python
import semver

def test_placebo_candidate():
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
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 8/12 — `1d331d5b9501ed06` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (326 tokens in 47.65s):*

```python
import semver

def test_placebo_candidate():
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
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 9/12 — `2efccfe40d947649` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (170 tokens in 25.36s):*

```python
import semver

def test_placebo_candidate():
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
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 10/12 — `085c382c12637d90` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (332 tokens in 48.0s):*

```python
import semver

def test_placebo_candidate():
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
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 11/12 — `05cc88d0e0cba70d` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (0 tokens in 27.56s):*

```python
```python
import semver

def test_placebo_candidate():
    # Test edge case where version is exactly equal and operator is "=="
    assert semver.Version.parse("2.0.0").match("==2.0.0") == True

    # Test edge case where version is exactly equal and operator is "!="
    assert semver.Version.parse("2.0.0").match("!=2.0.1") == True
    assert semver.Version.parse("2.0.0").match("!=2.0.0") == False

    # Test edge case where version is greater than and operator is ">"
    assert semver.Version.parse("3.0.0").match(">2.9.9999999999999999999999999999999
```

*Tool response — admission gates:*

- **REJECTED** `SYNTAX_ERROR` — line 13: unterminated string literal (detected at line 13)


---

## Fault 12/12 — `1ca242d1ca74bb80` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (455 tokens in 66.31s):*

```python
import semver

def test_placebo_candidate():
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
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---
