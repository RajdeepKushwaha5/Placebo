"""Local model client (Ollama).

Placebo deliberately runs against a *local* model. That is a design decision,
not a limitation:

* judges reproduce every result with no API key, no credentials in the
  submission, and no marginal cost;
* generation is pinned by model digest, ``temperature=0`` and a fixed seed;
* the central claim -- that deterministic verification beats direct prompting --
  is a claim about the harness, so a modest model makes it easier to see, not
  harder.

Every call is recorded to a trajectory log so the submission can show exactly
what the agent was asked and what it produced.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

DEFAULT_HOST = "http://127.0.0.1:11434"


@dataclass
class Completion:
    """One model call, with everything needed to audit or replay it."""

    model: str
    prompt: str
    system: str
    text: str
    prompt_tokens: int
    output_tokens: int
    duration_s: float
    options: dict
    error: str = ""

    @property
    def tokens_per_s(self) -> float:
        return self.output_tokens / self.duration_s if self.duration_s else 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ModelConfig:
    """Frozen generation settings. Recorded verbatim in the evidence bundle."""

    model: str = "qwen2.5:7b"
    temperature: float = 0.0
    seed: int = 7
    num_ctx: int = 8192
    num_predict: int = 900
    top_p: float = 1.0
    host: str = DEFAULT_HOST
    timeout_s: int = 900

    def options(self) -> dict:
        return {
            "temperature": self.temperature,
            "seed": self.seed,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "top_p": self.top_p,
        }


class LocalModel:
    """Thin, dependency-free Ollama client with trajectory recording."""

    def __init__(self, config: ModelConfig | None = None, trajectory: Path | None = None):
        self.config = config or ModelConfig()
        self.trajectory = trajectory
        self.calls: list[Completion] = []

    # -- introspection -----------------------------------------------------

    def digest(self) -> str:
        """Model content digest, pinned in the evidence bundle."""
        try:
            with urllib.request.urlopen(f"{self.config.host}/api/tags", timeout=10) as r:
                for m in json.load(r).get("models", []):
                    if m.get("name") == self.config.model:
                        return m.get("digest", "")
        except OSError:
            pass
        return ""

    def available(self) -> bool:
        return bool(self.digest())

    # -- generation --------------------------------------------------------

    def complete(self, prompt: str, system: str = "", **overrides) -> Completion:
        """Single deterministic completion."""
        options = {**self.config.options(), **overrides}
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if system:
            payload["system"] = system

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.config.host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )

        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_s) as r:
                data = json.load(r)
            completion = Completion(
                model=self.config.model,
                prompt=prompt,
                system=system,
                text=data.get("response", ""),
                prompt_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
                duration_s=time.perf_counter() - start,
                options=options,
            )
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            completion = Completion(
                model=self.config.model,
                prompt=prompt,
                system=system,
                text="",
                prompt_tokens=0,
                output_tokens=0,
                duration_s=time.perf_counter() - start,
                options=options,
                error=f"{type(exc).__name__}: {exc}",
            )

        self.calls.append(completion)
        self._record(completion)
        return completion

    def _record(self, completion: Completion) -> None:
        if not self.trajectory:
            return
        self.trajectory.parent.mkdir(parents=True, exist_ok=True)
        with self.trajectory.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(completion.to_dict(), ensure_ascii=False) + "\n")

    # -- accounting --------------------------------------------------------

    def usage(self) -> dict:
        return {
            "calls": len(self.calls),
            "prompt_tokens": sum(c.prompt_tokens for c in self.calls),
            "output_tokens": sum(c.output_tokens for c in self.calls),
            "model_seconds": round(sum(c.duration_s for c in self.calls), 1),
            "usd_cost": 0.0,  # local inference: no marginal cost
        }
