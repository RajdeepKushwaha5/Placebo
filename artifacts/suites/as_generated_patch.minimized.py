"""An unedited pull request of agent-written tests.

Assembled by scripts/build_as_generated_patch.py from the raw output of every
generation condition in this project. No test was hand-written, reordered by
quality, or removed. This is the input to `scripts/run_audit.py`.
"""

import pytest
import semver




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


# fault detected: semver/version.py:730 in Version.is_compatible: `False` -> `None` (return_value)
# mutant id: 95f32034b4f97f3d
def test_ai_gap_02():
    """Detects: semver/version.py:730 in Version.is_compatible: `False` -> `None` (return_value)"""
    assert repr(semver.Version.parse("0.1.0").is_compatible(semver.Version.parse("0.0.1"))) == 'False'
    assert repr(semver.Version.parse("0.0.1").is_compatible(semver.Version.parse("0.1.0"))) == 'False'
