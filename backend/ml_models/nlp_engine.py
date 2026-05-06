"""
NLP Engine — Groq-powered + OpenRouter Vision OCR
────────────────────────────────────────────────────
- PDF text extraction (PyMuPDF → pdfplumber → OpenRouter Vision OCR)
- Summarization     → Groq llama-3.1-8b-instant
- Question Answering → Groq llama-3.1-8b-instant
- Key topic extraction → YAKE
- Translation        → Groq / googletrans
"""

import os
import re
import logging
import requests
import base64
from collections import Counter

logger = logging.getLogger(__name__)

# ── API endpoints ──────────────────────────────────────────────
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ── WORKING FREE OCR MODELS ───────────────────────────────────
OPENROUTER_VISION_MODELS = [
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "openrouter/auto"
]


# ── Headers ────────────────────────────────────────────────────
def _groq_headers():
    return {
        "Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '')}",
        "Content-Type": "application/json",
    }


def _openrouter_headers():
    return {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://learning-assistant-a7n9.onrender.com",
        "X-Title": "AI Learning Assistant",
    }


# ── Groq Chat ──────────────────────────────────────────────────
def _groq_chat(
    prompt: str,
    system: str = "You are a helpful AI assistant.",
    max_tokens: int = 1000,
):
    try:
        r = requests.post(
            GROQ_URL,
            headers=_groq_headers(),
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.4,
                "max_tokens": max_tokens,
            },
            timeout=60,
        )

        if r.ok:
            return r.json()["choices"][0]["message"]["content"].strip()

        logger.error(f"[Groq] Error: {r.status_code} {r.text}")
        return ""

    except Exception as e:
        logger.error(f"[Groq] Exception: {e}")
        return ""


# ── PDF TEXT EXTRACTION ────────────────────────────────────────
def extract_text_from_pdf(file_path: str) -> str:

    if not os.path.exists(file_path):
        logger.error(f"[PDF] File not found: {file_path}")
        return ""

    if os.path.getsize(file_path) == 0:
        logger.error("[PDF] File is empty")
        return ""

    logger.warning(f"[PDF] File size: {os.path.getsize(file_path)} bytes")

    # ── Stage 1: PyMuPDF ──────────────────────────────────────
    try:
        import fitz

        doc = fitz.open(file_path)

        text = ""
        total_pages = len(doc)

        for page in doc:
            text += page.get_text()

        doc.close()

        logger.warning(f"[PDF] PyMuPDF: {len(text)} chars from {total_pages} pages")

        if text and len(text.strip()) > 100:
            return _clean_text(text)

        logger.warning("[PDF] PyMuPDF returned empty — trying pdfplumber")

    except Exception as e:
        logger.error(f"[PDF] PyMuPDF failed: {e}")

    # ── Stage 2: pdfplumber ───────────────────────────────────
    try:
        import pdfplumber

        text = ""

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"

        logger.warning(f"[PDF] pdfplumber: {len(text)} chars")

        if text and len(text.strip()) > 100:
            return _clean_text(text)

        logger.warning("[PDF] pdfplumber returned empty — trying OpenRouter OCR")

    except Exception as e:
        logger.error(f"[PDF] pdfplumber failed: {e}")

    # ── Stage 3: OCR ──────────────────────────────────────────
    return _openrouter_vision_ocr(file_path)


# ── OCR MODEL FALLBACK ────────────────────────────────────────
def _try_ocr_page(b64_image: str, page_num: int) -> str:

    for model in OPENROUTER_VISION_MODELS:

        try:
            logger.warning(f"[OCR] Page {page_num + 1}: trying model '{model}'...")

            r = requests.post(
                OPENROUTER_URL,
                headers=_openrouter_headers(),
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{b64_image}"
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": """
You are an OCR engine.

Extract ALL readable text from this PDF page.

Rules:
- Preserve paragraphs
- Preserve headings
- Preserve bullet points
- Ignore watermarks
- Ignore isolated page numbers
- Return ONLY extracted text
- Do NOT summarize
"""
                                },
                            ],
                        }
                    ],
                    "temperature": 0.1,
                    "max_tokens": 4000,
                },
                timeout=120,
            )

            if r.ok:

                result = r.json()

                page_text = (
                    result.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )

                logger.warning(
                    f"[OCR] Page {page_num + 1}: {len(page_text)} chars via '{model}'"
                )

                if len(page_text.strip()) > 50:
                    return page_text

            else:
                logger.warning(
                    f"[OCR] Model '{model}' returned {r.status_code}: {r.text[:200]}"
                )

        except Exception as e:
            logger.warning(f"[OCR] Model '{model}' failed: {e}")

    logger.error(f"[OCR] All OCR models failed for page {page_num + 1}")
    return ""


# ── OpenRouter Vision OCR ─────────────────────────────────────
def _openrouter_vision_ocr(file_path: str) -> str:

    api_key = os.getenv("OPENROUTER_API_KEY", "")

    if not api_key:
        logger.error("[OCR] OPENROUTER_API_KEY missing")
        return ""

    try:
        import fitz

        logger.warning("[OCR] Starting OpenRouter Vision OCR pipeline...")

        doc = fitz.open(file_path)

        all_text = []

        max_pages = min(len(doc), 5)

        for page_num in range(max_pages):

            page = doc[page_num]

            mat = fitz.Matrix(2, 2)

            pix = page.get_pixmap(matrix=mat)

            img_bytes = pix.tobytes("jpeg")

            b64_image = base64.b64encode(img_bytes).decode("utf-8")

            page_text = _try_ocr_page(b64_image, page_num)

            if page_text:
                all_text.append(page_text)

        doc.close()

        if not all_text:
            logger.error("[OCR] No OCR text extracted")
            return ""

        full_text = "\n\n".join(all_text)

        logger.warning(
            f"[OCR] Completed: {len(full_text)} chars extracted from {max_pages} page(s)"
        )

        cleaned = _clean_text(full_text)

        logger.warning(f"[OCR] Cleaned text length: {len(cleaned)}")

        return cleaned

    except Exception as e:
        logger.error(f"[OCR] Pipeline failed: {e}")
        return ""


# ── SAFE TEXT CLEANING ────────────────────────────────────────
def _clean_text(text: str) -> str:
    """
    Safe text cleaning without destroying OCR content
    """

    if not text:
        return ""

    # Normalize line breaks
    text = text.replace("\r", "\n")

    # Remove null bytes
    text = text.replace("\x00", "")

    # Remove excessive spaces
    text = re.sub(r"[ \t]+", " ", text)

    # Remove excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove repeated weird OCR artifacts
    text = re.sub(r"([^\w\s])\1{5,}", "", text)

    return text.strip()


# ── Summarization ─────────────────────────────────────────────
def summarize_text_groq(text: str) -> str:

    if not text or len(text.strip()) < 50:
        return text

    context = text[:15000]

    prompt = f"""
Provide a detailed structured summary of the following document.

Requirements:
- At least 10 lines
- Use bullet points
- Include key concepts
- Include important definitions
- Include conclusions if present

TEXT:
{context}
"""

    result = _groq_chat(
        prompt,
        system="You are a professional academic summarizer.",
        max_tokens=1200,
    )

    return result if result else text[:500]


def summarize_text(text: str) -> str:
    return summarize_text_groq(text)


# ── Question Answering ────────────────────────────────────────
def answer_question(question: str, context: str) -> dict:

    if not question or not context:
        return {
            "answer": "Insufficient context provided.",
            "score": 0.0
        }

    context = context[:15000]

    prompt = f"""
Based ONLY on the provided document text answer the question.

DOCUMENT:
{context}

QUESTION:
{question}

If answer not present say:
'This information is not available in the document.'
"""

    answer = _groq_chat(
        prompt,
        system="You are a document Q&A assistant.",
        max_tokens=500,
    )

    return {
        "answer": answer if answer else "Answer not found.",
        "score": 0.9 if answer else 0.0,
    }


# ── Key Topics ────────────────────────────────────────────────
def extract_key_topics(text: str, n: int = 10):

    try:
        import yake

        extractor = yake.KeywordExtractor(
            lan="en",
            n=2,
            dedupLim=0.8,
            top=n
        )

        keywords = extractor.extract_keywords(text)

        return [kw for kw, _ in keywords]

    except Exception:

        words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())

        stopwords = {
            "this", "that", "with", "from",
            "have", "been", "they", "their",
            "will", "which", "what"
        }

        freq = {}

        for w in words:
            if w not in stopwords:
                freq[w] = freq.get(w, 0) + 1

        return sorted(freq, key=freq.get, reverse=True)[:n]


# ── Translation ───────────────────────────────────────────────
def translate_text(text: str, target_lang: str, source_lang: str = "en"):

    if target_lang == source_lang or target_lang == "en":
        return text

    prompt = f"""
Translate the following text from {source_lang} to {target_lang}.

Return ONLY translated text.

TEXT:
{text}
"""

    result = _groq_chat(
        prompt,
        system="You are a professional translator.",
        max_tokens=1000,
    )

    if result:
        return result

    try:
        from googletrans import Translator

        translator = Translator()

        translated = translator.translate(
            text,
            dest=target_lang,
            src=source_lang
        )

        return translated.text

    except Exception as e:
        logger.error(f"[Translation] Failed: {e}")
        return text


# ── Session Aggregation ───────────────────────────────────────
def aggregate_session(snapshots: list):

    if not snapshots:
        return {
            "avg_attention": 0.0,
            "dominant_emotion": "unknown",
            "engagement_level": "low",
        }

    attentions = [
        s.get("attention_score", 0)
        for s in snapshots
    ]

    emotions = [
        s.get("emotion", "unknown")
        for s in snapshots
        if s.get("face_detected")
    ]

    avg_attention = (
        round(sum(attentions) / len(attentions), 3)
        if attentions else 0.0
    )

    dominant = (
        Counter(emotions).most_common(1)[0][0]
        if emotions else "unknown"
    )

    engagement = (
        "high"
        if avg_attention >= 0.7
        else "medium"
        if avg_attention >= 0.4
        else "low"
    )

    return {
        "avg_attention": avg_attention,
        "dominant_emotion": dominant,
        "engagement_level": engagement,
    }
