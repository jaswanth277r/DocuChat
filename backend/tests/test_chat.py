from __future__ import annotations

import asyncio

from app import db
from app.generation.answer import extractive_answer
from app.generation.chat import run_turn
from app.retrieval.index import search


def _collect_turn(session, owner, question):
    async def collect():
        events = []
        async for event, data in run_turn(session, owner, question):
            events.append((event, data))
        return events

    return asyncio.run(collect())


def test_chat_turn_persists_citations(corpus, owner):
    session = {
        "_id": db.sessions().insert_one(
            {
                "user_id": db.oid(owner.id),
                "document_ids": [corpus["notes"]["_id"]],
                "title": "Test chat",
                "title_generated": False,
                "created_at": db.utcnow(),
                "updated_at": db.utcnow(),
            }
        ).inserted_id,
        "document_ids": [corpus["notes"]["_id"]],
        "title": "Test chat",
        "title_generated": False,
    }
    events = _collect_turn(session, owner, "What does Section 4.2 say about the scaling factor?")
    names = [event for event, _ in events]
    assert "retrieval" in names
    assert "delta" in names
    assert "citations" in names
    assert "done" in names
    assert names[-1] == "done"

    assistant = db.messages().find_one({"session_id": session["_id"], "role": "assistant"})
    assert assistant["status"] in {"complete", "abstained"}
    assert assistant["content"]
    assert assistant["citations"], "expected stored citations"
    assert all(citation["status"] != "invalid" for citation in assistant["citations"])
    assert assistant["citations"][0]["page_number"] == 2


def test_unanswerable_chat_abstains(corpus, owner):
    session = {
        "_id": db.sessions().insert_one(
            {
                "user_id": db.oid(owner.id),
                "document_ids": [corpus["notes"]["_id"]],
                "title": "Abstain chat",
                "title_generated": True,
                "created_at": db.utcnow(),
                "updated_at": db.utcnow(),
            }
        ).inserted_id,
        "document_ids": [corpus["notes"]["_id"]],
        "title": "Abstain chat",
        "title_generated": True,
    }
    events = _collect_turn(session, owner, "What is the tuition fee for the course?")
    done = events[-1][1]
    assert done["abstained"] is True
    assistant = db.messages().find_one({"session_id": session["_id"], "role": "assistant"})
    assert assistant["abstained"] is True
    assert assistant["citations"] == []


def test_extractive_answer_has_markers(corpus, owner):
    retrieval = search(
        "What dropout probability is applied, and what limitation do the authors note about long sequences?",
        [str(corpus["notes"]["_id"])],
        owner.id,
    )
    answer, abstained = extractive_answer(retrieval["query"], retrieval)
    assert abstained is False
    assert "[S" in answer
    assert "0.1" in answer
