# Trajectory — condition `real_gap_closure`

- **Context condition**: `D (oracle-grounded), confirmed real gaps`
- **Max attempts**: 3
- **Discovery faults attempted**: 6
- **Admitted**: 3
- **Model cost**: 13 calls, 3598 output tokens, 472 model-seconds, $0.00

Every attempt below was judged by executing pytest, never by asking the model to grade itself. The admission gates are:

- `static` — static checks (parses, defines a test, no forbidden patterns, has an assertion)
- `clean_head` — passes against the CORRECT implementation
- `kills_target` — FAILS against the injected fault — the test detects it
- `repeat_stable` — same verdict on repeat runs

---

## Fault 1/6 — `33797d243637a3c5` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (79 tokens in 9.65s):*

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:637 in Version.parse: `%` -> `*` (arithmetic)"""
    with pytest.raises(TypeError):
        semver.Version.parse(1.0)
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`
- **REJECTED** `TARGET_MUTANT_SURVIVED` — candidate does not detect the injected fault
- fault status under this test: `survived`

### Attempt 2

*Agent produced (116 tokens in 15.02s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 3

*Agent produced (162 tokens in 21.48s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy


---

## Fault 2/6 — `400588ba9c9f77f9` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (156 tokens in 20.7s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 2

*Agent produced (486 tokens in 63.73s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 3

*Agent produced (486 tokens in 63.99s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy


---

## Fault 3/6 — `7c644c64bde4883c` — ADMITTED

Attempts used: 2

### Attempt 1

*Agent produced (121 tokens in 15.59s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 2

*Agent produced (546 tokens in 72.14s):*

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:598 in Version.match: `0` -> `1` (constant)"""
    assert repr(semver.Version.parse("1.0.0").match(">=1.0.0")) == 'True'
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:598 in Version.match: `0` -> `1` (constant)"""
    assert repr(semver.Version.parse("1.0.0").match(">=1.0.0")) == 'True'
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 4/6 — `95f32034b4f97f3d` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (155 tokens in 20.05s):*

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:730 in Version.is_compatible: `False` -> `None` (return_value)"""
    assert repr(semver.Version.parse("0.1.0").is_compatible(semver.Version.parse("0.0.1"))) == 'False'
    assert repr(semver.Version.parse("0.0.1").is_compatible(semver.Version.parse("0.1.0"))) == 'False'
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:730 in Version.is_compatible: `False` -> `None` (return_value)"""
    assert repr(semver.Version.parse("0.1.0").is_compatible(semver.Version.parse("0.0.1"))) == 'False'
    assert repr(semver.Version.parse("0.0.1").is_compatible(semver.Version.parse("0.1.0"))) == 'False'
```

> Proven: passes on correct code, fails on the injected fault.


---

## Fault 5/6 — `a6eb2ad4fd7271ea` — NOT ADMITTED

Attempts used: 3

### Attempt 1

*Agent produced (157 tokens in 20.05s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 2

*Agent produced (487 tokens in 64.56s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy

### Attempt 3

*Agent produced (517 tokens in 68.14s):*

```python

```

*Tool response — admission gates:*

- **REJECTED** `TARGET_MUTANT_SURVIVED` — no proposed expression distinguished clean from buggy


---

## Fault 6/6 — `bad59b17cefa1f72` — ADMITTED

Attempts used: 1

### Attempt 1

*Agent produced (130 tokens in 16.65s):*

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:599 in Version.match: `0` -> `1` (constant)"""
    assert repr(semver.Version.parse("1.0.0").match("<=1.0.0")) == 'True'
    assert repr(semver.Version.parse("1.0.0").match("<=0.9.9")) == 'False'
    assert repr(semver.Version.parse("2.0.0").match("<=1.0.0")) == 'False'
    assert repr(semver.Version.parse("1.0.0").match("<=1.0.0-alpha")) == 'False'
    assert repr(semver.Version.parse("1.0.0").match("<=1.0.0+build.1")) == 'True'
```

*Tool response — admission gates:*

- passed: `static`, `clean_head`, `kills_target`
- **ADMITTED** — passes clean HEAD and detects the injected fault

### Final admitted test

```python
import pytest
import semver


def test_placebo_candidate():
    """Detects: semver/version.py:599 in Version.match: `0` -> `1` (constant)"""
    assert repr(semver.Version.parse("1.0.0").match("<=1.0.0")) == 'True'
    assert repr(semver.Version.parse("1.0.0").match("<=0.9.9")) == 'False'
    assert repr(semver.Version.parse("2.0.0").match("<=1.0.0")) == 'False'
    assert repr(semver.Version.parse("1.0.0").match("<=1.0.0-alpha")) == 'False'
    assert repr(semver.Version.parse("1.0.0").match("<=1.0.0+build.1")) == 'True'
```

> Proven: passes on correct code, fails on the injected fault.


---
