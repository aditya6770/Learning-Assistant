"""
NLP Engine
─────────
• PDF text extraction (PyMuPDF / pdfplumber)
• Summarization (HuggingFace pipeline — facebook/bart-large-cnn)
• Question Answering (deepset/roberta-base-squad2)
• Key topic extraction (YAKE keyword extractor)
• Translation (Helsinki-NLP MarianMT or googletrans)
"""
import os, re, logging, requests, json
from typing import Optional

logger = logging.getLogger(__name__)

# ── Lazy-loaded models (only import when first used) ──────────────────────────
_summarizer = None
_qa_pipeline = None


def _get_summarizer():
    global _summarizer
    if _summarizer is None:
        from transformers import pipeline
        logger.info("Loading summarization model (first use)…")
        _summarizer = pipeline(
    "summarization",
    model="sshleifer/distilbart-cnn-12-6",
    framework="pt"
)
    return _summarizer


def _get_qa_pipeline():
    global _qa_pipeline
    if _qa_pipeline is None:
        from transformers import pipeline
        logger.info("Loading QA model (first use)…")
        _qa_pipeline = pipeline(
            "question-answering",
            model="deepset/roberta-base-squad2",
            device=-1,
        )
    return _qa_pipeline


# ── PDF Extraction ─────────────────────────────────────────────────────────────
def extract_text_from_pdf(file_path: str) -> str:
    """Return plain text from a PDF file."""
    try:
        import fitz  # PyMuPDF
        doc  = fitz.open(file_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return _clean_text(text)
    except ImportError:
        pass

    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        return _clean_text(text)
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\x00-\x7F]+", " ", text)   # strip non-ASCII
    return text.strip()


# ── Summarisation ─────────────────────────────────────────────────────────────
def summarize_text_groq(text: str) -> str:
    """Return a detailed (at least 10 lines) summary using Groq AI."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return summarize_text(text)

    # Limit context for prompt
    context = text[:15000] 
    
    prompt = (
        "Please provide a comprehensive and detailed summary of the following text. "
        "The summary MUST be at least 10 lines long and structured clearly. "
        "Use bullet points if helpful. Focus on the key concepts and actionable insights. "
        f"\n\nTEXT:\n{context}"
    )

    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": "You are a professional academic summarizer."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.5,
            "max_tokens": 1000
        }
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        if r.ok:
            return r.json()["choices"][0]["message"]["content"]
        else:
            logger.error(f"Groq summary failed: {r.status_code} {r.text}")
            return summarize_text(text)
    except Exception as e:
        logger.error(f"Groq summary exception: {e}")
        return summarize_text(text)

def summarize_text(text: str) -> str:
    """Return a concise summary of the given text."""
    if not text or len(text.split()) < 50:
        return text

    summarizer = _get_summarizer()

    # Limit extreme long inputs
    max_chars = 4000
    text = text[:max_chars]

    try:
        result = summarizer(
            text,
            max_length=150,
            min_length=40,
            do_sample=False,
            truncation=True,
        )
        return result[0]["summary_text"]
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        return text[:300]


def _chunk_text(text: str, max_words: int = 800) -> list:
    words  = text.split()
    return [
        " ".join(words[i : i + max_words])
        for i in range(0, len(words), max_words)
    ]


# ── Question Answering ────────────────────────────────────────────────────────
def answer_question(question: str, context: str) -> dict:
    """Return {answer, score, start, end} using extractive QA."""
    if not question or not context:
        return {"answer": "Insufficient context provided.", "score": 0.0}

    # Truncate context to ~3000 words for the model
    context_trunc = " ".join(context.split()[:3000])
    try:
        qa   = _get_qa_pipeline()
        result = qa(question=question, context=context_trunc)
        return {
            "answer": result.get("answer", ""),
            "score":  round(result.get("score", 0.0), 4),
        }
    except Exception as e:
        logger.error(f"QA failed: {e}")
        return {"answer": "Could not find an answer in the document.", "score": 0.0}


# ── Keyword / Topic Extraction ────────────────────────────────────────────────
def extract_key_topics(text: str, n: int = 10) -> list:
    """Return top-n keywords/phrases using YAKE."""
    try:
        import yake
        extractor = yake.KeywordExtractor(
            lan="en", n=2, dedupLim=0.8, top=n, features=None
        )
        keywords = extractor.extract_keywords(text)
        return [kw for kw, _ in keywords]
    except ImportError:
        # Fallback: simple frequency-based extraction
        words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
        stopwords = {"this","that","with","from","have","been","they",
                     "their","will","what","when","which","were","also"}
        freq = {}
        for w in words:
            if w not in stopwords:
                freq[w] = freq.get(w, 0) + 1
        sorted_words = sorted(freq, key=freq.get, reverse=True)
        return sorted_words[:n]


# ── Translation ───────────────────────────────────────────────────────────────
def translate_text(text: str, target_lang: str, source_lang: str = "en") -> str:
    """
    Translate text using Helsinki-NLP MarianMT models.
    Falls back to googletrans if model not available.
    """
    if target_lang == source_lang or target_lang == "en":
        return text

    # Try MarianMT first
    try:
        from transformers import MarianMTModel, MarianTokenizer
        model_name = f"Helsinki-NLP/opus-mt-{source_lang}-{target_lang}"
        tokenizer  = MarianTokenizer.from_pretrained(model_name)
        model      = MarianMTModel.from_pretrained(model_name)
        tokens     = tokenizer([text], return_tensors="pt", padding=True, truncation=True)
        translated = model.generate(**tokens)
        return tokenizer.decode(translated[0], skip_special_tokens=True)
    except Exception:
        pass

    # Fallback: googletrans
    try:
        from googletrans import Translator
        translator = Translator()
        result = translator.translate(text, dest=target_lang, src=source_lang)
        return result.text
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return text
