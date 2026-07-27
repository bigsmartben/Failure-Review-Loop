COLLECTION_BLOCKER_CODES = frozenset({
    "CODEX_SOURCE_UNAVAILABLE",
    "ANALYSIS_TARGET_CONVERSATIONS_NOT_FOUND",
})


class SddFrlError(Exception):
    """A stable, user-facing contract failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
