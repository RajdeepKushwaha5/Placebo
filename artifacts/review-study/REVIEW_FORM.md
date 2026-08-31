# Blinded review form

You are reviewing 5 candidate test patches for `python-semver`. You do not
know which tool or process produced any of them, and the order is randomized.

For **each** patch, please record:

| # | question | scale |
|---|---|---|
| 1 | Would you merge this as-is? | yes / with changes / no |
| 2 | Is it readable? | 1 (poor) - 5 (excellent) |
| 3 | Does it capture behavior worth protecting? | 1 - 5 |
| 4 | Would it catch a realistic future regression? | 1 - 5 |
| 5 | How confident are you in answers 1-4? | 1 - 5 |
| 6 | Minutes spent reviewing this patch | integer |

Free text, per patch:

- What is the strongest test here, and why?
- What is the weakest, and why?
- Anything that would make you reject the patch outright?

## Rules

- Review in the order given. Do not skip ahead.
- Do not run the tests. Judge them as a reviewer reading a pull request.
- Record minutes honestly, including time spent confused.
- If you recognize a patch's origin, say so - it means blinding failed.

## Patches

- `patches/patch_01.py`
- `patches/patch_02.py`
- `patches/patch_03.py`
- `patches/patch_04.py`
- `patches/patch_05.py`

Return the completed form to the study coordinator. Ratings are analyzed with
`scripts/analyze_review_study.py`, which unblinds only after all ratings are in.
