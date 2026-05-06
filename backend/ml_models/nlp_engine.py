"""
NLP Engine — Groq-powered + OpenRouter Vision OCR
────────────────────────────────────────────────────
- PDF text extraction (PyMuPDF → pdfplumber → OpenRouter Vision OCR)
- Summarization     → Groq llama-3.1-8b-instant
- Question Answering → Groq llama-3.1-8b-instant
- Key topic extraction → YAKE (lightweight, no torch)
- Translation        → Groq / googletrans

FIXES (May 2026):
- Replaced deprecated google/gemini-2.0-flash-exp:free with a
  prioritized fallback list of active free vision models on OpenRouter.
- Added _try_ocr_page() helper that cycles through models on 404/error.
"""

import os
import re
import logging
import requests
import json
import base64
from typing import Optional

logger = logging.getLogger(__name__)

# ── API endpoints ──────────────────────────────────────────────
GROQ_URL         = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL       = "llama-3.1-8b-instant"
OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"

# ── Free vision models in priority order ──────────────────────
# If the first model fails (404 / rate-limit / etc.) the next is tried.
# Add or reorder as OpenRouter's free catalogue changes.
OPENROUTER_VISION_MODELS = [
    "qwen/qwen2.5-vl-32b-instruct:free",          # strong OCR, 32B
    "meta-llama/llama-3.2-11b-vision-instruct:free",  # reliable fallback
    "google/gemma-4-26b-a4b-it:free",              # Google Gemma 4 (vision)
    "google/gemma-4-31b-it:free",                  # larger Gemma variant
    "openrouter/free",                              # auto-router catch-all
]


# ── Auth headers ───────────────────────────────────────────────
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


# ── Core Groq call ─────────────────────────────────────────────
def _groq_chat(
    prompt: str,
    system: str = "You are a helpful AI assistant.",
    max_tokens: int = 1000,
) -> str:
    """Send a chat completion request to Groq and return the text response."""
    try:
        r = requests.post(
            GROQ_URL,
            headers=_groq_headers(),
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                "temperature": 0.4,
                "max_tokens":  max_tokens,
            },
            timeout=30,
        )
        if r.ok:
            return r.json()["choices"][0]["message"]["content"].strip()
        else:
            logger.error(f"Groq API error: {r.status_code} {r.text}")
            return ""
    except Exception as e:
        logger.error(f"Groq call failed: {e}")
        return ""


# ── PDF Extraction ─────────────────────────────────────────────
def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract text from a PDF using a three-stage pipeline:
      1. PyMuPDF      — fast, works on text-based PDFs
      2. pdfplumber   — fallback for text PDFs
      3. OpenRouter Vision OCR — for scanned / image-only PDFs
    """
    if not os.path.exists(file_path):
        logger.error(f"[PDF] File not found: {file_path}")
        return ""

    if os.path.getsize(file_path) == 0:
        logger.error("[PDF] File is empty")
        return ""

    # ── Stage 1: PyMuPDF ──────────────────────────────────────
    try:
        import fitz  # PyMuPDF
        doc  = fitz.open(file_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        if text.strip():
            logger.warning(f"[PDF] PyMuPDF success: {len(text)} chars")
            return _clean_text(text)
        logger.warning("[PDF] PyMuPDF returned empty text — trying pdfplumber")
    except Exception as e:
        logger.warning(f"[PDF] PyMuPDF failed: {e}")

    # ── Stage 2: pdfplumber ───────────────────────────────────
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        if text.strip():
            logger.warning(f"[PDF] pdfplumber success: {len(text)} chars")
            return _clean_text(text)
        logger.warning("[PDF] pdfplumber returned empty text — trying OpenRouter Vision OCR")
    except Exception as e:
        logger.warning(f"[PDF] pdfplumber failed: {e}")

    # ── Stage 3: OpenRouter Vision OCR ────────────────────────
    return _openrouter_vision_ocr(file_path)


# ── OpenRouter Vision OCR ──────────────────────────────────────
def _try_ocr_page(b64_image: str, page_num: int) -> str:
    """
    Try each model in OPENROUTER_VISION_MODELS in order.
    Returns the extracted text from the first model that succeeds,
    or an empty string if all models fail.
    """
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
                                    "text": (
                                        "Extract ALL text from this image exactly as it appears. "
                                        "Preserve the structure and formatting. "
                                        "Return only the extracted text, nothing else."
                                    ),
                                },
                            ],
                        }
                    ],
                    "max_tokens":  2000,
                    "temperature": 0.1,
                },
                timeout=60,
            )

            if r.ok:
                page_text = r.json()["choices"][0]["message"]["content"]
                logger.warning(
                    f"[OCR] Page {page_num + 1}: {len(page_text)} chars via '{model}'"
                )
                return page_text
            else:
                error_body = r.text[:200]
                logger.warning(
                    f"[OCR] Model '{model}' returned {r.status_code}: {error_body} — trying next model"
                )

        except Exception as e:
            logger.warning(f"[OCR] Model '{model}' raised exception: {e} — trying next model")

    logger.error(f"[OCR] All models failed for page {page_num + 1}")
    return ""


def _openrouter_vision_ocr(file_path: str) -> str:
    """
    Render each PDF page as a JPEG and send to OpenRouter Vision OCR.
    Uses _try_ocr_page() which automatically falls back across models.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.error("[OCR] OPENROUTER_API_KEY environment variable is not set")
        return ""

    try:
        import fitz  # PyMuPDF — used here only for rendering, not text extraction
        logger.warning("[OCR] Starting OpenRouter Vision OCR pipeline...")

        doc       = fitz.open(file_path)
        all_text  = []
        max_pages = min(len(doc), 5)  # cap at 5 pages to stay within free-tier limits

        for page_num in range(max_pages):
            page = doc[page_num]

            # Render page to JPEG at 150 DPI (good balance of quality vs. payload size)
            mat       = fitz.Matrix(150 / 72, 150 / 72)
            pix       = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("jpeg")
            b64_image = base64.b64encode(img_bytes).decode("utf-8")

            page_text = _try_ocr_page(b64_image, page_num)
            if page_text:
                all_text.append(page_text)

        doc.close()

        if all_text:
            full_text = "\n\n".join(all_text)
            logger.warning(
                f"[OCR] Completed: {len(full_text)} chars extracted from {max_pages} page(s)"
            )
            return _clean_text(full_text)
        else:
            logger.error("[OCR] All pages returned no text from any model")
            return ""

    except Exception as e:
        logger.error(f"[OCR] Vision OCR pipeline completely failed: {e}")
        return ""


# ── Text Cleaning ──────────────────────────────────────────────
def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\x00-\x7F]+", " ", text)
    return text.strip()


# ── Summarization ──────────────────────────────────────────────
def summarize_text_groq(text: str) -> str:
    """Generate a detailed 10+ line summary via Groq."""
    if not text or len(text.strip()) < 50:
        return text

    context = text[:15000]
    prompt  = (
        "Provide a comprehensive and detailed summary of the following text. "
        "The summary MUST be at least 10 lines long and clearly structured. "
        "Use bullet points where helpful. Focus on key concepts and insights.\n\n"
        f"TEXT:\n{context}"
    )
    result = _groq_chat(
        prompt,
        system="You are a professional academic summarizer.",
        max_tokens=1000,
    )
    return result if result else text[:300]


def summarize_text(text: str) -> str:
    """Public entry point — always routes to Groq (no local model needed)."""
    return summarize_text_groq(text)


# ── Question Answering ─────────────────────────────────────────
def answer_question(question: str, context: str) -> dict:
    """Answer a question strictly from the provided document context."""
    if not question or not context:
        return {"answer": "Insufficient context provided.", "score": 0.0}

    context_trunc = " ".join(context.split()[:4000])
    prompt = (
        f"Based ONLY on the following document text, answer the question accurately.\n\n"
        f"DOCUMENT:\n{context_trunc}\n\n"
        f"QUESTION: {question}\n\n"
        "If the answer is not in the document, say: "
        "'This information is not available in the document.'\n"
        "Answer:"
    )
    answer = _groq_chat(
        prompt,
        system="You are a precise document Q&A assistant.",
        max_tokens=400,
    )
    return {
        "answer": answer if answer else "Could not find an answer in the document.",
        "score":  0.9 if answer else 0.0,
    }


# ── Key Topic Extraction ───────────────────────────────────────
def extract_key_topics(text: str, n: int = 10) -> list:
    """
    Extract top-n keywords using YAKE (no PyTorch required).
    Falls back to a simple frequency counter if YAKE is not installed.
    """
    try:
        import yake
        extractor = yake.KeywordExtractor(
            lan="en", n=2, dedupLim=0.8, top=n, features=None
        )
        keywords = extractor.extract_keywords(text)
        return [kw for kw, _ in keywords]
    except ImportError:
        words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
        stopwords = {
            "this", "that", "with", "from", "have", "been", "they",
            "their", "will", "what", "when", "which", "were", "also",
        }
        freq: dict = {}
        for w in words:
            if w not in stopwords:
                freq[w] = freq.get(w, 0) + 1
        return sorted(freq, key=freq.get, reverse=True)[:n]


# ── Translation ────────────────────────────────────────────────
def translate_text(text: str, target_lang: str, source_lang: str = "en") -> str:
    """
    Translate text via Groq first; falls back to googletrans if Groq fails.
    Returns the original text unchanged when target == source or target == 'en'.
    """
    if target_lang == source_lang or target_lang == "en":
        return text

    prompt = (
        f"Translate the following text from {source_lang} to {target_lang}. "
        f"Return ONLY the translated text, nothing else.\n\nTEXT:\n{text}"
    )
    result = _groq_chat(
        prompt,
        system="You are a professional translator.",
        max_tokens=500,
    )
    if result:
        return result

    # Fallback: googletrans
    try:
        from googletrans import Translator
        translator = Translator()
        translated = translator.translate(text, dest=target_lang, src=source_lang)
        return translated.text
    except Exception as e:
        logger.error(f"[Translation] googletrans failed: {e}")
        return text


# ── Session Aggregation ────────────────────────────────────────
def aggregate_session(snapshots: list) -> dict:
    """
    Aggregate a list of attention/emotion snapshots into session-level metrics.
    Kept for backward compatibility with the rest of the app.
    """
    if not snapshots:
        return {
            "avg_attention":    0.0,
            "dominant_emotion": "unknown",
            "engagement_level": "low",
        }

    attentions    = [s.get("attention_score", 0) for s in snapshots]
    emotions      = [s.get("emotion", "unknown") for s in snapshots if s.get("face_detected")]
    avg_attention = round(sum(attentions) / len(attentions), 3) if attentions else 0.0

    from collections import Counter
    dominant   = Counter(emotions).most_common(1)[0][0] if emotions else "unknown"
    engagement = (
        "high"   if avg_attention >= 0.7  else
        "medium" if avg_attention >= 0.45 else
        "low"
    )

    return {
        "avg_attention":    avg_attention,
        "dominant_emotion": dominant,
        "engagement_level": engagement,
    }
