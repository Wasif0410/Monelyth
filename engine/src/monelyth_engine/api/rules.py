"""Categorization rules: the defaults, and adding, changing and deleting the user's own.

Every change re-categorizes, in the background, the transactions the rule matched before or
matches now, except those the user categorized themselves.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Annotated, Final, Self

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from monelyth_engine.api.categorization import Worker
from monelyth_engine.api.deps import Connection
from monelyth_engine.categorize.pipeline import RunScope
from monelyth_engine.categorize.rule_editing import (
    DuplicateRuleError,
    RuleChange,
    RuleDraft,
    add_rule,
    change_rule,
    preview_rule,
    remove_rule,
)
from monelyth_engine.categorize.rules import RulePatternError
from monelyth_engine.categorize.worker import CategorizationWorker
from monelyth_engine.db.rules import (
    ReadOnlyRuleError,
    Rule,
    RuleAuthor,
    RuleMatchType,
    get_rule,
    list_rules,
)

router = APIRouter(prefix="/rules", tags=["rules"])

MAX_PATTERN_INPUT: Final = 1000
"""Longer than any pattern accepted, so the length check that explains itself gets to run."""
MAX_PRIORITY: Final = 1000

_Pattern = Annotated[str, Field(max_length=MAX_PATTERN_INPUT)]
_Priority = Annotated[int, Field(ge=0, le=MAX_PRIORITY)]
_CategoryId = Annotated[int, Field(ge=1)]


class RuleOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    pattern: str
    match_type: RuleMatchType
    category_id: int
    priority: int
    """Among rules by the same author, the highest that matches wins."""
    created_by: RuleAuthor
    """``system`` rules are Monelyth's defaults and can't be changed; the user's always come
    first."""

    @classmethod
    def of(cls, rule: Rule) -> RuleOut:
        return cls(
            id=rule.id,
            pattern=rule.pattern,
            match_type=rule.match_type,
            category_id=rule.category_id,
            priority=rule.priority,
            created_by=rule.created_by,
        )


class RuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: _Pattern
    match_type: RuleMatchType = RuleMatchType.CONTAINS
    category_id: _CategoryId
    priority: _Priority = 0


class RuleUpdate(BaseModel):
    """Leave a field out to keep its current value."""

    model_config = ConfigDict(extra="forbid")

    pattern: _Pattern | None = None
    match_type: RuleMatchType | None = None
    category_id: _CategoryId | None = None
    priority: _Priority | None = None

    @model_validator(mode="after")
    def _require_a_change(self) -> Self:
        if self.model_fields_set.isdisjoint({"pattern", "match_type", "category_id", "priority"}):
            raise ValueError("Give at least one of pattern, match_type, category_id, priority")
        return self


class RulePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: _Pattern
    match_type: RuleMatchType = RuleMatchType.CONTAINS


class RulePreviewOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    matching: int
    """Stored transactions the pattern matches."""
    user_set: int
    """Of those, how many keep their category because you set it (or it's a linked transfer)."""
    examples: list[str]
    """A few of the merchant names it matches, most frequent first."""


@router.get("")
def get_rules(conn: Connection) -> list[RuleOut]:
    """Every rule in the order they are tried: yours first, then the defaults, each by priority
    (highest first) and then the longest pattern first."""
    return [RuleOut.of(rule) for rule in list_rules(conn)]


@router.post("/preview")
def post_rule_preview(body: RulePreviewRequest, conn: Connection) -> RulePreviewOut:
    """How many stored transactions a pattern matches, without saving anything. ``422`` with a
    readable message if the pattern can't be used."""
    with _rule_errors():
        preview = preview_rule(conn, body.pattern, body.match_type)
    return RulePreviewOut(
        matching=preview.matching, user_set=preview.user_set, examples=list(preview.examples)
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def post_rule(body: RuleCreate, conn: Connection, worker: Worker) -> RuleOut:
    """Add a rule. ``422`` if the pattern can't be used, ``409`` if you already have a rule with
    the same pattern."""
    draft = RuleDraft(
        pattern=body.pattern,
        match_type=body.match_type,
        category_id=body.category_id,
        priority=body.priority,
    )
    with _rule_errors():
        change = add_rule(conn, draft)
    return _recategorize(change, worker)


@router.patch("/{rule_id}")
def patch_rule(rule_id: int, body: RuleUpdate, conn: Connection, worker: Worker) -> RuleOut:
    """Change one of your rules. ``403`` for a default rule."""
    current = get_rule(conn, rule_id)
    draft = RuleDraft(
        pattern=current.pattern if body.pattern is None else body.pattern,
        match_type=current.match_type if body.match_type is None else body.match_type,
        category_id=current.category_id if body.category_id is None else body.category_id,
        priority=current.priority if body.priority is None else body.priority,
    )
    with _rule_errors():
        change = change_rule(conn, rule_id, draft)
    return _recategorize(change, worker)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, conn: Connection, worker: Worker) -> Response:
    """Delete one of your rules. ``403`` for a default rule."""
    with _rule_errors():
        change = remove_rule(conn, rule_id)
    _recategorize(change, worker)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _recategorize(change: RuleChange, worker: CategorizationWorker) -> RuleOut:
    if change.affected_ids:
        worker.request(RunScope(transaction_ids=change.affected_ids))
    return RuleOut.of(change.rule)


@contextmanager
def _rule_errors() -> Generator[None]:
    """Turn the rule editor's user-facing errors into HTTP errors carrying their message."""
    try:
        yield
    except RulePatternError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except DuplicateRuleError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except ReadOnlyRuleError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
