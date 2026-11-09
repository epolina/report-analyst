"""One-off: rename the old field names in stored reports and Conversations.

The API and the stored JSON now use `company_name`, `reporting_year` and `page_count`. Files
written before that still say `year` (report metadata, chat Evidence), `company` (chat scope) and
`pages` (report metadata), and no longer load. Run this once, with the app stopped, from `backend/`:

    uv run python scripts/migrate_field_names.py [DATA_DIR]

DATA_DIR defaults to `data`, the app's default (`REPORTS_DIR=data/reports`,
`CONVERSATIONS_DIR=data/conversations`). Running it again changes nothing.
"""

import json
import sys

from pathlib import Path
from typing import Any


def _rename(obj: dict[str, Any], old: str, new: str) -> bool:
    if old not in obj:
        return False
    obj[new] = obj.pop(old)
    return True


def _migrate_report(metadata: dict[str, Any]) -> bool:
    # `|`, not `or`: both renames must run.
    return _rename(metadata, "year", "reporting_year") | _rename(metadata, "pages", "page_count")


def _migrate_conversation(conversation: dict[str, Any]) -> bool:
    changed = False
    for turn in conversation.get("turns", []):
        changed |= _rename(turn["scope"], "company", "company_name")
        for evidence in turn["answer"].get("evidence", []):
            changed |= _rename(evidence, "year", "reporting_year")
    return changed


def _migrate(files: list[Path], migrate: Any) -> int:
    changed = 0
    for path in files:
        data = json.loads(path.read_text())
        if migrate(data):
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(path)  # whole or not at all
            changed += 1
    return changed


def main() -> None:
    """Migrate every stored report and Conversation under the data folder."""
    data_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    reports = sorted((data_dir / "reports").glob("*/metadata.json"))
    conversations = sorted((data_dir / "conversations").glob("*.json"))
    print(f"Reports: {_migrate(reports, _migrate_report)} of {len(reports)} updated")
    print(
        f"Conversations: {_migrate(conversations, _migrate_conversation)}"
        f" of {len(conversations)} updated"
    )


if __name__ == "__main__":
    main()
