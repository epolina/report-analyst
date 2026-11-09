from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from report_analyst.chat.models import Conversation
from report_analyst.chat.repository import ConversationRepository


def test_saving_one_conversation_at_once_from_two_requests_does_not_crash(tmp_path: Path) -> None:
    # With one shared temporary name, one save renamed the other's file away mid-write.
    repository = ConversationRepository(tmp_path)
    conversation = Conversation()

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: repository.save(conversation), range(200)))

    assert repository.get(conversation.conversation_id) == conversation
    assert [p.name for p in tmp_path.iterdir()] == [f"{conversation.conversation_id}.json"]
