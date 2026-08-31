# Trajectory — condition `placebo_B`

- **Context condition**: `B`
- **Max attempts**: 3
- **Discovery faults attempted**: 12
- **Admitted**: 5
- **Model cost**: 29 calls, 2819 output tokens, 440 model-seconds, $0.00

Every attempt below was judged by executing pytest, never by asking the model to grade itself. The admission gates are:

- `static` — static checks (parses, defines a test, no forbidden patterns, has an assertion)
- `clean_head` — passes against the CORRECT implementation
- `kills_target` — FAILS against the injected fault — the test detects it
- `repeat_stable` — same verdict on repeat runs

---

## Fault 1/12 — `0a016d6d36518355` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (156 tokens in 22.9s):*

```python
import semver

def test_placebo_candidate():
    version = semver.VersionInfo.parse("1.2.3")
    parts = {"major": 4, "patch": 5}
    
    # Correct behavior: unknownkeys should be {'build', 'minor'}
    try:
        result = version.replace(**parts)
    except TypeError as e:
        assert str(e) == "replace() got 0 unexpected keyword argument(s):"
    
    # Incorrect behavior (bug): unknownkeys should include 'minor'
    parts["minor"] = None
    with pytest.raises(TypeError) as excinfo:
        version.replace(**parts)
    assert str(excinfo.value) == "replace() got 1 unexpected keyword argument(s): minor"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (145 tokens in 22.0s):*

```python
import semver

def test_placebo_candidate():
    version = semver.VersionInfo.parse("1.2.3")
    with pytest.raises(TypeError) as excinfo:
        version.replace(major=4, patch=5)
    assert str(excinfo.value) == "replace() got 0 unexpected keyword argument(s):"

    version_dict = {"major": 4, "minor": 6, "patch": 7, "prerelease": None, "build": None}
    new_version = version.to_dict()
    new_version.update(version_dict)
    expected_version = semver.VersionInfo(**new_version)

    assert version.replace(**version_dict) == expected_version
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (142 tokens in 40.41s):*

```python
import semver

def test_placebo_candidate():
    version = semver.VersionInfo.parse("1.2.3")
    with pytest.raises(TypeError) as excinfo:
        version.replace(major=4, patch=5)
    assert str(excinfo.value) == "replace() got 0 unexpected keyword argument(s):"

    version = semver.VersionInfo.parse("1.2.3-rc.1+build.10")
    with pytest.raises(TypeError) as excinfo:
        version.replace(major=4, prerelease="beta", build=None)
    assert str(excinfo.value) == "replace() got 0 unexpected keyword argument(s):"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 2/12 — `1ac3986cca492880` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (75 tokens in 12.18s):*

```python
import semver

def test_placebo_candidate():
    assert semver.cmp_prerelease_tag(1, "2") == -1
    assert semver.cmp_prerelease_tag("2", 1) == 1
    assert semver.cmp_prerelease_tag(1, 2) == -1
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (75 tokens in 11.15s):*

```python
import semver

def test_placebo_candidate():
    # Choose input values where the two versions produce different results.
    # The change from 'and' to 'or' in the condition will make the function return -1 instead of 0.
    assert semver.cmp_prerelease_tag(1, "2") == -1
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (75 tokens in 11.17s):*

```python
import semver

def test_placebo_candidate():
    # Choose input values where the two versions produce different results.
    # The change from 'and' to 'or' in the condition will make the function return -1 instead of 0.
    assert semver.cmp_prerelease_tag(1, "2") == -1
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 3/12 — `03fe90d993fa6512` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (71 tokens in 10.63s):*

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

### Attempt 2

*Agent produced (56 tokens in 8.35s):*

```python
import semver

def test_placebo_candidate():
    version1 = semver.VersionInfo.parse("1.0.0")
    version2 = semver.VersionInfo.parse("1.0.1")

    assert not version1 < version2
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (56 tokens in 8.29s):*

```python
import semver

def test_placebo_candidate():
    version1 = semver.VersionInfo.parse("1.0.0")
    version2 = semver.VersionInfo.parse("1.0.1")

    assert not version1 < version2
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 4/12 — `0311cef58a002912` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (60 tokens in 9.04s):*

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

Attempts used: 3

### Attempt 1

*Agent produced (103 tokens in 15.88s):*

```python
import semver

def test_placebo_candidate():
    version1 = semver.VersionInfo.parse("0.2.3")
    version2 = semver.VersionInfo.parse("0.2.3-rc.1")

    # The change should affect the outcome for this input
    assert str(version1.next_version("minor")) == "0.3.0"
    assert str(version2.next_version("minor")) == "0.2.4-rc.1"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (89 tokens in 13.51s):*

```python
import semver

def test_placebo_candidate():
    version = semver.VersionInfo.parse("0.2.3-rc.1")
    version2 = semver.VersionInfo.parse("0.2.4")

    assert str(version.next_version("minor")) == "0.3.0"
    assert str(version2.next_version("minor")) == "0.3.0-rc.1"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (89 tokens in 13.37s):*

```python
import semver

def test_placebo_candidate():
    version = semver.VersionInfo.parse("0.2.0-rc.1")
    version2 = semver.VersionInfo.parse("0.2.0")

    assert str(version.next_version("minor")) == "0.3.0-rc.1"
    assert str(version2.next_version("minor")) == "0.3.0"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 6/12 — `5c7e1209a4ecd4ba` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (250 tokens in 37.18s):*

```python
import semver

def test_placebo_candidate():
    # Input where optional_minor_and_patch is True and version has no minor and patch parts
    with pytest.raises(ValueError):
        semver.Version.parse('3.4', optional_minor_and_patch=True)
    
    # Input where optional_minor_and_patch is False and version has no minor and patch parts
    assert semver.Version.parse('3.4', optional_minor_and_patch=False).minor == 0
    assert semver.Version.parse('3.4', optional_minor_and_patch=False).patch == 0

    # Input where optional_minor_and_patch is True and version has minor and patch parts
    with pytest.raises(ValueError):
        semver.Version.parse('3.4.5-pre.2+build.4', optional_minor_and_patch=True)
    
    # Input where optional_minor_and_patch is False and version has minor and patch parts
    assert semver.Version.parse('3.4.5-pre.2+build.4', optional_minor_and_patch=False).minor == 0
    assert semver.Version.parse('3.4.5-pre.2+build.4', optional_minor_and_patch=False).patch == 0
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (123 tokens in 18.16s):*

```python
import semver

def test_placebo_candidate():
    # Test with a string that should raise an error when optional_minor_and_patch is False
    with pytest.raises(ValueError):
        semver.Version.parse('3.4', optional_minor_and_patch=False)
    
    # Test with the same string but without raising an error when optional_minor_and_patch is True
    version = semver.Version.parse('3.4', optional_minor_and_patch=True)
    assert str(version) == 'Version(major=3, minor=4, patch=0, prerelease=None, build=None)'
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (111 tokens in 16.67s):*

```python
import semver

def test_placebo_candidate():
    with pytest.raises(TypeError):
        semver.Version.parse(b'\xff\xf3\x8e\xe6')

    try:
        semver.Version.parse('3.4.5-pre.2+build.4', optional_minor_and_patch=True)
    except ValueError as e:
        assert False, f"Expected no ValueError, but got: {e}"

semver.Version.parse('3.4.5-pre.2+build.4', optional_minor_and_patch=True)
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 7/12 — `0723feea7643f22a` — ADMITTED

Attempts used: 2

### Attempt 1

*Agent produced (171 tokens in 24.04s):*

```python
import semver

def test_placebo_candidate():
    version1 = semver.Version.parse("1.2.3-rc.5")
    version2 = semver.Version.parse("1.2.3")

    assert str(version1.finalize_version()) == "1.2.3"
    assert str(version2.finalize_version()) == "1.2.3"

    # Introduce the regression by modifying finalize_version
    orig_finalize_version = semver.Version.finalize_version

    try:
        def broken_finalize_version(self):
            return None

        semver.Version.finalize_version = broken_finalize_version

        assert str(version1.finalize_version()) is None
        assert str(version2.finalize_version()) is None
    finally:
        semver.Version.finalize_version = orig_finalize_version
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (77 tokens in 11.77s):*

```python
import semver

def test_placebo_candidate():
    version1 = semver.Version.parse('1.2.3-rc.5')
    version2 = semver.Version.parse('1.2.3')

    assert str(version1.finalize_version()) == '1.2.3'
    assert version1.finalize_version() != None
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import semver

def test_placebo_candidate():
    version1 = semver.Version.parse('1.2.3-rc.5')
    version2 = semver.Version.parse('1.2.3')

    assert str(version1.finalize_version()) == '1.2.3'
    assert version1.finalize_version() != None
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 8/12 — `1d331d5b9501ed06` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (57 tokens in 8.69s):*

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

### Attempt 2

*Agent produced (59 tokens in 8.68s):*

```python
import semver

def test_placebo_candidate():
    original_string = "version2.3.1"
    expected_result = "version2.3.2"
    actual_result = semver._increment_string(original_string)
    assert actual_result == expected_result
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (59 tokens in 8.58s):*

```python
import semver

def test_placebo_candidate():
    original_string = "version2.3.1"
    expected_result = "version2.3.2"
    actual_result = semver._increment_string(original_string)
    assert actual_result == expected_result
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---

## Fault 9/12 — `2efccfe40d947649` — ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (96 tokens in 14.43s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.Version.parse("3.4.5")
    
    # Test with a negative start index
    assert ver[0:0] == (3,)
    
    # Test with an invalid slice that should raise an IndexError due to the change
    try:
        ver[-1:1]
        assert False, "Expected IndexError not raised"
    except IndexError:
        pass
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 2

*Agent produced (114 tokens in 16.88s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.Version.parse("3.4.5")
    
    # Test with start index -1, which should raise an IndexError in the correct implementation
    assert pytest.raises(IndexError, lambda: ver[-1:0])
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (98 tokens in 14.53s):*

```python
import semver

def test_placebo_candidate():
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
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import semver

def test_placebo_candidate():
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
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 10/12 — `085c382c12637d90` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (78 tokens in 11.4s):*

```python
import semver

def test_placebo_candidate():
    version1 = semver.VersionInfo.parse("1.0.0")
    version2 = semver.VersionInfo.parse("1.0.0")

    # The correct implementation returns False for equality, but the regression
    # changes it to return True.
    assert not version1 > version2
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

    # The correct implementation returns False for equality, but the regression
    # changes it to return True.
    assert not version1 > version2
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 11/12 — `05cc88d0e0cba70d` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (87 tokens in 13.81s):*

```python
import semver

def test_placebo_candidate():
    version = semver.Version.parse("1.0.0")
    match_expr = ">1.0.0"
    
    # Correct behavior: should return False
    assert not version.match(match_expr)

    match_expr = "<1.0.0"
    
    # Correct behavior: should return False
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
    
    # Correct behavior: should return False
    assert not version.match(match_expr)

    match_expr = "<1.0.0"
    
    # Correct behavior: should return False
    assert not version.match(match_expr)
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 12/12 — `1ca242d1ca74bb80` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (72 tokens in 10.97s):*

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

### Attempt 2

*Agent produced (116 tokens in 16.85s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.VersionInfo.parse("3.4.5-rc.1+build.9")
    
    # Correct behavior: token == "" should result in "0"
    correct_result = ver.bump_build(token="")
    assert str(correct_result.build) == "0"

    # Incorrect behavior: token != "" should not change the build number
    incorrect_result = ver.bump_build(token="test")
    assert str(incorrect_result.build) == "build.10"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code

### Attempt 3

*Agent produced (59 tokens in 8.85s):*

```python
import semver

def test_placebo_candidate():
    ver = semver.VersionInfo.parse("3.4.5-rc.1+build.9")
    correct_result = ver.bump_build(token="")
    assert str(correct_result.build) == "0"
```

*Tool response — admission gates:*

- passed: `static`
- **REJECTED** `CLEAN_HEAD_FAILED` — candidate fails against correct code


---
