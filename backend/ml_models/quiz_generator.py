"""
Quiz Generator
──────────────
Generates three types of questions from study material:
  • MCQ (Multiple Choice)
  • Fill-in-the-blank
  • Descriptive (open-ended)

Approach:
  1. Extract sentences with key nouns/entities as question sources.
  2. For MCQ: use a T5 QG model (valhalla/t5-small-qg-hl) or pattern rules.
  3. Distractors: WordNet / same-doc frequency words.
  4. Fill-in-the-blank: mask named entities / keyword spans.
  5. Descriptive: template questions on summarised paragraphs.
"""
import re, random, logging
from typing import List, Dict

logger = logging.getLogger(__name__)

_qg_pipeline = None


def _get_qg_pipeline():
    global _qg_pipeline
    if _qg_pipeline is None:
        try:
            from transformers import pipeline
            logger.info("Loading question-generation model…")
            _qg_pipeline = pipeline(
                "text2text-generation",
                model="valhalla/t5-small-qg-hl",
                device=-1,
            )
        except Exception as e:
            logger.warning(f"QG model not loaded ({e}), using rule-based fallback")
            _qg_pipeline = "fallback"
    return _qg_pipeline


# ── Public API ────────────────────────────────────────────────────────────────
def generate_quiz(
    text: str,
    n_mcq: int = 5,
    n_fib: int = 3,
    n_desc: int = 2,
    difficulty: str = "medium",
) -> List[Dict]:
    """
    Return a flat list of question dicts ready for DB storage.
    Each dict: { id, type, question, options, correct_answer,
                 explanation, difficulty }
    """
    sentences = _extract_sentences(text)
    questions = []
    q_id      = 1

    # MCQ
    for q in _generate_mcq(sentences, text, n_mcq, difficulty):
        q["id"] = q_id; q_id += 1
        questions.append(q)

    # Fill-in-the-blank
    for q in _generate_fib(sentences, n_fib, difficulty):
        q["id"] = q_id; q_id += 1
        questions.append(q)

    # Descriptive
    for q in _generate_descriptive(text, n_desc):
        q["id"] = q_id; q_id += 1
        questions.append(q)

    random.shuffle(questions)
    return questions


# ── MCQ ───────────────────────────────────────────────────────────────────────
def _generate_mcq(sentences: List[str], full_text: str, n: int, difficulty: str) -> List[Dict]:
    questions = []
    pipe      = _get_qg_pipeline()
    candidates = [s for s in sentences if len(s.split()) > 8][:n * 2]

    for sent in candidates[:n]:
        # Highlight the "answer" span (first named noun chunk)
        answer_span, highlighted = _highlight_answer(sent)
        if not answer_span:
            continue

        # Try model-based QG
        question_text = None
        if pipe != "fallback":
            try:
                prompt = f"generate question: {highlighted}"
                out    = pipe(prompt, max_new_tokens=64, num_beams=4)[0]["generated_text"]
                question_text = out.strip()
            except Exception:
                pass

        if not question_text:
            question_text = _rule_based_question(sent, answer_span)

        distractors = _get_distractors(answer_span, full_text, n=3)
        options = distractors + [answer_span]
        random.shuffle(options)

        questions.append({
            "type": "mcq",
            "question": question_text,
            "options": options,
            "correct_answer": answer_span,
            "explanation": f"The correct answer can be found in: \"{sent[:120]}...\"",
            "difficulty": difficulty,
        })

    return questions


def _highlight_answer(sentence: str):
    """Pick a span to be the answer and wrap it in <hl>…</hl>."""
    # Pick the last meaningful noun phrase (simple heuristic)
    words = sentence.split()
    # Find longest capitalized sequence (likely proper noun)
    caps_run = []
    for i, w in enumerate(words):
        clean = re.sub(r"[^a-zA-Z]", "", w)
        if clean and clean[0].isupper() and i > 0:
            caps_run.append((i, clean))
        else:
            if len(caps_run) >= 1:
                break
            caps_run = []

    if caps_run:
        span = " ".join(c for _, c in caps_run)
        hl   = sentence.replace(span, f"<hl> {span} </hl>", 1)
        return span, hl

    # Fallback: pick a content word from the middle
    content = [w for w in words if len(w) > 4 and w.isalpha()]
    if content:
        span = content[len(content) // 2]
        hl   = sentence.replace(span, f"<hl> {span} </hl>", 1)
        return span, hl

    return None, sentence


def _rule_based_question(sentence: str, answer: str) -> str:
    """Simple rule: replace answer span with 'What/Which __?'"""
    q = sentence.replace(answer, "___")
    return f"Fill in: {q} (What is the missing term?)"


def _get_distractors(correct: str, text: str, n: int = 3) -> List[str]:
    """
    Return n plausible-but-wrong options.
    Strategy: WordNet synonyms → same-doc frequent words → generic placeholders.
    """
    distractors = []

    # WordNet
    try:
        from nltk.corpus import wordnet
        import nltk
        nltk.download("wordnet", quiet=True)
        for syn in wordnet.synsets(correct.split()[0])[:5]:
            for lemma in syn.lemmas():
                word = lemma.name().replace("_", " ")
                if word.lower() != correct.lower() and word not in distractors:
                    distractors.append(word.capitalize())
    except Exception:
        pass

    # Same-doc frequent capitalised words
    if len(distractors) < n:
        words = re.findall(r"\b[A-Z][a-z]{3,}\b", text)
        freq  = {}
        for w in words:
            if w.lower() != correct.lower():
                freq[w] = freq.get(w, 0) + 1
        for w in sorted(freq, key=freq.get, reverse=True):
            if w not in distractors:
                distractors.append(w)
            if len(distractors) >= n:
                break

    # Generic placeholders
    placeholders = ["None of the above", "All of the above", "Not defined", "Cannot be determined"]
    while len(distractors) < n:
        distractors.append(placeholders[len(distractors) % len(placeholders)])

    return distractors[:n]


# ── Fill-in-the-blank ─────────────────────────────────────────────────────────
def _generate_fib(sentences: List[str], n: int, difficulty: str) -> List[Dict]:
    questions = []
    candidates = [s for s in sentences if len(s.split()) > 6]

    for sent in candidates[:n]:
        words   = [w for w in sent.split() if len(w) > 4 and w.isalpha()]
        if not words:
            continue
        target  = random.choice(words)
        blanked = sent.replace(target, "_____", 1)

        questions.append({
            "type": "fill_in_blank",
            "question": blanked,
            "options": [],
            "correct_answer": target,
            "explanation": f"Original sentence: \"{sent}\"",
            "difficulty": difficulty,
        })

    return questions


# ── Descriptive ───────────────────────────────────────────────────────────────
_DESC_TEMPLATES = [
    "Explain the concept of '{topic}' as discussed in the material.",
    "What is the significance of '{topic}'? Discuss in detail.",
    "Compare and contrast '{topic}' with related concepts from the text.",
    "How does '{topic}' relate to the main theme of the document?",
    "Summarize the key points about '{topic}' in your own words.",
]


def _generate_descriptive(text: str, n: int) -> List[Dict]:
    from ml_models.nlp_engine import extract_key_topics
    topics = extract_key_topics(text, n=max(n, 5))
    questions = []

    for i in range(min(n, len(topics))):
        topic    = topics[i]
        template = _DESC_TEMPLATES[i % len(_DESC_TEMPLATES)]
        questions.append({
            "type": "descriptive",
            "question": template.format(topic=topic),
            "options": [],
            "correct_answer": "",    # graded manually / by AI
            "explanation": "This is an open-ended question. Write a detailed answer.",
            "difficulty": "hard",
        })

    return questions


# ── Helpers ───────────────────────────────────────────────────────────────────
def _extract_sentences(text: str) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]
