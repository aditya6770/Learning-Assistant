"""
NLP Engine — Groq-powered + OpenRouter Vision OCR
────────────────────────────────────────────────────
- PDF text extraction (PyMuPDF → pdfplumber → OpenRouter Vision OCR)
- Summarization     → Groq llama-3.1-8b-instant
- Question Answering → Groq llama-3.1-8b-instant
- Key topic extraction → YAKE (lightweight, no torch)
- Translation        → Groq / googletrans
"""
import os, re, logging, requests, json, base64
from typing import Optional

logger = logging.getLogger(__name__)

GROQ_URL        = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL      = "llama-3.1-8b-instant"
OPENROUTER_URL  = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "nvidia/llama-3.1-nemotron-nano-vl-8b-v1:free"


def _groq_headers():
    return {
        "Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '')}",
        "Content-Type": "application/json"
    }


def _openrouter_headers():
    return {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://learning-assistant-a7n9.onrender.com",
        "X-Title": "AI Learning Assistant"
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
    Extract text from PDF:
    1. PyMuPDF      (fast, text-based PDFs)
    2. pdfplumber   (fallback for text PDFs)
    3. OpenRouter Vision OCR (scanned/image PDFs)
    """
    if not os.path.exists(file_path):
        logger.error(f"[PDF] File not found: {file_path}")
        return ""

    if os.path.getsize(file_path) == 0:
        logger.error("[PDF] File is empty")
        return ""

    # ── Method 1: PyMuPDF ──
    try:
        import fitz
        doc  = fitz.open(file_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        if text.strip():
            logger.warning(f"[PDF] PyMuPDF success: {len(text)} chars")
            return _clean_text(text)
        logger.warning("[PDF] PyMuPDF empty — trying pdfplumber")
    except Exception as e:
        logger.warning(f"[PDF] PyMuPDF failed: {e}")

    # ── Method 2: pdfplumber ──
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        if text.strip():
            logger.warning(f"[PDF] pdfplumber success: {len(text)} chars")
            return _clean_text(text)
        logger.warning("[PDF] pdfplumber empty — trying OpenRouter Vision OCR")
    except Exception as e:
        logger.warning(f"[PDF] pdfplumber failed: {e}")

    # ── Method 3: OpenRouter Vision OCR ──
    return _openrouter_vision_ocr(file_path)


def _openrouter_vision_ocr(file_path: str) -> str:
    """
    Convert PDF pages to images and use OpenRouter Vision
    (Nemotron Nano 12B VL) to extract text.
    No system packages needed — uses PyMuPDF for rendering.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.error("[OCR] OPENROUTER_API_KEY not set")
        return ""

    try:
        import fitz
        logger.warning("[OCR] Starting OpenRouter Vision OCR...")

        doc       = fitz.open(file_path)
        all_text  = []
        max_pages = min(len(doc), 5)  # max 5 pages to stay within limits

        for page_num in range(max_pages):
            page = doc[page_num]

            # Render page to JPEG image at 150 DPI
            mat      = fitz.Matrix(150/72, 150/72)
            pix      = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("jpeg")
            b64_image = base64.b64encode(img_bytes).decode("utf-8")

            logger.warning(f"[OCR] Sending page {page_num + 1}/{max_pages} to OpenRouter...")

            try:
                r = requests.post(
                    OPENROUTER_URL,
                    headers=_openrouter_headers(),
                    json={
                        "model": OPENROUTER_MODEL,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{b64_image}"
                                        }
                                    },
                                    {
                                        "type": "text",
                                        "text": (
                                            "Extract ALL text from this image exactly as it appears. "
                                            "Preserve the structure and formatting. "
                                            "Return only the extracted text, nothing else."
                                        )
                                    }
                                ]
                            }
                        ],
                        "max_tokens": 2000,
                        "temperature": 0.1
                    },
                    timeout=60
                )

                if r.ok:
                    page_text = r.json()["choices"][0]["message"]["content"]
                    all_text.append(page_text)
                    logger.warning(f"[OCR] Page {page_num+1}: {len(page_text)} chars")
                else:
                    logger.error(f"[OCR] OpenRouter error on page {page_num+1}: {r.status_code} {r.text[:200]}")

            except Exception as e:
                logger.error(f"[OCR] Page {page_num+1} request failed: {e}")

        doc.close()

        if all_text:
            full_text = "\n\n".join(all_text)
            logger.warning(f"[OCR] Total extracted: {len(full_text)} chars from {max_pages} pages")
            return _clean_text(full_text)
        else:
            logger.error("[OCR] OpenRouter Vision returned no text")
            return ""

    except Exception as e:
        logger.error(f"[OCR] OpenRouter Vision OCR completely failed: {e}")
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
