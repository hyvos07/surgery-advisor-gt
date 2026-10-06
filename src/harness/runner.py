"""Runs one surgery with any policy; seeds and outcomes."""

import copy
import random
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from advisor import knowledge
from advisor.config import ANTISEPTIC_DRAFT, ANTISEPTIC_MINIMAL, Config
from advisor.engine import decide
from advisor.memory import Memory
from advisor.state import ScreenState
from harness.baseline import baseline_policy, train_e_plus_policy
from harness.observe import observe, strip_formatting
from harness.surge import (
    CONDITION_NAMES,
    MALADY_NAMES,
    TOOL_TYPES,
    Patient,
    start_surgery,
)

MAX_TURNS = 80  # stands in for the real game's 2-minute timer

SUCCESS = "success"
AVOIDABLE_DEATH = "avoidable_death"
UNLUCKY_DEATH = "unlucky_death"
TIMEOUT = "timeout"

# A policy gets the screen state and the patient, and returns
# {"tool": ..., "rule": ..., "reason": ...}. Only the Train-E baseline may look at
# the patient (for SurgE's own tips); the advisor must use the screen state alone.
Policy = Callable[[dict[str, Any], Patient], dict[str, str]]
Record = dict[str, Any]

# SurgE draws from Python's global `random`, so every call to it runs under this
# lock with the surgery's own generator swapped in (see surge_random).
_RANDOM_LOCK = threading.RLock()


@contextmanager
def surge_random(rng: random.Random) -> Iterator[None]:
    """Run SurgE's code with `rng` as the global random state, then swap back.

    Each surgery owns a generator, so the same seed always plays the same way and
    interleaved surgeries (the web viewer) can't change each other's rolls.
    """
    with _RANDOM_LOCK:
        saved = random.getstate()
        random.setstate(rng.getstate())
        try:
            yield
        finally:
            rng.setstate(random.getstate())
            random.setstate(saved)


@dataclass(frozen=True)
class Settings:
    malady: str
    condition: str = "none"
    skill: int = 100
    modifier: str | None = None
    seed: int = 0


@dataclass(frozen=True)
class Result:
    settings: Settings
    policy: str
    outcome: str
    turns: int
    tools_used: int
    tool_counts: dict[str, int]
    skill_fails: int
    illegal_moves: int
    end_text: str


class AdvisorPolicy:
    """The rule engine as a policy: one instance per surgery, because it has memory.

    It ignores `patient` and sees only the screen state, like a player would.
    The `Config` is built from the first state's skill and modifier.
    """

    def __init__(self, antiseptic_mode: str = ANTISEPTIC_MINIMAL) -> None:
        self.antiseptic_mode = antiseptic_mode
        self.memory = Memory.new(knowledge.load())
        self.config: Config | None = None

    def __call__(self, state: dict[str, Any], patient: Patient) -> dict[str, str]:
        screen = ScreenState.from_dict(state)
        if self.config is None:
            self.config = Config.for_patient(
                screen.skill_level,
                screen.modifier.value if screen.modifier else None,
                antiseptic_mode=self.antiseptic_mode,
            )
        return decide(screen, self.memory, self.config).to_dict()


# Each entry builds a new policy, so no memory is shared between surgeries.
_POLICY_FACTORIES: dict[str, Callable[[], Policy]] = {
    "advisor": AdvisorPolicy,
    "advisor-draft-antiseptic": lambda: AdvisorPolicy(ANTISEPTIC_DRAFT),
    "baseline": lambda: baseline_policy,
    "train-e-plus": lambda: train_e_plus_policy,
}
POLICY_NAMES = tuple(_POLICY_FACTORIES)


def policy_by_name(name: str) -> Policy:
    """A fresh policy. Call it once per surgery: the advisor keeps memory."""
    factory = _POLICY_FACTORIES.get(name)
    if factory is None:
        raise ValueError(
            f"unknown policy {name!r}; choose from {', '.join(POLICY_NAMES)}"
        )
    return factory()


def resolve_settings(
    malady: str | None = None,
    condition: str | None = None,
    skill: int | None = None,
    modifier: str | None = None,
    seed: int | None = None,
) -> Settings:
    """Fill blank fields at random. The same seed always fills them the same way.

    A blank modifier means no modifier, as in the benchmark grid.
    """
    if seed is None:
        seed = random.SystemRandom().randrange(2**31)
    pick = random.Random(f"settings-{seed}")
    return Settings(
        malady=malady or pick.choice(MALADY_NAMES),
        condition=condition or pick.choice(list(CONDITION_NAMES)),
        skill=pick.randint(0, 100) if skill is None else skill,
        modifier=modifier,
        seed=seed,
    )


def _is_success(patient: Patient) -> bool:
    return bool(patient.IsSurgeryEnded) and "success" in patient.EndText.lower()


class Surgery:
    """One surgery that moves one turn per `step()`.

    `state` is the current screen and `decision` the policy's pending pick for
    it; both are None-able only after the surgery ends (`decision` is None then).
    """

    def __init__(
        self,
        settings: Settings,
        policy: Policy,
        policy_name: str = "policy",
        max_turns: int = MAX_TURNS,
    ) -> None:
        self.settings = settings
        self.policy = policy
        self.policy_name = policy_name
        self.max_turns = max_turns
        self.rng = random.Random(settings.seed)
        with surge_random(self.rng):
            self.patient = start_surgery(
                settings.malady, settings.condition, settings.skill, settings.modifier
            )
        self.turn = 0
        self.applied: list[str] = []
        self.skill_fails = 0
        self.illegal_moves = 0
        self.outcome: str | None = None
        self.end_text = ""
        self.state: dict[str, Any] = observe(self.patient)
        self.decision: dict[str, str] | None = self.policy(self.state, self.patient)

    @property
    def ended(self) -> bool:
        return self.outcome is not None

    def step(self) -> Record:
        """Apply the pending decision, run SurgE's turn, and return the turn record."""
        if self.decision is None:
            raise RuntimeError("the surgery has ended")
        state, decision = self.state, self.decision

        # An unusable tool is rejected and recorded; the Sponge (always usable) is
        # applied instead so the surgery can go on.
        legal = decision.get("tool") in state["usable_tools"]
        tool = decision["tool"] if legal else "sponge"
        if not legal:
            self.illegal_moves += 1

        with surge_random(self.rng):
            skill_fail = bool(self.patient.UseTool(TOOL_TYPES[tool]))
        self.applied.append(tool)
        self.skill_fails += skill_fail

        record: Record = {
            "seed": self.settings.seed,
            "malady": self.settings.malady,
            "condition": self.settings.condition,
            "skill": self.settings.skill,
            "modifier": self.settings.modifier,
            "policy": self.policy_name,
            "turn": self.turn,
            "state": state,
            "decision": decision,
            "legal": legal,
            "applied_tool": tool,
            "tool_text": strip_formatting(self.patient.ToolText),
            "skill_fail": skill_fail,
        }
        self.turn += 1

        if self.patient.IsSurgeryEnded:
            self.end_text = strip_formatting(self.patient.EndText)
            self.outcome = (
                SUCCESS if _is_success(self.patient) else self._classify_death()
            )
        elif self.turn >= self.max_turns:
            self.outcome = TIMEOUT
        record["ended"] = self.ended
        record["outcome"] = self.outcome

        if self.ended:
            self.decision = None
        else:
            self.state = observe(self.patient)
            self.decision = self.policy(self.state, self.patient)
        return record

    def result(self) -> Result:
        if self.outcome is None:
            raise RuntimeError("the surgery has not ended")
        return Result(
            settings=self.settings,
            policy=self.policy_name,
            outcome=self.outcome,
            turns=self.turn,
            tools_used=len(self.applied),
            tool_counts=dict(Counter(self.applied)),
            skill_fails=self.skill_fails,
            illegal_moves=self.illegal_moves,
            end_text=self.end_text,
        )

    def _classify_death(self) -> str:
        """Avoidable if the policy broke the rules or another tool would have lived.

        The check is one turn deep: replay the surgery up to the fatal turn, then
        try every other usable tool from that same state and random draw. A mistake
        made turns earlier (never clamping a bleed, say) still counts as unlucky.
        """
        if self.illegal_moves:
            return AVOIDABLE_DEATH
        patient = start_surgery(
            self.settings.malady,
            self.settings.condition,
            self.settings.skill,
            self.settings.modifier,
        )
        rng = random.Random(self.settings.seed)
        *before, fatal = self.applied
        for tool in before:
            with surge_random(rng):
                patient.UseTool(TOOL_TYPES[tool])
        for alternative in observe(patient)["usable_tools"]:
            if alternative == fatal:
                continue
            trial, trial_rng = copy.deepcopy(patient), random.Random()
            trial_rng.setstate(rng.getstate())
            with surge_random(trial_rng):
                trial.UseTool(TOOL_TYPES[alternative])
            if not trial.IsSurgeryEnded or _is_success(trial):
                return AVOIDABLE_DEATH
        return UNLUCKY_DEATH


def run_surgery(
    settings: Settings,
    policy: Policy,
    policy_name: str = "policy",
    *,
    max_turns: int = MAX_TURNS,
    on_record: Callable[[Record], None] | None = None,
) -> Result:
    """Play one surgery to its end; `on_record` receives each turn's log record."""
    surgery = Surgery(settings, policy, policy_name, max_turns)
    while not surgery.ended:
        record = surgery.step()
        if on_record is not None:
            on_record(record)
    return surgery.result()
