from __future__ import annotations

from pathlib import Path

import fitz

OUT_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "fixtures"
PAGE_W, PAGE_H = 595, 842
MARGIN = 56


def _new_page(doc: fitz.Document, title: str, heading: str | None = None) -> tuple[fitz.Page, float]:
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_textbox(
        fitz.Rect(MARGIN, 54, PAGE_W - MARGIN, 108),
        title,
        fontsize=19,
        fontname="hebo",
        color=(0.06, 0.06, 0.12),
    )
    page.insert_text((MARGIN, 118), "DocuChat evaluation fixture", fontsize=8, fontname="helv", color=(0.45, 0.45, 0.5))
    y = 146.0
    if heading:
        page.insert_textbox(
            fitz.Rect(MARGIN, y, PAGE_W - MARGIN, y + 34),
            heading,
            fontsize=14,
            fontname="hebo",
            color=(0.12, 0.1, 0.3),
        )
        y += 44
    return page, y


def _paragraphs(page: fitz.Page, paragraphs: list[str], y: float, size: float = 11) -> float:
    for text in paragraphs:
        height = 26 + 15 * (len(text) // 92)
        page.insert_textbox(
            fitz.Rect(MARGIN, y, PAGE_W - MARGIN, y + height),
            text,
            fontsize=size,
            fontname="helv",
            lineheight=1.45,
            color=(0.12, 0.12, 0.14),
        )
        y += height
    return y


def _table(page: fitz.Page, y: float, header: list[str], rows: list[list[str]]) -> float:
    col_width = (PAGE_W - 2 * MARGIN) / len(header)
    row_height = 27
    all_rows = [header] + rows
    for row_index, row in enumerate(all_rows):
        top = y + row_index * row_height
        for col_index, value in enumerate(row):
            rect = fitz.Rect(MARGIN + col_index * col_width, top, MARGIN + (col_index + 1) * col_width, top + row_height)
            page.draw_rect(rect, color=(0.55, 0.55, 0.62), width=0.7)
            page.insert_textbox(
                rect + (5, 6, -5, 0),
                value,
                fontsize=9.5,
                fontname="hebo" if row_index == 0 else "helv",
                color=(0.1, 0.1, 0.14),
            )
    return y + len(all_rows) * row_height + 18


def build_transformer_notes(path: Path) -> None:
    doc = fitz.open()
    title = "Transformer Architectures: Lecture Notes"

    page, y = _new_page(doc, title, "Lecture 1: Attention Foundations")
    _paragraphs(
        page,
        [
            "Attention is a mechanism that weights input tokens by their relevance to the current query. "
            "It lets a model focus on the parts of an input that matter for a prediction.",
            "Self-attention allows each position in a sequence to attend to every other position in the same "
            "sequence. This differs from recurrent models, which process tokens one step at a time.",
            "A multi-head attention layer runs several attention heads in parallel and concatenates their outputs. "
            "Each head learns a different projection of the input.",
            "The course notes report that dense retrieval alone achieves Recall@10 of 0.938 on the course benchmark.",
        ],
        y,
    )

    page, y = _new_page(doc, title, "Section 4.2 Scaling Factors")
    _paragraphs(
        page,
        [
            "Section 4.2 states that the scaling factor 1/sqrt(d_k) keeps dot-product logits in a stable range. "
            "Without scaling, large dot products push the softmax into regions with very small gradients.",
            "The model dimension d_model is 512 in the original configuration. The feed-forward network uses an "
            "inner dimension of 2048.",
            "The original model uses 8 attention heads. Each head therefore operates on a projected dimension of 64.",
        ],
        y,
    )

    page, y = _new_page(doc, title, "Training and Regularization")
    y = _paragraphs(
        page,
        [
            "Dropout with probability 0.1 is applied to each sub-layer output during training. Dropout is disabled "
            "during inference.",
            "Label smoothing of 0.1 improves BLEU scores in the reported experiments. The authors attribute part of "
            "the gain to reduced overconfidence.",
            "Table 1: Reported BLEU scores on the translation benchmark.",
        ],
        y,
    )
    y = _table(page, y, ["Model", "BLEU", "Notes"], [["Baseline", "25.8", "Reimplementation"], ["Transformer", "28.4", "Base model"], ["Transformer (big)", "29.3", "Larger model"]])
    _paragraphs(
        page,
        [
            "Scores are measured on the same test set. The larger model was trained for more steps, which is a "
            "confounding factor when comparing architectures.",
        ],
        y,
    )

    page, y = _new_page(doc, title, "Limitations")
    _paragraphs(
        page,
        [
            "The authors note that attention over long sequences has quadratic computational cost. Memory grows "
            "quickly as the context length increases.",
            "The paper does not evaluate on low-resource languages. The results therefore may not transfer to "
            "settings with limited parallel data.",
            "Future work should examine efficient attention variants and domain adaptation for smaller datasets.",
        ],
        y,
    )

    doc.save(path)
    doc.close()


def build_retrieval_report(path: Path) -> None:
    doc = fitz.open()
    title = "Retrieval Evaluation Report - Fall 2025"

    page, y = _new_page(doc, title, "Executive Summary")
    _paragraphs(
        page,
        [
            "Hybrid retrieval raised Recall@10 from 0.938 to 0.969 on the internal benchmark. The benchmark "
            "contains 1,200 questions over 400 technical documents.",
            "Reranking improved MRR from 0.833 to 0.914 at a cost of about 119 ms per query. The team judged the "
            "latency trade-off acceptable for the pilot deployment.",
            "The report recommends enabling hybrid retrieval and reranking for all production collections.",
        ],
        y,
    )

    page, y = _new_page(doc, title, "Section 2.1 Fusion Configuration")
    _paragraphs(
        page,
        [
            "Reciprocal Rank Fusion with k equal to 60 merges dense and BM25 rankings without score normalization. "
            "This avoids assuming that vector similarity and keyword scores are directly comparable.",
            "Vector weight is set to 0.7 and BM25 weight to 0.3. These weights performed best on conceptual "
            "questions, while exact section-number queries relied more heavily on BM25.",
            "The reranker is applied to the top 20 candidates, and the five highest-scoring passages are passed to "
            "the generator.",
        ],
        y,
    )

    page, y = _new_page(doc, title, "Open Issues")
    _paragraphs(
        page,
        [
            "The evaluation set contains no scanned PDFs, so OCR behaviour is untested. The team plans to add "
            "scanned documents in the next evaluation cycle.",
            "For comparison, the course benchmark reported a Recall@10 of 0.921 for dense retrieval. The difference "
            "from the internal benchmark is attributed to a different document mix.",
            "Citation support verification is currently manual. Automated claim-level verification remains future "
            "work.",
        ],
        y,
    )

    doc.save(path)
    doc.close()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build_transformer_notes(OUT_DIR / "transformer_notes.pdf")
    build_retrieval_report(OUT_DIR / "retrieval_report.pdf")
    print(f"wrote fixtures to {OUT_DIR}")


if __name__ == "__main__":
    main()
