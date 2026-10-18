"""Which tiers a categorization run asks, and where the optional ones plug in.

Every run asks, in this order, and the first answer wins:

1. :func:`~monelyth_engine.categorize.memory.user_memory`: what the user taught by correcting.
2. :class:`~monelyth_engine.categorize.rules.RulesCategorizer`: the user's rules, then the
   defaults.
3. :func:`~monelyth_engine.categorize.memory.learned_memory`: earlier confident answers from
   the classifier or LLM.
4. The optional tiers from :attr:`PipelineExtensions.optional_tiers`, in the order given
   (classifier, then LLM).

Anything left unanswered goes to the review queue. Before the tiers, each
:attr:`PipelineExtensions.pre_passes` entry runs once (transfer linking).

**Plugging in a tier:** return it from the factory in :func:`installed_extensions`. That
function is the single place the app's tiers are configured; the background worker and
``scripts/eval_categorizer.py`` both use it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from monelyth_engine.categorize.memory import learned_memory, user_memory
from monelyth_engine.categorize.models import Categorizer
from monelyth_engine.categorize.rules import RulesCategorizer
from monelyth_engine.db.memory import MemoryEntry
from monelyth_engine.db.rules import Rule

TierFactory = Callable[[sqlite3.Connection], Sequence[Categorizer]]
"""Builds the optional tiers for one run.

Called at the start of every run with that run's connection, which a tier may read (e.g. for
labeled examples) but must not keep: tiers never write, and the connection closes when the run
ends. Expensive set-up such as loading a model belongs outside, in an object the factory closes
over, so it happens once per engine rather than once per run. If the factory raises, the run
continues with the built-in tiers and reports the problem.
"""


class PrePass(Protocol):
    """Work that runs over the stored transactions before the tiers, e.g. linking transfers.

    It writes through the connection itself, in its own
    :func:`~monelyth_engine.db.atomic.atomic` blocks, and must:

    - never change a transaction whose ``category_source`` is ``'user'``;
    - be idempotent, since it runs at the start of every run;
    - mark what it handled with ``transfer_group``: the tiers skip any transaction that has
      one, so a linked transfer keeps the category the pre-pass gave it.

    If it raises, the run logs it, carries on with the tiers and reports the problem.
    """

    @property
    def name(self) -> str:
        """What it does, for the user, e.g. ``"Transfer detection"``."""
        ...

    def run(self, conn: sqlite3.Connection) -> None: ...


@dataclass(frozen=True, slots=True)
class PipelineExtensions:
    """The parts of the pipeline that are not built in."""

    optional_tiers: TierFactory | None = None
    """Asked after memory and rules, in the order returned."""
    pre_passes: tuple[PrePass, ...] = ()


def installed_extensions() -> PipelineExtensions:
    """The optional tiers and pre-passes this build of the app runs.

    Plug the classifier and LLM tiers and the transfer pass in here, e.g.::

        return PipelineExtensions(
            optional_tiers=lambda conn: [classifier_tier, llm_tier],
            pre_passes=(TransferLinking(),),
        )
    """
    return PipelineExtensions()


def core_tiers(memory: Mapping[str, MemoryEntry], rules: Sequence[Rule]) -> list[Categorizer]:
    """The built-in tiers, in the order they are asked (see the module docstring)."""
    return [user_memory(memory), RulesCategorizer(rules), learned_memory(memory)]
