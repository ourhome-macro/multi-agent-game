from __future__ import annotations


class ActionValidationError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
