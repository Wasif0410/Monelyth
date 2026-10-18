"""Errors raised by the LLM client. Their messages are written to be shown to the user."""

from __future__ import annotations


class LLMError(Exception):
    """Base class for every error the LLM client raises."""


class LLMConfigError(LLMError, ValueError):
    """The LLM settings are invalid, for example a server address that isn't this computer."""


class LLMUnavailableError(LLMError):
    """The server can't be used right now: it isn't running, is too slow, or lacks the model.

    Retrying the same request won't help until something about the server changes.
    """


class LLMResponseError(LLMError):
    """The server answered this one request, but not with something usable.

    Other requests may still succeed, so callers working through a batch can move on.
    """
