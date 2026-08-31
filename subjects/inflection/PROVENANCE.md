# Subject provenance - inflection

Third-party code that existed before the competition. System under test, not
part of Placebo's contribution.

| Field | Value |
|---|---|
| Project | inflection |
| Upstream | https://github.com/jpvanhal/inflection |
| Tag | `0.5.1` |
| Commit | `b00d4d348b32ef5823221b20ee4cbd1d2d924462` |
| Licence | MIT (see `LICENSE`) |
| Vendored on | 2026-08-31 |

## Why this second subject

Placebo's first subject (semver) is comparison- and boundary-heavy. inflection
is **string transformation** logic - pluralisation, camelise, underscore,
titleize - a structurally different fault surface. If the method only worked on
numeric boundary comparisons, it would show here.

- 455 tests in ~0.43 s
- Pure Python, no compiled or network dependencies
- MIT licensed

## Modifications when vendoring

`test_inflection.py` moved to `tests/` so the runner's layout matches the
semver subject. Content byte-identical. No source file modified.
