PY ?= python

.PHONY: historical multirepo metamorphic variance seeds equal-budget review-study package evidence-page gap-search audit setup census pipeline real-gaps rescore test report bundle real-gap-bundle verify verify-real-gaps trajectories check reproduce

setup:                ## install pinned dependencies
	$(PY) -m pip install -r requirements.lock

test:                 ## run Placebo's own unit tests
	$(PY) -m pytest tests -q

census:               ## measure the subject's expert suite against every mutant
	$(PY) scripts/run_census.py --workers 6

pipeline:             ## full experiment: all conditions, held-out scoring
	$(PY) scripts/run_pipeline.py --conditions baseline_A mutant_aware_B1 placebo_B placebo_C placebo_D

real-gaps:            ## close confirmed gaps in the subject's actual expert suite
	$(PY) scripts/run_real_gap_closure.py

rescore:              ## assemble fair suites and score stored runs without model calls
	$(PY) scripts/rescore.py

report:               ## rebuild the comparison report from stored results
	$(PY) scripts/build_report.py

bundle:               ## build the proof-carrying evidence bundle
	$(PY) scripts/build_bundle.py

real-gap-bundle:      ## bundle the merge-ready patch for confirmed repository gaps
	$(PY) scripts/build_bundle.py --real-gaps --out artifacts/real-gap-bundle

verify:               ## independently re-verify every claim in the bundle
	$(PY) scripts/verify_bundle.py --bundle artifacts/bundle

verify-real-gaps:     ## independently re-verify the real-gap patch claims
	$(PY) scripts/verify_bundle.py --bundle artifacts/real-gap-bundle

trajectories:         ## render human-readable agent trajectories
	$(PY) scripts/export_trajectories.py

gap-search:           ## close confirmed real gaps by deterministic search (no model calls)
	$(PY) scripts/run_gap_search.py

audit:                ## audit a patch for marginal fault-detection value
	$(PY) scripts/build_as_generated_patch.py
	$(PY) scripts/run_audit.py --suite artifacts/suites/as_generated_patch.py

historical:           ## evaluate against real bugs that shipped in semver 3.0.4
	$(PY) scripts/run_historical_bugs.py

multirepo:            ## run the census across every subject repository
	$(PY) scripts/run_multirepo_census.py

metamorphic:          ## level-3 oracle: properties, no hardcoded expected values
	$(PY) scripts/run_metamorphic.py

variance:             ## bootstrap spread from stored repeated runs
	$(PY) scripts/run_variance.py

seeds:                ## repeat the headline conditions for error bars
	$(PY) scripts/run_seeds.py --repeats 3

equal-budget:         ## control: does scaffolding help, or just more calls?
	$(PY) scripts/run_equal_budget.py --samples 3

review-study:         ## build the blinded reviewer packet (instrument only)
	$(PY) scripts/build_review_study.py

package:              ## build and verify the submission archive
	$(PY) scripts/package_submission.py

evidence-page:        ## render the self-contained HTML evidence page
	$(PY) scripts/build_evidence_page.py

check:                ## cross-check every headline claim against its evidence
	$(PY) scripts/check_consistency.py

reproduce: setup test census pipeline real-gaps rescore report bundle real-gap-bundle verify verify-real-gaps trajectories check  ## end-to-end from a clean clone
