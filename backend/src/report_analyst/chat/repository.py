"""Conversations on disk: one JSON file each."""

from pathlib import Path
from uuid import UUID

from report_analyst.chat.models import Conversation
from report_analyst.storage import write_atomic


class ConversationRepository:
    """Stores Conversations as `<id>.json` in one folder."""

    def __init__(self, conversations_dir: Path) -> None:
        """Create the repository, making the folder if it is missing.

        Args:
            conversations_dir: The folder.
        """
        self._dir = conversations_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def get(self, conversation_id: UUID) -> Conversation | None:
        """Get a Conversation.

        Args:
            conversation_id: Its id.

        Returns:
            The Conversation, or None if there's none with this id.
        """
        path = self._dir / f"{conversation_id}.json"
        return Conversation.model_validate_json(path.read_bytes()) if path.exists() else None

    def save(self, conversation: Conversation) -> None:
        """Save a Conversation, replacing the stored one.

        Args:
            conversation: The Conversation.
        """
        path = self._dir / f"{conversation.conversation_id}.json"
        write_atomic(path, conversation.model_dump_json(indent=2).encode())
