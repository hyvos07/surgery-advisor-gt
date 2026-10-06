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
from advisor.state import Decision, ScreenState, Tool
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

# The lookback asks "would a different tool at an earlier turn have saved it?" by
# playing the surgery on from there: the alternative must win 2 of 3 rollouts, and
# the tool the policy really used must not (same draws for both).
BRANCH_ROLLOUTS = 3
BRANCH_WINS_NEEDED = 2

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
    # For deaths only: how many turns before the fatal one a different tool would
    # have saved the surgery, and that tool. Both None when the death is unlucky,
    # when the cause was an illegal move, and for surgeries that did not die.
    mistake_turns_back: int | None = None
    alternative: str | None = None
    # Every alternative that worked at that turn, best first (`alternative` is the
    # first). Empty whenever `alternative` is None.
    alternatives: tuple[str, ...] = ()


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

    def note_override(self, tool: str) -> None:
        """Tell memory that `tool` was applied instead of the decision just made.

        The death analysis replaces a tool and plays on; memory must then confirm
        the replaced tool's effect, not the one the engine picked.
        """
        self.memory.last_decision = Decision(
            Tool(tool), "X0", "Branch: tool replaced for death analysis"
        )


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
        lookback: int = 1,
        classify: bool = True,
    ) -> None:
        if lookback < 1:
            raise ValueError(f"lookback must be at least 1, got {lookback}")
        self.settings = settings
        self.policy = policy
        self.policy_name = policy_name
        self.max_turns = max_turns
        self.lookback = lookback
        # A death is classified (and replayed from here) only in the real surgery;
        # the branches of the lookback turn this off, and a death is just a death.
        self._classify = classify
        # A branch needs a fresh policy that has seen nothing yet, so keep an
        # untouched copy (not in a branch itself, which never classifies).
        self._pristine_policy = copy.deepcopy(policy) if classify else None
        self.mistake_turns_back: int | None = None
        self.alternative: str | None = None
        self.alternatives: tuple[str, ...] = ()
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

    def step(self, override: str | None = None) -> Record:
        """Apply the pending decision, run SurgE's turn, and return the turn record.

        `override` applies another tool instead (the death analysis uses it); the
        policy is told, if it can be, so its memory follows what really happened.
        """
        if self.decision is None:
            raise RuntimeError("the surgery has ended")
        state, decision = self.state, self.decision
        if override is not None and override != decision["tool"]:
            note = getattr(self.policy, "note_override", None)
            if note is not None:
                note(override)
            decision = {
                "tool": override,
                "rule": "X0",
                "reason": "Branch: tool replaced for death analysis",
            }

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
            if _is_success(self.patient):
                self.outcome = SUCCESS
            elif self._classify:
                self.outcome = self._classify_death()
            else:
                self.outcome = UNLUCKY_DEATH  # a branch only needs "not a success"
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
            mistake_turns_back=self.mistake_turns_back,
            alternative=self.alternative,
            alternatives=self.alternatives,
        )

    def _classify_death(self) -> str:
        """Avoidable if the policy broke the rules or another tool would have won.

        At the fatal turn and then each turn before it, up to `lookback` turns,
        newest first: replay the surgery to that turn and play every other usable
        tool on to the end (see `_rollouts`). An alternative has to win the whole
        surgery, and the tool the policy really applied, given the same draws, must
        not win it too (then the death was luck at that depth). Nothing found means
        unlucky.
        """
        if self.illegal_moves:
            return AVOIDABLE_DEATH
        for back in range(min(self.lookback, len(self.applied))):
            turn = len(self.applied) - 1 - back
            branch = self._replay_to(turn)
            original = self.applied[turn]
            working: list[tuple[int, int, int, str]] = []
            for order, alternative in enumerate(branch.state["usable_tools"]):
                if alternative == original:
                    continue
                wins, tools = _rollouts(
                    branch, turn, alternative, run_all_when_working=True
                )
                if wins >= BRANCH_WINS_NEEDED:
                    working.append((-wins, tools, order, alternative))
            if not working:
                continue
            # The original tool is rolled out only when an alternative worked, and
            # with the same draws: if it wins too, the death was luck at this depth.
            wins, _ = _rollouts(branch, turn, original, run_all_when_working=False)
            if wins >= BRANCH_WINS_NEEDED:
                continue
            working.sort()
            self.mistake_turns_back, self.alternative = back, working[0][3]
            self.alternatives = tuple(w[3] for w in working)
            return AVOIDABLE_DEATH
        return UNLUCKY_DEATH

    def _replay_to(self, turn: int) -> "Surgery":
        """A branch point: a fresh policy and patient taken through `turn` turns.

        The tools applied in the real surgery are applied again, so the patient,
        the random state and the policy's memory are what they were at that turn;
        the policy's pending decision for it is made, but not applied.
        """
        assert self._pristine_policy is not None
        replay = Surgery(
            self.settings,
            copy.deepcopy(self._pristine_policy),
            self.policy_name,
            self.max_turns,
            classify=False,
        )
        for tool in self.applied[:turn]:
            replay.step(override=tool)
        return replay


def rollout_rng(seed: int, turn: int, rollout: int) -> random.Random:
    """The random state of rollout `rollout` at branch turn `turn`.

    It does not depend on the tool tried: every tool at a turn, the advisor's own
    included, gets the same draws in rollout r (common random numbers), so a tool
    is not credited or blamed for luck the others did not have.
    """
    return random.Random(f"{seed}-{turn}-r{rollout}")


def _rollouts(
    branch: Surgery, turn: int, tool: str, *, run_all_when_working: bool
) -> tuple[int, int]:
    """Wins and tools used in the winning rollouts of `tool` at the branch point.

    Each rollout starts from a copy of the branch point (policy memory included)
    with the turn's own seeded random state. It stops once the tool can no longer
    reach BRANCH_WINS_NEEDED wins, and, unless `run_all_when_working`, as soon as
    it has them; a tool that keeps going has its full count of wins.
    """
    wins = losses = tools = 0
    for rollout in range(BRANCH_ROLLOUTS):
        trial = copy.deepcopy(branch)
        trial.rng = rollout_rng(branch.settings.seed, turn, rollout)
        trial.step(override=tool)
        while not trial.ended:
            trial.step()
        if trial.outcome == SUCCESS:
            wins += 1
            tools += len(trial.applied)
        else:
            losses += 1
        if wins >= BRANCH_WINS_NEEDED and not run_all_when_working:
            break
        if losses > BRANCH_ROLLOUTS - BRANCH_WINS_NEEDED:
            break
    return wins, tools


def run_surgery(
    settings: Settings,
    policy: Policy,
    policy_name: str = "policy",
    *,
    max_turns: int = MAX_TURNS,
    lookback: int = 1,
    on_record: Callable[[Record], None] | None = None,
) -> Result:
    """Play one surgery to its end; `on_record` receives each turn's log record."""
    surgery = Surgery(settings, policy, policy_name, max_turns, lookback)
    while not surgery.ended:
        record = surgery.step()
        if on_record is not None:
            on_record(record)
    return surgery.result()
