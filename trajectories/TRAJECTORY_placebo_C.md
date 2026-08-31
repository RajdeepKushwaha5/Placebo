# Trajectory — condition `placebo_C`

- **Context condition**: `C`
- **Max attempts**: 3
- **Discovery faults attempted**: 12
- **Admitted**: 4
- **Model cost**: 28 calls, 2970 output tokens, 849 model-seconds, $0.00

Every attempt below was judged by executing pytest, never by asking the model to grade itself. The admission gates are:

- `static` — static checks (parses, defines a test, no forbidden patterns, has an assertion)
- `clean_head` — passes against the CORRECT implementation
- `kills_target` — FAILS against the injected fault — the test detects it
- `repeat_stable` — same verdict on repeat runs

---

## Fault 1/12 — `0a016d6d36518355` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (161 tokens in 23.81s):*

```python
import semver

def test_placebo_candidate():
    version = semver.Version.parse("1.2.3")
    
    # Test with valid parts
    new_version = version.replace(major=4)
    assert str(new_version) == "4.2.3"
    
    # Test with invalid keys (should raise TypeError)
    with pytest.raises(TypeError):
        version.replace(invalid_key="test")

    # Test with multiple valid parts
    new_version = version.replace(minor=5, patch=6)
    assert str(new_version) == "1.5.6"

    # Test with a mix of valid and invalid keys (should raise TypeError)
    with pytest.raises(TypeError):
        version.replace(major=4, invalid_key="test")
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (127 tokens in 18.09s):*

```python
import semver

def test_placebo_candidate():
    v = semver.Version.parse("1.2.3")
    
    # Test with valid keys
    new_version = v.replace(major=4)
    assert str(new_version) == "4.2.3"
    
    # Test with multiple valid keys
    new_version = v.replace(major=4, minor=5)
    assert str(new_version) == "4.5.3"
    
    # Test with invalid keys (should raise TypeError)
    with pytest.raises(TypeError):
        v.replace(invalid_key="test")
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (127 tokens in 18.27s):*

```python
import semver

def test_placebo_candidate():
    v = semver.Version.parse("1.2.3")
    
    # Test with valid keys
    new_version = v.replace(major=4)
    assert str(new_version) == "4.2.3"
    
    # Test with multiple valid keys
    new_version = v.replace(major=4, minor=5)
    assert str(new_version) == "4.5.3"
    
    # Test with invalid keys (should raise TypeError)
    with pytest.raises(TypeError):
        v.replace(unknownkey="test")
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 2/12 — `1ac3986cca492880` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (185 tokens in 25.89s):*

```python
import semver

def test_placebo_candidate():
    # Test case where both a and b are integers
    assert semver.cmp_prerelease_tag(1, 2) == -1
    
    # Test case where a is an integer and b is a string with a prerelease tag
    assert semver.cmp_prerelease_tag(1, "1.0.0-alpha") == -1
    
    # Test case where a is a string with a prerelease tag and b is an integer
    assert semver.cmp_prerelease_tag("2.0.0-beta", 2) == 1
    
    # Test case where both a and b are strings with the same prerelease tag
    assert semver.cmp_prerelease_tag("3.0.0-alpha", "3.0.0-alpha") == 0
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (69 tokens in 10.11s):*

```python
import semver

def test_placebo_candidate():
    # The function should compare two prerelease tags.
    # Given that both are integers, it should return -1 if 'a' is less than 'b'.
    assert semver.cmp_prerelease_tag(1, 2) == -1
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (69 tokens in 10.1s):*

```python
import semver

def test_placebo_candidate():
    # The function should compare two prerelease tags.
    # Given that both are integers, it should return -1 if 'a' is less than 'b'.
    assert semver.cmp_prerelease_tag(1, 2) == -1
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 3/12 — `03fe90d993fa6512` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (116 tokens in 16.41s):*

```python
import semver

def test_placebo_candidate():
    # Create two version objects for comparison
    v1 = semver.VersionInfo.parse("1.0.0")
    v2 = semver.VersionInfo.parse("1.0.1")

    # Correct behavior: v1 < v2 should be True
    assert v1.__lt__(v2) == True

    # Regression behavior: v1 <= v2 should still be False, but it is not
    assert v1.__lt__(v2) != False
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`
- **REJECTED** `TARGET_MUTANT_SURVIVED` — candidate does not detect the injected fault
- fault status under this test: `survived`

### Attempt 2

*Agent produced (112 tokens in 15.95s):*

```python
import semver

def test_placebo_candidate():
    v1 = semver.VersionInfo.parse("1.0.0")
    v2 = semver.VersionInfo.parse("1.0.1")

    # Correct implementation should return False because 1.0.0 < 1.0.1
    assert v1.__lt__(v2) == False

    # Buggy implementation returns True because of the <= comparison, which is incorrect
    assert v1.__lt__(v2) == True
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (76 tokens in 11.56s):*

```python
import semver

def test_placebo_candidate():
    v1 = semver.Version(major=1, minor=0, patch=0)
    v2 = semver.Version(major=1, minor=0, patch=1)
    
    assert v1 < v2 == False
    assert v2 > v1 == True
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 4/12 — `0311cef58a002912` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (73 tokens in 10.74s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.Version.parse("3.4.5")
    expected_version = semver.Version(major=3, minor=5, patch=0, prerelease=None, build=None)
    actual_version = ver.bump_minor()
    assert actual_version == expected_version
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import semver

def test_placebo_candidate():
    ver = semver.Version.parse("3.4.5")
    expected_version = semver.Version(major=3, minor=5, patch=0, prerelease=None, build=None)
    actual_version = ver.bump_minor()
    assert actual_version == expected_version
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 5/12 — `1486704c2686bc4b` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (110 tokens in 16.22s):*

```python
import semver

def test_placebo_candidate():
    version = semver.VersionInfo.parse("0.1.4-rc.3")
    
    # Correct behaviour: should increment patch and add prerelease token
    assert str(version.next_version("prerelease")) == "0.1.5-rc.1"
    
    # Regression behaviour: should not change version as part is not 'minor'
    assert str(version.next_version("patch")) == "0.1.4-rc.4"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (57 tokens in 8.78s):*

```python
import semver

def test_placebo_candidate():
    version = semver.VersionInfo.parse("0.1.4-rc.3")
    assert str(version.next_version("prerelease")) == "0.1.5-rc.1"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (57 tokens in 8.71s):*

```python
import semver

def test_placebo_candidate():
    version = semver.VersionInfo.parse("0.1.4-rc.3")
    assert str(version.next_version("prerelease")) == "0.1.5-rc.1"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 6/12 — `5c7e1209a4ecd4ba` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (174 tokens in 25.23s):*

```python
import semver

def test_placebo_candidate():
    # Test with a valid version string without optional parts
    assert semver.Version.parse('3.4') == semver.Version(major=3, minor=4)
    
    # Test with a valid version string with optional parts
    assert semver.Version.parse('3.4.5-pre.2+build.4', optional_minor_and_patch=True) == semver.Version(
        major=3, minor=4, patch=5, prerelease='pre.2', build='build.4'
    )
    
    # Test with an invalid version string
    with pytest.raises(ValueError):
        semver.Version.parse('invalid-version')
    
    # Test with a non-string input
    with pytest.raises(TypeError):
        semver.Version.parse(123)
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (107 tokens in 15.86s):*

```python
import semver

def test_placebo_candidate():
    # Test with a valid SemVer string without optional parts
    assert semver.Version.parse('3.4') == semver.Version(major=3, minor=4, patch=0)
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (122 tokens in 17.86s):*

```python
import semver

def test_placebo_candidate():
    # Test with a valid SemVer string without optional parts
    assert semver.Version.parse('3.4') == semver.Version(major=3, minor=4, patch=0)
    # Test with a valid SemVer string with optional parts
    assert semver.Version.parse('3.4.5-pre.2+build.4') == semver.Version(
        major=3, minor=4, patch=5, prerelease='pre.2', build='build.4'
    )
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 7/12 — `0723feea7643f22a` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (49 tokens in 7.3s):*

```python
import semver

def test_placebo_candidate():
    version = semver.Version.parse('1.2.3-rc.5')
    assert str(version.finalize_version()) == '1.2.3'
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import semver

def test_placebo_candidate():
    version = semver.Version.parse('1.2.3-rc.5')
    assert str(version.finalize_version()) == '1.2.3'
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 8/12 — `1d331d5b9501ed06` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (61 tokens in 9.06s):*

```python
import semver

def test_placebo_candidate():
    original_string = "version_1.2.3"
    expected_result = "version_1.2.4"
    
    result = semver._increment_string(original_string)
    
    assert result == expected_result
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (57 tokens in 8.59s):*

```python
import semver

def test_placebo_candidate():
    original_string = "version2.3.1"
    expected_result = "version2.3.2"
    result = semver._increment_string(original_string)
    assert result == expected_result
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (53 tokens in 7.84s):*

```python
import semver

def test_placebo_candidate():
    original_string = "version2.3.1"
    expected_result = "version2.3.2"
    assert semver._increment_string(original_string) == expected_result
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 9/12 — `2efccfe40d947649` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (204 tokens in 29.06s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.Version.parse("3.4.5")
    
    # Test with a valid slice that should raise an IndexError due to negative start
    with pytest.raises(IndexError):
        ver[0:100]

    # Test with a valid slice that should not raise an IndexError
    assert ver[0:2] == (3, 4)

    # Test with a valid single index that should return the correct part
    assert ver[0] == 3
    assert ver[1] == 4
    assert ver[2] == 5

    # Test with an invalid slice where start is None but end is valid
    with pytest.raises(IndexError):
        ver[None:2]

    # Test with a valid slice that should not raise an IndexError even though start is None
    assert ver[0:None] == (3, 4, 5)
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (177 tokens in 26.05s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.Version.parse("3.4.5")
    
    # Test with a valid index
    assert ver[0] == 3
    assert ver[1] == 4
    assert ver[2] == 5
    
    # Test with an invalid start index (should raise IndexError)
    with pytest.raises(IndexError):
        ver[-1]
    
    # Test with a slice that should raise IndexError due to undefined part
    with pytest.raises(IndexError):
        ver[slice(3, 4)]
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (177 tokens in 25.2s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.Version.parse("3.4.5")
    
    # Test with a valid index
    assert ver[0] == 3
    assert ver[1] == 4
    assert ver[2] == 5
    
    # Test with an invalid start index (should raise IndexError)
    with pytest.raises(IndexError):
        ver[-1]
    
    # Test with a slice that should raise IndexError due to undefined part
    with pytest.raises(IndexError):
        ver[slice(3, 4)]
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 10/12 — `085c382c12637d90` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (85 tokens in 437.34s):*

```python
import semver

def test_placebo_candidate():
    # Define a version object and an equivalent version for comparison
    v1 = semver.VersionInfo.parse("1.0.0")
    v2 = semver.VersionInfo.parse("1.0.0")

    # The correct implementation should return False because the versions are equal
    assert not v1.__gt__(v2)
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import semver

def test_placebo_candidate():
    # Define a version object and an equivalent version for comparison
    v1 = semver.VersionInfo.parse("1.0.0")
    v2 = semver.VersionInfo.parse("1.0.0")

    # The correct implementation should return False because the versions are equal
    assert not v1.__gt__(v2)
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 11/12 — `05cc88d0e0cba70d` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (117 tokens in 14.69s):*

```python
import semver

def test_placebo_candidate():
    version = semver.Version.parse("2.0.0")
    assert version.match(">1.0.0") == True
    assert version.match("<3.0.0") == True
    assert version.match(">=2.0.0") == True
    assert version.match("<=2.0.0") == True
    assert version.match("==2.0.0") == True
    assert version.match("!=1.0.0") == True
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import semver

def test_placebo_candidate():
    version = semver.Version.parse("2.0.0")
    assert version.match(">1.0.0") == True
    assert version.match("<3.0.0") == True
    assert version.match(">=2.0.0") == True
    assert version.match("<=2.0.0") == True
    assert version.match("==2.0.0") == True
    assert version.match("!=1.0.0") == True
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 12/12 — `1ca242d1ca74bb80` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (83 tokens in 10.27s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.Version.parse("3.4.5-rc.1+build.9")
    new_ver = ver.bump_build(token="")
    assert str(new_ver) == "Version(major=3, minor=4, patch=5, prerelease='rc.1', build='build.10')"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (82 tokens in 9.94s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.Version.parse("3.4.5-rc.1+build.9")
    new_ver = ver.bump_build()
    assert str(new_ver) == "Version(major=3, minor=4, patch=5, prerelease='rc.1', build='build.10')"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (83 tokens in 10.05s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.VersionInfo.parse("3.4.5-rc.1+build.9")
    new_ver = ver.bump_build()
    assert str(new_ver) == "Version(major=3, minor=4, patch=5, prerelease='rc.1', build='build.10')"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---
