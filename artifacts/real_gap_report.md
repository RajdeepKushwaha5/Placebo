# Placebo — real gap closure

> **This is the intermediate agent-only run, not the final result.**
> It measures what the LLM agent achieved on its own: **3 of 6** confirmed gaps.
> The final end-to-end result uses deterministic counterexample search and
> closes **6 of 6** with zero model calls — see
> [`artifacts/report.md`](report.md) and
> [`../experiments/gap_search.json`](../experiments/gap_search.json).
> Both are kept so the improvement can be traced rather than asserted.


- Existing expert suite: **329 tests, 100% line and branch coverage**
- Confirmed detectable gaps before Placebo: **6**
- Generated tests retained: **3**
- Existing suite + patch remains green: **True**
- Confirmed gaps closed: **3/6 (50%)**
- Model calls: **13**; monetary cost: **$0**

This is the end-to-end product result. Unlike the authoring benchmark, every fault here actually survived the repository's existing suite and was separately confirmed to be behaviorally detectable.
