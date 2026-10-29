import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, titleCase } from "../lib/api";
import { useToast } from "../lib/toast";
import type { DocumentRecord, FlashcardT, Quiz, QuizResult, StudyGuide } from "../lib/types";
import { Icon } from "../components/Icon";
import { Badge, Button, EmptyState, Spinner } from "../components/ui";

type Tab = "guide" | "flashcards" | "quiz";

export function StudyPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [tab, setTab] = useState<Tab>("guide");
  const [guide, setGuide] = useState<StudyGuide | null>(null);
  const [cards, setCards] = useState<FlashcardT[]>([]);
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [quizList, setQuizList] = useState<Quiz[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [flipped, setFlipped] = useState<Set<string>>(new Set());
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [result, setResult] = useState<QuizResult | null>(null);
  const [difficulty, setDifficulty] = useState("intermediate");
  const [cardFilter, setCardFilter] = useState<"all" | "new" | "known" | "difficult">("all");

  const activeDocument = useMemo(
    () => documents.find((doc) => doc.id === documentId) || null,
    [documents, documentId],
  );

  const loadDocuments = useCallback(async () => {
    const data = await api<{ documents: DocumentRecord[] }>("/documents");
    const ready = data.documents.filter((doc) => doc.status === "ready");
    setDocuments(ready);
    return ready;
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const ready = await loadDocuments();
        if (!documentId && ready.length) {
          navigate(`/study/${ready[0].id}`, { replace: true });
          return;
        }
      } catch (error) {
        toast.push(error instanceof Error ? error.message : "Could not load documents", "error");
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadDocuments, documentId]);

  const loadStudy = useCallback(async () => {
    if (!documentId) return;
    setGuide(null);
    setCards([]);
    setQuiz(null);
    setResult(null);
    setQuizList([]);
    setAnswers({});
    try {
      const [guideResult, cardsResult, quizzesResult] = await Promise.allSettled([
        api<StudyGuide>(`/documents/${documentId}/study-guides`),
        api<{ flashcards: FlashcardT[] }>(`/documents/${documentId}/flashcards`),
        api<{ quizzes: Quiz[] }>(`/documents/${documentId}/quizzes`),
      ]);
      if (guideResult.status === "fulfilled") setGuide(guideResult.value);
      if (cardsResult.status === "fulfilled") setCards(cardsResult.value.flashcards);
      if (quizzesResult.status === "fulfilled") {
        setQuizList(quizzesResult.value.quizzes);
        const latest = quizzesResult.value.quizzes[0];
        if (latest) {
          const full = await api<Quiz>(`/quizzes/${latest.id}`);
          setQuiz(full);
        }
      }
    } catch {
      /* individual failures show as empty states */
    }
  }, [documentId]);

  useEffect(() => {
    void loadStudy();
  }, [loadStudy]);

  const generateGuide = async () => {
    if (!documentId) return;
    setBusy("guide");
    try {
      const data = await api<StudyGuide>(`/documents/${documentId}/study-guides`, {
        method: "POST",
        body: JSON.stringify({ count: 10 }),
      });
      setGuide(data);
      toast.push("Study guide generated", "success");
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not generate a study guide", "error");
    } finally {
      setBusy(null);
    }
  };

  const generateCards = async () => {
    if (!documentId) return;
    setBusy("cards");
    try {
      const data = await api<{ flashcards: FlashcardT[] }>(`/documents/${documentId}/flashcards`, {
        method: "POST",
        body: JSON.stringify({ count: 12 }),
      });
      setCards(data.flashcards);
      setFlipped(new Set());
      toast.push("Flashcards generated", "success");
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not generate flashcards", "error");
    } finally {
      setBusy(null);
    }
  };

  const generateQuiz = async () => {
    if (!documentId) return;
    setBusy("quiz");
    try {
      const data = await api<Quiz>(`/documents/${documentId}/quizzes`, {
        method: "POST",
        body: JSON.stringify({ count: 6, difficulty }),
      });
      setQuiz(data);
      setResult(null);
      setAnswers({});
      setQuizList((current) => [data, ...current]);
      toast.push("Quiz generated", "success");
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not generate a quiz", "error");
    } finally {
      setBusy(null);
    }
  };

  const setCardStatus = async (card: FlashcardT, status: "known" | "difficult" | "new") => {
    try {
      const updated = await api<FlashcardT>(`/flashcards/${card.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setCards((current) => current.map((item) => (item.id === card.id ? updated : item)));
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not update the card", "error");
    }
  };

  const deleteCard = async (card: FlashcardT) => {
    try {
      await api(`/flashcards/${card.id}`, { method: "DELETE" });
      setCards((current) => current.filter((item) => item.id !== card.id));
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not delete the card", "error");
    }
  };

  const submitQuiz = async () => {
    if (!quiz) return;
    setBusy("attempt");
    try {
      const ordered = quiz.questions.map((_, index) => answers[index] || "");
      const data = await api<QuizResult>(`/quizzes/${quiz.id}/attempts`, {
        method: "POST",
        body: JSON.stringify({ answers: ordered }),
      });
      setResult(data);
      toast.push(`Scored ${Math.round(data.score * 100)}%`, data.score >= 0.6 ? "success" : "info");
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not submit the quiz", "error");
    } finally {
      setBusy(null);
    }
  };

  const openPage = (page?: number | null) => {
    if (!documentId || !page) return;
    window.open(`/api/documents/${documentId}/file#page=${page}&view=FitH`, "_blank", "noopener");
  };

  const toggleFlip = (id: string) =>
    setFlipped((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const visibleCards = cards.filter((card) => (cardFilter === "all" ? true : card.status === cardFilter));
  const knownCount = cards.filter((card) => card.status === "known").length;
  const difficultCount = cards.filter((card) => card.status === "difficult").length;

  if (loading) {
    return (
      <div className="page" style={{ display: "grid", placeItems: "center" }}>
        <Spinner />
      </div>
    );
  }

  if (!documents.length) {
    return (
      <div className="page">
        <div className="page-narrow">
          <header className="page-header">
            <div>
              <h1 className="page-title">Study mode</h1>
              <p className="page-sub">Turn your PDFs into study guides, flashcards, and quizzes.</p>
            </div>
          </header>
          <EmptyState
            icon="study"
            title="No ready documents yet"
            description="Upload and process a PDF first, then return here to generate cited study material."
            action={
              <Link className="btn btn-primary" to="/library">
                Go to library
              </Link>
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-narrow">
        <header className="page-header">
          <div>
            <h1 className="page-title">Study mode</h1>
            <p className="page-sub">Every item links back to the page it came from.</p>
          </div>
          {activeDocument ? (
            <Badge tone="accent">
              <Icon name="file" size={12} /> {activeDocument.page_count || "—"} pages
            </Badge>
          ) : null}
        </header>

        <div className="study-layout">
          <aside className="study-side">
            <div className="sidebar-section-label" style={{ color: "#8b8592", padding: "4px 8px 8px" }}>
              Documents
            </div>
            <div className="study-doc-list">
              {documents.map((doc) => (
                <button
                  key={doc.id}
                  className={`study-doc-item ${doc.id === documentId ? "active" : ""}`}
                  onClick={() => navigate(`/study/${doc.id}`)}
                >
                  {doc.title}
                </button>
              ))}
            </div>
            <div className="divider" />
            <div style={{ display: "grid", gap: 8, padding: "0 6px 4px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#6d6675" }}>
                <span>Flashcards</span>
                <strong>{cards.length}</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#6d6675" }}>
                <span>Known</span>
                <strong style={{ color: "var(--color-success)" }}>{knownCount}</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#6d6675" }}>
                <span>Needs review</span>
                <strong style={{ color: "var(--color-warning)" }}>{difficultCount}</strong>
              </div>
            </div>
          </aside>

          <div>
            <div className="tabs" role="tablist">
              <button className={`tab ${tab === "guide" ? "active" : ""}`} onClick={() => setTab("guide")} role="tab" aria-selected={tab === "guide"}>
                Study guide
              </button>
              <button className={`tab ${tab === "flashcards" ? "active" : ""}`} onClick={() => setTab("flashcards")} role="tab" aria-selected={tab === "flashcards"}>
                Flashcards {cards.length ? `(${cards.length})` : ""}
              </button>
              <button className={`tab ${tab === "quiz" ? "active" : ""}`} onClick={() => setTab("quiz")} role="tab" aria-selected={tab === "quiz"}>
                Quiz {quizList.length ? `(${quizList.length})` : ""}
              </button>
            </div>

            {tab === "guide" ? (
              <div>
                <div style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "center" }}>
                  <Button variant={guide ? "secondary" : "primary"} icon="sparkle" onClick={() => void generateGuide()} loading={busy === "guide"}>
                    {guide ? "Regenerate guide" : "Generate study guide"}
                  </Button>
                  {guide?.generated_by ? (
                    <Badge tone="neutral" mono>
                      {guide.generated_by}
                    </Badge>
                  ) : null}
                </div>
                {!guide ? (
                  <EmptyState
                    icon="book"
                    title="No study guide yet"
                    description="Generate a cited overview of the key sections, concepts, and definitions in this document."
                    action={
                      <Button variant="primary" icon="sparkle" onClick={() => void generateGuide()} loading={busy === "guide"}>
                        Generate study guide
                      </Button>
                    }
                  />
                ) : (
                  <>
                    {guide.sections.map((section, index) => (
                      <section className="guide-section" key={index}>
                        <h3>{section.heading}</h3>
                        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.6 }}>
                          {section.points.map((point, pointIndex) => (
                            <li key={pointIndex} style={{ marginBottom: 6 }}>
                              {point.text}{" "}
                              {point.page_number ? (
                                <button
                                  className="cite-chip"
                                  onClick={() => openPage(point.page_number)}
                                  title={`Open page ${point.page_number}`}
                                >
                                  p.{point.page_number}
                                </button>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </section>
                    ))}
                    {guide.key_terms?.length ? (
                      <>
                        <h3 style={{ fontSize: 14, margin: "18px 0 10px" }}>Key terms</h3>
                        <div className="term-grid">
                          {guide.key_terms.map((term, index) => (
                            <div className="term-card" key={index}>
                              <div className="term-name">{term.term}</div>
                              <div className="term-def">{term.definition}</div>
                              {term.page_number ? (
                                <div style={{ marginTop: 8 }}>
                                  <button className="cite-chip" onClick={() => openPage(term.page_number)}>
                                    p.{term.page_number}
                                  </button>
                                </div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </>
                    ) : null}
                  </>
                )}
              </div>
            ) : null}

            {tab === "flashcards" ? (
              <div>
                <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
                  <Button variant={cards.length ? "secondary" : "primary"} icon="sparkle" onClick={() => void generateCards()} loading={busy === "cards"}>
                    {cards.length ? "Regenerate deck" : "Generate flashcards"}
                  </Button>
                  {cards.length ? (
                    <div className="filter-chips">
                      {(["all", "new", "known", "difficult"] as const).map((value) => (
                        <button key={value} className={`chip ${cardFilter === value ? "active" : ""}`} onClick={() => setCardFilter(value)}>
                          {titleCase(value)}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {cards.length ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      icon="refresh"
                      style={{ marginLeft: "auto" }}
                      onClick={() => setCards((current) => [...current].sort(() => Math.random() - 0.5))}
                    >
                      Shuffle
                    </Button>
                  ) : null}
                </div>

                {!cards.length ? (
                  <EmptyState
                    icon="study"
                    title="No flashcards yet"
                    description="Generate a deck of questions and answers taken directly from this document, with page references."
                    action={
                      <Button variant="primary" icon="sparkle" onClick={() => void generateCards()} loading={busy === "cards"}>
                        Generate flashcards
                      </Button>
                    }
                  />
                ) : (
                  <div className="card-grid">
                    {visibleCards.map((card) => {
                      const isFlipped = flipped.has(card.id);
                      return (
                        <div
                          key={card.id}
                          className={`flashcard ${isFlipped ? "flipped" : ""}`}
                          onClick={() => toggleFlip(card.id)}
                        >
                          <div className="flashcard-inner">
                            <div className="flashcard-face">
                              <div style={{ display: "flex", justifyContent: "space-between" }}>
                                <span className="flashcard-label">Question</span>
                                <Badge tone={card.difficulty === "hard" ? "danger" : card.difficulty === "easy" ? "success" : "neutral"}>
                                  {card.difficulty || "medium"}
                                </Badge>
                              </div>
                              <div className="flashcard-text">{card.front}</div>
                              <div className="flashcard-foot">
                                {card.page_number ? (
                                  <button
                                    className="cite-chip"
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      openPage(card.page_number);
                                    }}
                                  >
                                    p.{card.page_number}
                                  </button>
                                ) : null}
                                <button
                                  className="icon-btn"
                                  style={{ marginLeft: "auto" }}
                                  aria-label="Flip card"
                                  title="Flip card"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    toggleFlip(card.id);
                                  }}
                                >
                                  <Icon name="refresh" size={13} />
                                </button>
                              </div>
                            </div>
                            <div className="flashcard-face flashcard-back">
                              <span className="flashcard-label">Answer</span>
                              <div className="flashcard-text">{card.back}</div>
                              <div className="flashcard-foot">
                                <button
                                  className="btn btn-sm btn-secondary"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void setCardStatus(card, card.status === "known" ? "new" : "known");
                                  }}
                                >
                                  <Icon name="check" size={12} /> {card.status === "known" ? "Known" : "Mark known"}
                                </button>
                                <button
                                  className="btn btn-sm btn-ghost"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void setCardStatus(card, card.status === "difficult" ? "new" : "difficult");
                                  }}
                                >
                                  <Icon name="alert" size={12} /> Review
                                </button>
                                <button
                                  className="icon-btn"
                                  style={{ marginLeft: "auto" }}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    toggleFlip(card.id);
                                  }}
                                  aria-label="Flip card back"
                                  title="Flip card back"
                                >
                                  <Icon name="refresh" size={13} />
                                </button>
                                <button
                                  className="icon-btn"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void deleteCard(card);
                                  }}
                                  aria-label="Delete flashcard"
                                >
                                  <Icon name="trash" size={14} />
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : null}

            {tab === "quiz" ? (
              <div>
                <div style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
                  <Button variant={quiz ? "secondary" : "primary"} icon="sparkle" onClick={() => void generateQuiz()} loading={busy === "quiz"}>
                    {quiz ? "New quiz" : "Generate quiz"}
                  </Button>
                  <select className="select" style={{ width: 160 }} value={difficulty} onChange={(event) => setDifficulty(event.target.value)} aria-label="Quiz difficulty">
                    <option value="beginner">Beginner</option>
                    <option value="intermediate">Intermediate</option>
                    <option value="advanced">Advanced</option>
                    <option value="exam">Exam prep</option>
                  </select>
                  {quiz?.generated_by ? (
                    <Badge tone="neutral" mono>
                      {quiz.generated_by}
                    </Badge>
                  ) : null}
                  {quizList.length > 1 ? (
                    <select
                      className="select"
                      style={{ width: 190, marginLeft: "auto" }}
                      value={quiz?.id || ""}
                      onChange={async (event) => {
                        const full = await api<Quiz>(`/quizzes/${event.target.value}`);
                        setQuiz(full);
                        setResult(null);
                        setAnswers({});
                      }}
                      aria-label="Choose a quiz"
                    >
                      {quizList.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.title}
                        </option>
                      ))}
                    </select>
                  ) : null}
                </div>

                {!quiz ? (
                  <EmptyState
                    icon="flask"
                    title="No quiz yet"
                    description="Create a quiz with multiple-choice, true/false, and short-answer questions grounded in this document."
                    action={
                      <Button variant="primary" icon="sparkle" onClick={() => void generateQuiz()} loading={busy === "quiz"}>
                        Generate quiz
                      </Button>
                    }
                  />
                ) : (
                  <div>
                    {result ? (
                      <div className="score-banner">
                        <div className="score-ring" style={{ ["--score" as string]: Math.round(result.score * 100) }}>
                          {Math.round(result.score * 100)}%
                        </div>
                        <div>
                          <div style={{ fontWeight: 650, fontSize: 15 }}>
                            {result.correct} of {result.total} correct
                          </div>
                          <div style={{ color: "var(--color-muted)", fontSize: 12.5 }}>
                            Review the feedback below, then reopen the cited pages for the full context.
                          </div>
                        </div>
                        <Button
                          variant="secondary"
                          size="sm"
                          style={{ marginLeft: "auto" }}
                          onClick={() => {
                            setResult(null);
                            setAnswers({});
                          }}
                        >
                          Try again
                        </Button>
                      </div>
                    ) : null}

                    {quiz.questions.map((question, index) => {
                      const feedback = result?.results.find((item) => item.index === index);
                      return (
                        <div className="quiz-q" key={index}>
                          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginBottom: 8 }}>
                            <div style={{ fontWeight: 560, fontSize: 13.5, lineHeight: 1.5 }}>
                              {index + 1}. {question.prompt}
                            </div>
                            <div style={{ display: "flex", gap: 5, flexShrink: 0 }}>
                              <Badge tone="neutral" mono>
                                {question.type.replace("_", " ")}
                              </Badge>
                              {question.page_number ? (
                                <button className="cite-chip" onClick={() => openPage(question.page_number)}>
                                  p.{question.page_number}
                                </button>
                              ) : null}
                            </div>
                          </div>

                          {question.type === "short_answer" ? (
                            <textarea
                              className="textarea"
                              rows={2}
                              placeholder="Write a short answer…"
                              value={answers[index] || ""}
                              disabled={Boolean(result)}
                              onChange={(event) => setAnswers((current) => ({ ...current, [index]: event.target.value }))}
                            />
                          ) : (
                            (question.options || []).map((option) => {
                              const selected = answers[index] === option;
                              const isCorrect = feedback && option === feedback.expected;
                              const isWrong = feedback && selected && !feedback.correct;
                              return (
                                <label
                                  key={option}
                                  className={`quiz-option ${selected ? "selected" : ""} ${isCorrect ? "correct" : ""} ${isWrong ? "incorrect" : ""}`}
                                >
                                  <input
                                    type="radio"
                                    name={`q-${quiz.id}-${index}`}
                                    checked={selected}
                                    disabled={Boolean(result)}
                                    onChange={() => setAnswers((current) => ({ ...current, [index]: option }))}
                                    style={{ marginTop: 3, accentColor: "var(--color-accent)" }}
                                  />
                                  <span>{option}</span>
                                </label>
                              );
                            })
                          )}

                          {feedback ? (
                            <div
                              style={{
                                marginTop: 10,
                                padding: "9px 11px",
                                borderRadius: 8,
                                fontSize: 12.5,
                                background: feedback.correct ? "#effaf4" : "#fdf4f2",
                                border: `1px solid ${feedback.correct ? "#cfe9dd" : "#f4d8d2"}`,
                                color: feedback.correct ? "#14684a" : "#8f2f26",
                              }}
                            >
                              <div style={{ fontWeight: 600, marginBottom: 2 }}>{feedback.correct ? "Correct" : "Review this"}</div>
                              <div>{feedback.feedback}</div>
                              {question.explanation ? (
                                <div style={{ marginTop: 4, color: "#5d5764" }}>{question.explanation}</div>
                              ) : null}
                              {feedback.page_number ? (
                                <button className="cite-chip" style={{ marginTop: 6 }} onClick={() => openPage(feedback.page_number)}>
                                  Open page {feedback.page_number}
                                </button>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      );
                    })}

                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <Button variant="primary" onClick={() => void submitQuiz()} loading={busy === "attempt"} disabled={Boolean(result)}>
                        Submit answers
                      </Button>
                      <span className="hint">Grading is deterministic for multiple-choice and true/false questions.</span>
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
