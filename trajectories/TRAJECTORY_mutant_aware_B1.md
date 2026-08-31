# Trajectory — condition `mutant_aware_B1`

- **Context condition**: `B`
- **Max attempts**: 1
- **Discovery faults attempted**: 12
- **Admitted**: 3
- **Model cost**: 12 calls, 1231 output tokens, 181 model-seconds, $0.00

Every attempt below was judged by executing pytest, never by asking the model to grade itself. The admission gates are:

- `static` — static checks (parses, defines a test, no forbidden patterns, has an assertion)
- `clean_head` — passes against the CORRECT implementation
- `kills_target` — FAILS against the injected fault — the test detects it
- `repeat_stable` — same verdict on repeat runs

---

## Fault 1/12 — `0a016d6d36518355` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (159 tokens in 22.75s):*

```python
import semver

def test_placebo_candidate():
    version = semver.VersionInfo.parse("1.2.3")
    parts = {"major": 4, "patch": 5}
    
    # Correct behavior: unknownkeys should be {'build'}
    try:
        result = version.replace(**parts)
    except TypeError as e:
        assert str(e) == "replace() got 0 unexpected keyword argument(s):"
    
    # Incorrect behavior (bug): unknownkeys should include 'build' and 'patch'
    parts["build"] = None
    with pytest.raises(TypeError) as excinfo:
        version.replace(**parts)
    assert str(excinfo.value) == "replace() got 2 unexpected keyword argument(s): build, patch"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 2/12 — `1ac3986cca492880` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (55 tokens in 8.61s):*

```python
import semver

def test_placebo_candidate():
    assert semver.cmp_prerelease_tag(1, "2") == -1
    assert semver.cmp_prerelease_tag("2", 1) == 1
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 3/12 — `03fe90d993fa6512` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (71 tokens in 10.59s):*

```python
import semver

def test_placebo_candidate():
    version1 = semver.VersionInfo.parse("1.0.0")
    version2 = semver.VersionInfo.parse("1.0.1")

    # The correct implementation returns False, but the changed implementation returns True
    assert not version1 < version2
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 4/12 — `0311cef58a002912` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (60 tokens in 8.84s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.VersionInfo.parse("3.4.5")
    expected = semver.VersionInfo(major=3, minor=5, patch=0)
    assert ver.bump_minor() == expected
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import semver

def test_placebo_candidate():
    ver = semver.VersionInfo.parse("3.4.5")
    expected = semver.VersionInfo(major=3, minor=5, patch=0)
    assert ver.bump_minor() == expected
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 5/12 — `1486704c2686bc4b` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (162 tokens in 24.43s):*

```python
import semver

def test_placebo_candidate():
    # Define a version where patch is 0 and minor is not 0
    version = semver.VersionInfo.parse("1.0.0-rc.5")
    
    # Expected result when part is "minor" and patch is 0
    expected_minor = "1.1.0"
    
    # Expected result when part is not "minor" and patch is 0
    expected_other = "1.0.1-rc.6"
    
    # Test with part as "minor"
    assert str(version.next_version("minor")) == expected_minor
    
    # Test with part as something other than "minor"
    assert str(version.next_version("patch")) == expected_other
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 6/12 — `5c7e1209a4ecd4ba` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (133 tokens in 19.71s):*

```python
import semver

def test_placebo_candidate():
    # Input where optional_minor_and_patch is True and version has no minor and patch parts
    with pytest.raises(ValueError):
        semver.Version.parse('3.4', optional_minor_and_patch=True)
    
    # Input where optional_minor_and_patch is False and version has no minor and patch parts
    try:
        semver.Version.parse('3.4', optional_minor_and_patch=False)
    except ValueError as e:
        assert False, f"Test failed unexpectedly: {e}"

# The test will pass with the correct code but fail if the line is changed as specified.
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 7/12 — `0723feea7643f22a` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (88 tokens in 12.53s):*

```python
import semver

def test_placebo_candidate():
    version1 = semver.Version.parse('1.2.3')
    version2 = semver.Version.parse('1.2.3-rc.5').finalize_version()
    
    assert str(version1.finalize_version()) == '1.2.3'
    assert str(version2) == '1.2.3-rc.5'
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 8/12 — `1d331d5b9501ed06` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (57 tokens in 8.77s):*

```python
import semver

def test_placebo_candidate():
    original_string = "version_123"
    expected_result = "version_124"
    actual_result = semver._increment_string(original_string)
    assert actual_result == expected_result
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 9/12 — `2efccfe40d947649` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (212 tokens in 30.57s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.Version.parse("3.4.5")
    
    # Test with a negative start index
    try:
        part = ver[0:1]
        assert len(part) == 1 and part[0] == 3
    except IndexError as e:
        assert False, f"Test failed unexpectedly: {e}"
    
    # Test with an invalid range that triggers the change in behavior
    try:
        part = ver[-1:]
        assert False, "Expected IndexError but got a valid result"
    except IndexError as e:
        pass

    # Test with a valid range that should not trigger the change
    try:
        part = ver[0:3]
        assert len(part) == 3 and part[0] == 3 and part[1] == 4 and part[2] == 5
    except IndexError as e:
        assert False, f"Test failed unexpectedly: {e}"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 10/12 — `085c382c12637d90` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (92 tokens in 12.85s):*

```python
import semver

def test_placebo_candidate():
    version1 = semver.VersionInfo.parse("1.0.0")
    version2 = semver.VersionInfo.parse("1.0.0")

    # The correct implementation returns False for equality
    assert not version1 > version2

    # The incorrect implementation returns True for equality
    assert version1 >= version2 and not (version1 > version2)
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import semver

def test_placebo_candidate():
    version1 = semver.VersionInfo.parse("1.0.0")
    version2 = semver.VersionInfo.parse("1.0.0")

    # The correct implementation returns False for equality
    assert not version1 > version2

    # The incorrect implementation returns True for equality
    assert version1 >= version2 and not (version1 > version2)
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 11/12 — `05cc88d0e0cba70d` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (70 tokens in 10.49s):*

```python
import semver

def test_placebo_candidate():
    version = semver.Version.parse("1.0.0")
    match_expr = ">1.0.0"
    
    # Correct behavior: should return False because it's not greater than 1.0.0
    assert not version.match(match_expr)
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import semver

def test_placebo_candidate():
    version = semver.Version.parse("1.0.0")
    match_expr = ">1.0.0"
    
    # Correct behavior: should return False because it's not greater than 1.0.0
    assert not version.match(match_expr)
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 12/12 — `1ca242d1ca74bb80` — NOT ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (72 tokens in 10.94s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.VersionInfo.parse("3.4.5-rc.1+build.9")
    new_ver = ver.bump_build(token="")
    
    assert str(new_ver) == "3.4.5-rc.1+build.10"
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`
- **REJECTED** `TARGET_MUTANT_SURVIVED` — candidate does not detect the injected fault
- fault status under this test: `survived`


---
