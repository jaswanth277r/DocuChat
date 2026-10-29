from __future__ import annotations

import json
import logging
import random
import re

from .. import db
from ..retrieval.index import search
from ..security import CurrentUser
from .prompts import build_flashcard_messages, build_quiz_messages, build_study_guide_messages
from .providers import LLMProvider, ProviderError, get_provider

log = logging.getLogger("docuchat.study")

DEFINITION_RE = re.compile(
    r"^(?P<term>[A-Z][A-Za-z0-9\- ]{2,60}?)\s+(?:is|are|refers to|means|describes|denotes)\s+"
    r"(?P<definition>[A-Za-z][^.!?]{20,400}[.!?])",
    re.MULTILINE,
)
BOILERPLATE = ("figure ", "table ", "references", "copyright", "all rights reserved", "http")


def _clean_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output")
    return json.loads(text[start : end + 1])


def _study_passages(document: dict, user: CurrentUser, focus: str | None, limit: int = 8) -> list[dict]:
    if focus:
        query = f"{focus} definitions key concepts"
    else:
        query = "summarize overview key concepts definitions"
    result = search(query, [str(document["_id"])], user.id, rerank_top_n=limit)
    return result.get("selected") or []


def _label_map(passages: list[dict]) -> dict[str, dict]:
    return {f"S{index}": passage for index, passage in enumerate(passages, start=1)}


def _citation_fields(label: str | None, mapping: dict[str, dict]) -> dict:
    passage = mapping.get((label or "").strip())
    if not passage:
        return {"citation": label or None, "page_number": None, "section_path": None, "excerpt": None}
    return {
        "citation": label,
        "page_number": passage.get("page_number"),
        "section_path": passage.get("section_path"),
        "excerpt": " ".join((passage.get("text") or "").split())[:260],
    }


def _definition_pairs(passages: list[dict]) -> list[dict]:
    pairs = []
    seen = set()
    corpus = " ".join((passage.get("text") or "") for passage in passages).lower()
    for index, passage in enumerate(passages, start=1):
        for match in DEFINITION_RE.finditer(passage.get("text") or ""):
            term = " ".join(match.group("term").split())
            definition = " ".join(match.group("definition").split())
            key = term.lower()
            if key in seen or len(definition) < 25:
                continue
            occurrences = len(re.findall(rf"\b{re.escape(key)}\b", corpus))
            if occurrences < 3 and " " not in term:
                continue
            seen.add(key)
            pairs.append(
                {
                    "term": term,
                    "definition": definition,
                    "citation": f"S{index}",
                    "page_number": passage.get("page_number"),
                    "section_path": passage.get("section_path"),
                    "excerpt": definition[:240],
                }
            )
    return pairs


def _informative_sentence(passage: dict) -> str | None:
    if passage.get("chunk_kind") == "table" or passage.get("extraction_method") == "table":
        return None
    for sentence in re.split(r"(?<=[.!?])\s+", passage.get("text") or ""):
        text = " ".join(sentence.split())
        if "|" in text:
            continue
        if 50 <= len(text) <= 320 and not text.lower().startswith(BOILERPLATE):
            return text
    return None


def deterministic_guide(document: dict, passages: list[dict]) -> dict:
    mapping = _label_map(passages)
    outline = [item for item in document.get("outline") or [] if item.get("text")][:6]
    sections = []
    for heading in outline:
        needle = heading["text"].lower()[:40]
        matches = [
            (f"S{index}", passage)
            for index, passage in enumerate(passages, start=1)
            if needle in (passage.get("section_path") or "").lower()
        ] or list(enumerate(passages, start=1))[:1]
        points = []
        for label, passage in matches[:1]:
            sentence = _informative_sentence(passage)
            if sentence:
                points.append({"text": sentence, "citation": label, "page_number": passage.get("page_number")})
        if points:
            sections.append({"heading": heading["text"], "points": points})
    if not sections:
        for index, passage in enumerate(passages[:5], start=1):
            sentence = _informative_sentence(passage)
            if not sentence:
                continue
            sections.append(
                {
                    "heading": passage.get("section_path") or f"Page {passage.get('page_number')}",
                    "points": [{"text": sentence, "citation": f"S{index}", "page_number": passage.get("page_number")}],
                }
            )

    key_terms = _definition_pairs(passages)[:8]
    return {
        "title": f"Study guide: {document.get('title') or 'Document'}",
        "sections": sections[:6],
        "key_terms": [
            {"term": item["term"], "definition": item["definition"], "citation": item["citation"], "page_number": item["page_number"]}
            for item in key_terms
        ],
        "generated_by": "deterministic-extractive",
        "passages": len(passages),
    }


def _validate_guide(payload: dict, mapping: dict[str, dict]) -> dict:
    sections = []
    for section in payload.get("sections") or []:
        points = []
        for point in section.get("points") or []:
            text = str(point.get("text") or "").strip()
            if not text:
                continue
            points.append({"text": text, **_citation_fields(point.get("citation"), mapping)})
        heading = str(section.get("heading") or "").strip()
        if heading and points:
            sections.append({"heading": heading, "points": points[:5]})
    terms = []
    for term in payload.get("key_terms") or []:
        name = str(term.get("term") or "").strip()
        definition = str(term.get("definition") or "").strip()
        if name and definition:
            terms.append({"term": name, "definition": definition, **_citation_fields(term.get("citation"), mapping)})
    if not sections and not terms:
        raise ValueError("Model returned no usable study guide content")
    return {
        "title": str(payload.get("title") or "Study guide")[:200],
        "sections": sections[:8],
        "key_terms": terms[:12],
        "generated_by": "llm",
        "passages": len(mapping),
    }


def deterministic_flashcards(passages: list[dict], count: int) -> list[dict]:
    cards = []
    seen = set()
    for index, passage in enumerate(passages, start=1):
        for match in DEFINITION_RE.finditer(passage.get("text") or ""):
            term = " ".join(match.group("term").split())
            definition = " ".join(match.group("definition").split())
            if term.lower() in seen or len(definition) < 25:
                continue
            seen.add(term.lower())
            cards.append(
                {
                    "front": f"What is {term}?",
                    "back": definition,
                    "citation": f"S{index}",
                    "page_number": passage.get("page_number"),
                    "section_path": passage.get("section_path"),
                    "difficulty": "medium",
                }
            )
            if len(cards) >= count:
                return cards

    for index, passage in enumerate(passages, start=1):
        sentence = _informative_sentence(passage)
        if not sentence:
            continue
        front = f"Key point from {passage.get('section_path') or 'page ' + str(passage.get('page_number'))}"
        if front.lower() in seen:
            continue
        seen.add(front.lower())
        cards.append(
            {
                "front": front,
                "back": sentence,
                "citation": f"S{index}",
                "page_number": passage.get("page_number"),
                "section_path": passage.get("section_path"),
                "difficulty": "easy",
            }
        )
        if len(cards) >= count:
            break
    return cards[:count]


def _validate_cards(payload: list, mapping: dict[str, dict], count: int) -> list[dict]:
    cards = []
    seen = set()
    for item in payload:
        front = str(item.get("front") or "").strip()
        back = str(item.get("back") or "").strip()
        if not front or not back or front.lower() in seen:
            continue
        seen.add(front.lower())
        difficulty = str(item.get("difficulty") or "medium").lower()
        cards.append(
            {
                "front": front[:300],
                "back": back[:1200],
                "difficulty": difficulty if difficulty in {"easy", "medium", "hard"} else "medium",
                **_citation_fields(item.get("citation"), mapping),
            }
        )
        if len(cards) >= count:
            break
    if not cards:
        raise ValueError("Model returned no usable flashcards")
    return cards


NUMBER_RE = re.compile(r"\b(\d+(?:\.\d+)?)\b")


def _perturb_numbers(sentence: str) -> str | None:
    matches = list(NUMBER_RE.finditer(sentence))
    if not matches:
        return None
    match = matches[0]
    raw = match.group(1)
    try:
        value = float(raw)
    except ValueError:
        return None
    replacement = value + 1 if value >= 10 else round(value + 0.1, 2)
    formatted = str(int(replacement)) if replacement.is_integer() else f"{replacement:g}"
    return sentence[: match.start(1)] + formatted + sentence[match.end(1) :]


def deterministic_quiz(passages: list[dict], count: int) -> list[dict]:
    pairs = _definition_pairs(passages)
    questions: list[dict] = []

    if len(pairs) >= 2:
        for position, pair in enumerate(pairs):
            distractors = [other["definition"] for other in pairs if other["term"] != pair["term"]][:3]
            if len(distractors) < 3:
                break
            options = [pair["definition"]] + distractors
            random.Random(position).shuffle(options)
            questions.append(
                {
                    "type": "mcq",
                    "prompt": f"Which statement best describes {pair['term']}?",
                    "options": options,
                    "answer": pair["definition"],
                    "explanation": pair["definition"],
                    "citation": pair["citation"],
                    "page_number": pair["page_number"],
                }
            )
            if len(questions) >= count:
                return questions[:count]

    numeric: list[dict] = []
    for index, passage in enumerate(passages, start=1):
        if passage.get("chunk_kind") == "table":
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", passage.get("text") or ""):
            sentence = " ".join(sentence.split())
            if not (45 <= len(sentence) <= 260) or "|" in sentence:
                continue
            altered = _perturb_numbers(sentence)
            if not altered:
                continue
            numeric.append(
                {
                    "sentence": sentence,
                    "altered": altered,
                    "citation": f"S{index}",
                    "page_number": passage.get("page_number"),
                }
            )
            break

    for position, item in enumerate(numeric):
        if len(questions) >= count:
            break
        options = [item["sentence"], item["altered"]]
        other_alters = [other["altered"] for other in numeric if other["sentence"] != item["sentence"]]
        options.extend(other_alters[:2])
        while len(options) < 4:
            options.append("The document does not provide this value.")
        random.Random(100 + position).shuffle(options)
        questions.append(
            {
                "type": "mcq",
                "prompt": "Which statement is supported by the document?",
                "options": options,
                "answer": item["sentence"],
                "explanation": f"The cited page states: {item['sentence']}",
                "citation": item["citation"],
                "page_number": item["page_number"],
            }
        )

    for position, item in enumerate(numeric):
        if len(questions) >= count:
            break
        questions.append(
            {
                "type": "true_false",
                "prompt": f"True or false, according to page {item['page_number']}: {item['altered']}",
                "options": ["True", "False"],
                "answer": "False",
                "explanation": f"The document states: {item['sentence']}",
                "citation": item["citation"],
                "page_number": item["page_number"],
            }
        )

    for index, passage in enumerate(passages, start=1):
        if len(questions) >= count:
            break
        sentence = _informative_sentence(passage)
        if not sentence:
            continue
        questions.append(
            {
                "type": "short_answer",
                "prompt": f"What does the document state about {passage.get('section_path') or 'this page'}?",
                "options": [],
                "answer": sentence,
                "explanation": "Compare your answer with the cited passage.",
                "citation": f"S{index}",
                "page_number": passage.get("page_number"),
            }
        )
    return questions[:count]


def _validate_questions(payload: list, mapping: dict[str, dict], count: int) -> list[dict]:
    questions = []
    for item in payload:
        kind = str(item.get("type") or "mcq").lower()
        if kind not in {"mcq", "true_false", "short_answer"}:
            kind = "mcq"
        prompt = str(item.get("prompt") or "").strip()
        answer = str(item.get("answer") or "").strip()
        options = [str(option).strip() for option in (item.get("options") or [])]
        if not prompt or not answer:
            continue
        if kind == "mcq" and len(options) < 2:
            continue
        if kind == "true_false":
            options = ["True", "False"]
        questions.append(
            {
                "type": kind,
                "prompt": prompt[:600],
                "options": options[:6],
                "answer": answer[:600],
                "explanation": str(item.get("explanation") or "")[:800],
                **_citation_fields(item.get("citation"), mapping),
            }
        )
        if len(questions) >= count:
            break
    if not questions:
        raise ValueError("Model returned no usable quiz questions")
    return questions


async def generate_guide(document: dict, user: CurrentUser, focus: str | None) -> dict:
    passages = _study_passages(document, user, focus)
    if not passages:
        raise ValueError("No indexed content was found for this document")
    provider: LLMProvider | None = get_provider()
    if provider is not None:
        try:
            raw = await provider.complete(build_study_guide_messages(passages, focus), max_tokens=1600)
            guide = _validate_guide(_clean_json(raw), _label_map(passages))
        except (ProviderError, ValueError, json.JSONDecodeError) as exc:
            log.warning("LLM study guide failed (%s); using deterministic guide", exc)
            guide = deterministic_guide(document, passages)
            guide["generation_note"] = f"Model generation failed: {exc}"
    else:
        guide = deterministic_guide(document, passages)
    guide.update(
        {
            "document_id": str(document["_id"]),
            "user_id": db.oid(user.id),
            "focus": focus,
            "created_at": db.utcnow(),
        }
    )
    db.study_guides().insert_one(guide)
    out = db.serialize(guide) or {}
    out.pop("user_id", None)
    return out


async def generate_flashcards(document: dict, user: CurrentUser, focus: str | None, count: int) -> list[dict]:
    passages = _study_passages(document, user, focus)
    if not passages:
        raise ValueError("No indexed content was found for this document")
    mapping = _label_map(passages)
    provider = get_provider()
    cards = None
    note = None
    if provider is not None:
        try:
            raw = await provider.complete(build_flashcard_messages(passages, count, focus), max_tokens=1800)
            payload = _clean_json(raw)
            cards = _validate_cards(payload.get("flashcards") or payload.get("cards") or [], mapping, count)
        except (ProviderError, ValueError, json.JSONDecodeError) as exc:
            log.warning("LLM flashcards failed (%s); using deterministic cards", exc)
            note = str(exc)
    if cards is None:
        cards = deterministic_flashcards(passages, count)

    db.flashcards().delete_many({"document_id": document["_id"], "user_id": db.oid(user.id)})
    rows = []
    for card in cards:
        rows.append(
            {
                "document_id": document["_id"],
                "user_id": db.oid(user.id),
                "front": card["front"],
                "back": card["back"],
                "citation": card.get("citation"),
                "page_number": card.get("page_number"),
                "section_path": card.get("section_path"),
                "excerpt": card.get("excerpt"),
                "difficulty": card.get("difficulty", "medium"),
                "status": "new",
                "generated_by": "llm" if provider is not None and note is None else "deterministic-extractive",
                "created_at": db.utcnow(),
            }
        )
    if rows:
        db.flashcards().insert_many(rows)
    stored = list(db.flashcards().find({"document_id": document["_id"], "user_id": db.oid(user.id)}).sort("created_at", 1))
    result = [db.serialize(row) for row in stored]
    if note:
        for row in result:
            row["generation_note"] = note
    return result


async def generate_quiz(document: dict, user: CurrentUser, count: int, difficulty: str) -> dict:
    passages = _study_passages(document, user, None)
    if not passages:
        raise ValueError("No indexed content was found for this document")
    mapping = _label_map(passages)
    provider = get_provider()
    questions = None
    note = None
    generated_by = "deterministic-extractive"
    if provider is not None:
        try:
            raw = await provider.complete(build_quiz_messages(passages, count, difficulty), max_tokens=2200)
            payload = _clean_json(raw)
            questions = _validate_questions(payload.get("questions") or [], mapping, count)
            generated_by = "llm"
        except (ProviderError, ValueError, json.JSONDecodeError) as exc:
            log.warning("LLM quiz failed (%s); using deterministic quiz", exc)
            note = str(exc)
    if questions is None:
        questions = deterministic_quiz(passages, count)

    quiz = {
        "document_id": document["_id"],
        "user_id": db.oid(user.id),
        "title": f"{difficulty.title()} quiz: {document.get('title')}",
        "difficulty": difficulty,
        "questions": questions,
        "generated_by": generated_by,
        "generation_note": note,
        "created_at": db.utcnow(),
    }
    quiz_id = db.quizzes().insert_one(quiz).inserted_id
    quiz["_id"] = quiz_id
    out = db.serialize(quiz) or {}
    out.pop("user_id", None)
    return out


def grade_quiz(quiz: dict, answers: list[str]) -> dict:
    results = []
    correct = 0
    for index, question in enumerate(quiz.get("questions") or []):
        given = (answers[index] if index < len(answers) else "").strip()
        expected = str(question.get("answer") or "").strip()
        kind = question.get("type")
        if kind in {"mcq", "true_false"}:
            is_correct = given.strip().lower() == expected.strip().lower()
            feedback = "Correct." if is_correct else f"The correct answer is: {expected}"
        else:
            expected_terms = {word for word in re.findall(r"[a-z]{4,}", expected.lower())}
            given_terms = {word for word in re.findall(r"[a-z]{4,}", given.lower())}
            overlap = len(expected_terms & given_terms) / max(len(expected_terms), 1)
            is_correct = overlap >= 0.45
            if is_correct:
                feedback = "Your answer covers the key points of the rubric."
            elif overlap >= 0.2:
                feedback = "Partially correct. The expected answer includes: " + expected
                is_correct = False
            else:
                feedback = "Review this concept. The expected answer is: " + expected
        if is_correct:
            correct += 1
        results.append(
            {
                "index": index,
                "prompt": question.get("prompt"),
                "given": given,
                "expected": expected,
                "correct": is_correct,
                "feedback": feedback,
                "citation": question.get("citation"),
                "page_number": question.get("page_number"),
                "source_excerpt": question.get("excerpt"),
            }
        )
    total = len(results)
    return {
        "score": round(correct / total, 3) if total else 0.0,
        "correct": correct,
        "total": total,
        "results": results,
        "graded_by": "deterministic",
    }
