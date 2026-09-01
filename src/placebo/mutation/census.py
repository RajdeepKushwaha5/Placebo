"""Full-suite mutation census: which faults does the existing suite miss?

This is the measurement that motivates the whole project. It runs the subject's
own test suite against every enumerated mutant and records, per mutant, whether
the suite detects it.

Runs are parallelized across isolated workspaces. Each worker owns its own copy
of the subject, so a mutant applied in one worker can never be observed by
another. Results are keyed by content-derived mutant id, so the output is
order-independent and diffable across machines.
"""

from __future__ import annotations

import queue
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ..verification.runner import SubjectRunner
from .models import Mutant, MutantRun, MutantStatus


@dataclass
class CensusResult:
    """Aggregate outcome of a mutation census."""

    runs: dict[str, MutantRun]
    mutants: dict[str, Mutant]
    baseline_duration_s: float
    wall_s: float

    # -- scoring -----------------------------------------------------------

    def by_status(self, status: MutantStatus) -> list[Mutant]:
        return [
            self.mutants[mid]
            for mid, run in self.runs.items()
            if run.status is status and mid in self.mutants
        ]

    @property
    def scorable(self) -> list[str]:
        """Mutants that produce a meaningful killed/survived verdict.

        INVALID (broke collection), TIMEOUT and ERROR mutants are excluded from
        the denominator rather than silently counted as kills.
        """
        return [
            mid
            for mid, run in self.runs.items()
            if run.status in (MutantStatus.KILLED, MutantStatus.SURVIVED)
        ]

    @property
    def killed(self) -> list[str]:
        return [m for m in self.scorable if self.runs[m].status is MutantStatus.KILLED]

    @property
    def survived(self) -> list[str]:
        return [m for m in self.scorable if self.runs[m].status is MutantStatus.SURVIVED]

    @property
    def score(self) -> float:
        """Mutation score over scorable mutants, in [0, 1]."""
        if not self.scorable:
            return 0.0
        return len(self.killed) / len(self.scorable)

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for run in self.runs.values():
            counts[run.status.value] = counts.get(run.status.value, 0) + 1
        return {
            "total_mutants": len(self.runs),
            "scorable": len(self.scorable),
            "killed": len(self.killed),
            "survived": len(self.survived),
            "mutation_score": round(self.score, 4),
            "status_counts": counts,
            "baseline_duration_s": round(self.baseline_duration_s, 2),
            "wall_s": round(self.wall_s, 1),
        }


def run_census(
    subject_root: Path,
    workspace_root: Path,
    mutants: list[Mutant],
    workers: int = 4,
    timeout_s: int = 300,
    progress: bool = True,
    source_roots: tuple[str, ...] = (),
) -> CensusResult:
    """Run the subject suite against every mutant, in parallel."""
    subject_root = Path(subject_root)
    workspace_root = Path(workspace_root)

    # One isolated workspace per worker, handed out through a queue so a
    # worker never shares a mutated file with another.
    pool: queue.Queue[SubjectRunner] = queue.Queue()
    runners: list[SubjectRunner] = []
    for i in range(workers):
        runner = SubjectRunner(
            subject_root, workspace_root / f"w{i}", timeout_s=timeout_s,
            source_roots=source_roots,
        )
        runner.prepare()
        runners.append(runner)
        pool.put(runner)

    # The clean suite must be green, or every downstream verdict is meaningless.
    baseline = runners[0].check_baseline()
    if not baseline.passed:
        raise RuntimeError(
            "Subject baseline suite is not green; refusing to run a census.\n"
            f"exit={baseline.returncode}\n{baseline.stdout[-2000:]}"
        )

    results: dict[str, MutantRun] = {}
    done = 0
    start = time.perf_counter()

    def work(mutant: Mutant) -> tuple[str, MutantRun]:
        runner = pool.get()
        try:
            return mutant.id, runner.run_mutant(mutant)
        finally:
            pool.put(runner)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for mid, run in executor.map(work, mutants):
            results[mid] = run
            done += 1
            if progress and (done % 10 == 0 or done == len(mutants)):
                elapsed = time.perf_counter() - start
                rate = done / elapsed if elapsed else 0
                remaining = (len(mutants) - done) / rate if rate else 0
                print(
                    f"  [{done:>4}/{len(mutants)}] "
                    f"{elapsed:5.0f}s elapsed, ~{remaining:4.0f}s left",
                    flush=True,
                )

    return CensusResult(
        runs=results,
        mutants={m.id: m for m in mutants},
        baseline_duration_s=baseline.duration_s,
        wall_s=time.perf_counter() - start,
    )
