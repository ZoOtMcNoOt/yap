"""Stable failures at the isolated LID preflight boundary."""


class LidPreflightCancelled(RuntimeError):
    """The caller or server lifecycle cancelled an active preflight."""


class LidPreflightConflict(RuntimeError):
    """A request identity conflicts with work that is already active."""


class LidPreflightUnavailable(RuntimeError):
    """The isolated preflight cannot safely accept or finish work."""
