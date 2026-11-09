"""Writing files on disk safely."""

from pathlib import Path
from uuid import uuid4


def write_atomic(path: Path, data: bytes) -> None:
    """Write a file whole or not at all.

    Writes a temporary file, then renames it, so a crash mid-write never leaves a half-written
    file in place. The temporary name is unique, so two requests writing the same file don't
    collide.

    Args:
        path: The file.
        data: Its new contents.
    """
    tmp = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
