# Ubiquitous language

The shared vocabulary for code, UI and conversation. If a term is here, use exactly this word everywhere (class names, API fields, UI labels). If code and this file disagree, fix one of them.

## Domain objects

| Term | Meaning | Rules |
|---|---|---|
| **Report** | One Company's annual report for one Reporting Year, as a PDF. | Unique per Company and Reporting Year. The same file (same SHA-256) is refused. The same Company and Reporting Year with a different file is either replaced (the id is kept) or kept alongside. The Reporting Year is the fiscal year covered, not the year of publication. A Company keeps the spelling it was first entered with, matched ignoring case, so "shell" is "Shell". Different names for one Company ("Royal Dutch Shell") aren't merged yet. |
| **Passage** | A span of a Report's text, with its page number. It's what search returns and what the LLM reads. | A Passage isn't a raw PDF page; a page may be split into several Passages. |
| **Evidence** | A verbatim quote from a Report, the page it is on and the boxes of the Passage it is from. | The model cites the Passage by id; the quote must appear literally in that Passage. It is never edited, shortened or reworded. |
| **Facts** | What is extracted from a Report: the **FTE** figure and the **Sustainability Goals**, each backed by Evidence. | FTE means full-time equivalent, not headcount. If both are given, use the FTE. A Sustainability Goal is a concrete target (metric, deadline, baseline), not a mission statement. A Fact citing a Passage the model wasn't shown goes back to the model to fix; a Fact whose quote isn't in its Passage is dropped. |
| **Question** | What the user asks in the chat, searched in the reports of its **Scope**: a Company and a Reporting Year, each of which may be "any". | A Company or year named in the Question wins over the selects. |
| **Answer** | The reply to a Question: plain text backed by at least one Evidence, or **Not Found** with a reason. | Not Found is a valid answer, never an error. Its quotes come from the API's citations; an answer citing nothing is Not Found. |
| **Conversation** | The Questions and Answers of one chat, in order. | Stored, so it survives a restart. "New chat" starts another. |
