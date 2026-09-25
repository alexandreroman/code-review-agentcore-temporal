"""Worker-internal models passed between the pull request workflow and its children."""

from pydantic import BaseModel


class ChangedFile(BaseModel):
    path: str
    status: str
    additions: int
    deletions: int
    patch_bytes: int | None
