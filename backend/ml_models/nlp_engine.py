"""
NLP Engine — Groq-powered (no local models)
────────────────────────────────────────────
- PDF text extraction (PyMuPDF / pdfplumber / OCR fallback)
- Summarization     → Groq llama-3.1-8b-instant
- Question Answering → Groq llama-3.1-8b-instant
- Key topic extraction → YAKE (lightweight, no torch)
- Translation        → Groq / googletrans
"""
import os, re, logging, requests, json
from typing import Optional

logger = logging.getLogger(__name__)

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"


def _groq_headers():
    return {
        "Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '')}",
        "Content-Type": "application/json"
    }


def _groq_chat(prompt: str, system: str = "You are a helpful AI assistant.", max_tokens: int = 1000) -> str:
    """Core Groq API call — returns text response."""
    try:
        r = requests.post(GROQ_URL, headers=_groq_headers(), json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt}
            ],
            "temperature": 0.4,
            "max_tokens":  max_tokens,
        }, timeout=30)
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
    Extract plain text from PDF.
    Tries: PyMuPDF → pdfplumber → OCR (for scanned/image PDFs)
    """
    if not os.path.exists(file_path):
        logger.error(f"[PDF] File does not exist: {file_path}")
        return ""

    file_size = os.path.getsize(file_path)
    logger.warning(f"[PDF] File size: {file_size} bytes")

    if file_size == 0:
        logger.error("[PDF] File is empty (0 bytes)")
        return ""

    # ── Method 1: PyMuPDF ──
    try:
        import fitz
        doc   = fitz.open(file_path)
        pages = len(doc)
        text  = "\n".join(page.get_text() for page in doc)
        doc.close()
        logger.warning(f"[PDF] PyMuPDF: {len(text)} chars from {pages} pages")
        if text.strip():
            return _clean_text(text)
        logger.warning("[PDF] PyMuPDF returned empty — trying pdfplumber")
    except Exception as e:
        logger.warning(f"[PDF] PyMuPDF failed: {e}")

    # ── Method 2: pdfplumber ──
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        logger.warning(f"[PDF] pdfplumber: {len(text)} chars")
        if text.strip():
            return _clean_text(text)
        logger.warning("[PDF] pdfplumber returned empty — trying OCR")
    except Exception as e:
        logger.error(f"[PDF] pdfplumber failed: {e}")

    # ── Method 3: OCR (for scanned/image-based PDFs) ──
    try:
        logger.warning("[PDF] Attempting OCR extraction...")
        import pytesseract
        from pdf2image import convert_from_path
        from PIL import Image

        pages = convert_from_path(file_path, dpi=200)
        logger.warning(f"[PDF] OCR: converted {len(pages)} pages to images")

        ocr_text = ""
        for i, page in enumerate(pages):
            page_text = pytesseract.image_to_string(page, lang="eng")
            ocr_text += page_text + "\n"
            logger.warning(f"[PDF] OCR page {i+1}: {len(page_text)} chars")

        if ocr_text.strip():
            logger.warning(f"[PDF] OCR total: {len(ocr_text)} chars")
            return _clean_text(ocr_text)
        else:
            logger.error("[PDF] OCR also returned empty text")
    except ImportError as e:
        logger.error(f"[PDF] OCR library missing: {e}")
    except Exception as e:
        logger.error(f"[PDF] OCR failed: {e}")

    logger.error("[PDF] All extraction methods failed")
    return ""


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\x00-\x7F]+", " ", text)
    return text.strip()


# ── Summarization ──────────────────────────────────────────────
def summarize_text_groq(text: str) -> str:
    """Detailed 10+ line summary via Groq."""
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
        max_tokens=1000
    )
    return result if result else text[:300]


def summarize_text(text: str) -> str:
    """Always routes to Groq — no local model needed."""
    return summarize_text_groq(text)


# ── Question Answering ─────────────────────────────────────────
def answer_question(question: str, context: str) -> dict:
    """Answer a question using Groq based on document context."""
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
        max_tokens=400
    )
    return {
        "answer": answer if answer else "Could not find an answer in the document.",
        "score":  0.9 if answer else 0.0,
    }


# ── Key Topic Extraction ───────────────────────────────────────
def extract_key_topics(text: str, n: int = 10) -> list:
    """Extract top-n keywords using YAKE (no torch required)."""
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
            "their", "will", "what", "when", "which", "were", "also"
        }
        freq = {}
        for w in words:
            if w not in stopwords:
                freq[w] = freq.get(w, 0) + 1
        return sorted(freq, key=freq.get, reverse=True)[:n]


# ── Translation ────────────────────────────────────────────────
def translate_text(text: str, target_lang: str, source_lang: str = "en") -> str:
    """Translate using Groq first, fallback to googletrans."""
    if target_lang == source_lang or target_lang == "en":
        return text

    prompt = (
        f"Translate the following text from {source_lang} to {target_lang}. "
        f"Return ONLY the translated text, nothing else.\n\nTEXT:\n{text}"
    )
    result = _groq_chat(
        prompt,
        system="You are a professional translator.",
        max_tokens=500
    )
    if result:
        return result

    try:
        from googletrans import Translator
        translator = Translator()
        result = translator.translate(text, dest=target_lang, src=source_lang)
        return result.text
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return text


# ── Session Aggregation (kept for compatibility) ───────────────
def aggregate_session(snapshots: list) -> dict:
    if not snapshots:
        return {
            "avg_attention":    0.0,
            "dominant_emotion": "unknown",
            "engagement_level": "low"
        }
    attentions    = [s.get("attention_score", 0) for s in snapshots]
    emotions      = [s.get("emotion", "unknown") for s in snapshots if s.get("face_detected")]
    avg_attention = round(sum(attentions) / len(attentions), 3) if attentions else 0.0

    from collections import Counter
    dominant   = Counter(emotions).most_common(1)[0][0] if emotions else "unknown"
    engagement = "high" if avg_attention >= 0.7 else ("medium" if avg_attention >= 0.45 else "low")

    return {
        "avg_attention":    avg_attention,
        "dominant_emotion": dominant,
        "engagement_level": engagement
    }
