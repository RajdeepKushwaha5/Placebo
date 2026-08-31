# Trajectory — condition `placebo_D`

- **Context condition**: `D`
- **Max attempts**: 3
- **Discovery faults attempted**: 12
- **Admitted**: 7
- **Model cost**: 23 calls, 5173 output tokens, 1040 model-seconds, $0.00

Every attempt below was judged by executing pytest, never by asking the model to grade itself. The admission gates are:

- `static` — static checks (parses, defines a test, no forbidden patterns, has an assertion)
- `clean_head` — passes against the CORRECT implementation
- `kills_target` — FAILS against the injected fault — the test detects it
- `repeat_stable` — same verdict on repeat runs

---

## Fault 1/12 — `0a016d6d36518355` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (121 tokens in 15.19s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 2

*Agent produced (357 tokens in 45.92s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 3

*Agent produced (356 tokens in 46.18s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy


---

## Fault 2/12 — `1ac3986cca492880` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (174 tokens in 22.69s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 2

*Agent produced (243 tokens in 31.0s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 3

*Agent produced (238 tokens in 45.69s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy


---

## Fault 3/12 — `03fe90d993fa6512` — ADMITTED

Attempts used: 2

### Attempt 1

*Agent produced (140 tokens in 64.68s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 2

*Agent produced (328 tokens in 87.82s):*

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:475 in Version.__lt__: `<` -> `<=` (comparison_boundary)"""
    assert repr(semver.Version.parse("1.0.0") < semver.Version.parse("1.0.0")) == 'False'
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:475 in Version.__lt__: `<` -> `<=` (comparison_boundary)"""
    assert repr(semver.Version.parse("1.0.0") < semver.Version.parse("1.0.0")) == 'False'
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 4/12 — `0311cef58a002912` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (95 tokens in 25.28s):*

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:292 in Version.bump_minor: `1` -> `2` (constant)"""
    assert repr(semver.Version.parse("3.4.5").bump_minor()) == 'Version(major=3, minor=5, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("2.9.9").bump_minor()) == 'Version(major=2, minor=10, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("3.4.9").bump_minor()) == 'Version(major=3, minor=5, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.0.0").bump_minor()) == 'Version(major=1, minor=1, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("3.4.0").bump_minor()) == 'Version(major=3, minor=5, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("3.3.9").bump_minor()) == 'Version(major=3, minor=4, patch=0, prerelease=None, build=None)'
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:292 in Version.bump_minor: `1` -> `2` (constant)"""
    assert repr(semver.Version.parse("3.4.5").bump_minor()) == 'Version(major=3, minor=5, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("2.9.9").bump_minor()) == 'Version(major=2, minor=10, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("3.4.9").bump_minor()) == 'Version(major=3, minor=5, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.0.0").bump_minor()) == 'Version(major=1, minor=1, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("3.4.0").bump_minor()) == 'Version(major=3, minor=5, patch=0, prerelease=None, build=None)'
    assert repr(semver.Version.parse("3.3.9").bump_minor()) == 'Version(major=3, minor=4, patch=0, prerelease=None, build=None)'
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 5/12 — `1486704c2686bc4b` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (88 tokens in 32.94s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 2

*Agent produced (511 tokens in 99.62s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 3

*Agent produced (511 tokens in 85.57s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy


---

## Fault 6/12 — `5c7e1209a4ecd4ba` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (91 tokens in 53.4s):*

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:636 in Version.parse: `not ` -> `` (negation)"""
    assert repr(semver.Version.parse("1.0.0").major) == '1'
    assert repr(semver.Version.parse("1.0.0").minor) == '0'
    assert repr(semver.Version.parse("1.0.0").patch) == '0'
    assert repr(semver.Version.parse("1.0.0-pre").prerelease) == "'pre'"
    assert repr(semver.Version.parse("1.0.0+build").build) == "'build'"
    with pytest.raises(AttributeError):
        semver.Version.parse("1.2.3").is_prerelease
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:636 in Version.parse: `not ` -> `` (negation)"""
    assert repr(semver.Version.parse("1.0.0").major) == '1'
    assert repr(semver.Version.parse("1.0.0").minor) == '0'
    assert repr(semver.Version.parse("1.0.0").patch) == '0'
    assert repr(semver.Version.parse("1.0.0-pre").prerelease) == "'pre'"
    assert repr(semver.Version.parse("1.0.0+build").build) == "'build'"
    with pytest.raises(AttributeError):
        semver.Version.parse("1.2.3").is_prerelease
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 7/12 — `0723feea7643f22a` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (113 tokens in 18.43s):*

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:554 in Version.finalize_version: `cls(self.major, self.minor, self.patch)` -> `None` (return_value)"""
    assert repr(semver.Version.parse("1.2.3-rc.5").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3+build.4").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3-alpha.1").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3-beta.99").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3-0.3.7").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3+04").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:554 in Version.finalize_version: `cls(self.major, self.minor, self.patch)` -> `None` (return_value)"""
    assert repr(semver.Version.parse("1.2.3-rc.5").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3+build.4").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3-alpha.1").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3-beta.99").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3-0.3.7").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
    assert repr(semver.Version.parse("1.2.3+04").finalize_version()) == 'Version(major=1, minor=2, patch=3, prerelease=None, build=None)'
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 8/12 — `1d331d5b9501ed06` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (78 tokens in 14.14s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 2

*Agent produced (244 tokens in 43.52s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 3

*Agent produced (244 tokens in 46.01s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy


---

## Fault 9/12 — `2efccfe40d947649` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (100 tokens in 22.35s):*

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:514 in Version.__getitem__: `and` -> `or` (boolean_logic)"""
    assert repr(semver.Version.parse("1.0.0")[0]) == '1'
    assert repr(semver.Version.parse("1.0.0")[slice(None, None, -1)]) == '(0, 0, 1)'
    assert repr(semver.Version.parse("1.0.0")[1]) == '0'
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:514 in Version.__getitem__: `and` -> `or` (boolean_logic)"""
    assert repr(semver.Version.parse("1.0.0")[0]) == '1'
    assert repr(semver.Version.parse("1.0.0")[slice(None, None, -1)]) == '(0, 0, 1)'
    assert repr(semver.Version.parse("1.0.0")[1]) == '0'
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 10/12 — `085c382c12637d90` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (140 tokens in 40.89s):*

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:483 in Version.__gt__: `>` -> `>=` (comparison_boundary)"""
    assert repr(semver.VersionInfo(1, 0, 0) > semver.VersionInfo(1, 0, 0)) == 'False'
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:483 in Version.__gt__: `>` -> `>=` (comparison_boundary)"""
    assert repr(semver.VersionInfo(1, 0, 0) > semver.VersionInfo(1, 0, 0)) == 'False'
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 11/12 — `05cc88d0e0cba70d` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (121 tokens in 38.77s):*

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:580 in Version.match: `0` -> `1` (constant)"""
    assert repr(semver.Version.parse("1.0.0").match(">1.0.0")) == 'False'
    assert repr(semver.Version.parse("1.0.0").match("<1.0.0")) == 'False'
    assert repr(semver.Version.parse("2.0.0").match(">1.0.0")) == 'True'
    assert repr(semver.Version.parse("0.0.0").match("<1.0.0")) == 'True'
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:580 in Version.match: `0` -> `1` (constant)"""
    assert repr(semver.Version.parse("1.0.0").match(">1.0.0")) == 'False'
    assert repr(semver.Version.parse("1.0.0").match("<1.0.0")) == 'False'
    assert repr(semver.Version.parse("2.0.0").match(">1.0.0")) == 'True'
    assert repr(semver.Version.parse("0.0.0").match("<1.0.0")) == 'True'
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 12/12 — `1ca242d1ca74bb80` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (107 tokens in 18.97s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 2

*Agent produced (349 tokens in 61.99s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 3

*Agent produced (424 tokens in 78.7s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy


---
