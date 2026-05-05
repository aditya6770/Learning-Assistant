"""
Adaptive Revision Planner — 100% Local NLP (No API Required)
Extracts topics from documents using frequency analysis + heading detection.
Scores and ranks topics without any external API calls.
"""

import os
import re
import math
from collections import Counter


# ══════════════════════════════════════════════════════════════
#  TEXT EXTRACTION
# ══════════════════════════════════════════════════════════════

def extract_text_from_file(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        try:
            import fitz
            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            return text.strip()
        except Exception as e:
            raise ValueError(f"Failed to read PDF: {e}")
    elif ext in (".txt", ".md"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    else:
        raise ValueError(f"Unsupported file type: {ext}. Use PDF or TXT.")


# ══════════════════════════════════════════════════════════════
#  STOPWORDS
# ══════════════════════════════════════════════════════════════

STOPWORDS = {
    'the','a','an','and','or','but','in','on','at','to','for','of','with',
    'by','from','is','are','was','were','be','been','being','have','has',
    'had','do','does','did','will','would','could','should','may','might',
    'shall','can','this','that','these','those','it','its','as','if','then',
    'than','so','also','more','most','other','some','such','not','no','nor',
    'only','own','same','very','just','each','all','both','any','into',
    'through','during','before','after','above','below','between','out',
    'off','over','under','again','further','once','here','there','when',
    'where','why','how','which','who','whom','what','we','they','he','she',
    'you','i','me','him','her','us','them','my','your','his','our','their',
    'about','up','used','using','use','like','well','example','fig','figure',
    'table','page','ref','etc','ie','eg','one','two','three','first','second',
    'third','can','need','many','much','new','get','set','given','based',
    'provide','different','following','however','therefore','thus','hence',
    'while','since','whether','without','within','along','among','various'
}


# ══════════════════════════════════════════════════════════════
#  SECTION SPLITTING
# ══════════════════════════════════════════════════════════════

def split_into_sections(text: str) -> list:
    lines = text.split('\n')
    sections = []
    current_heading = "Overview"
    current_content = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        is_heading = (
            len(line) < 100 and len(line) > 3 and
            not line.endswith(',') and
            (
                line.isupper() or
                bool(re.match(r'^(unit|chapter|section|topic|module|part|introduction|conclusion)\b', line.lower())) or
                bool(re.match(r'^\d+[\.\)]\s+[A-Z]', line)) or
                bool(re.match(r'^[A-Z][A-Z\s]{5,}$', line)) or
                (line.istitle() and len(line.split()) <= 8 and not line.endswith('.'))
            )
        )

        if is_heading:
            if current_content and len(' '.join(current_content)) > 50:
                sections.append({
                    "heading": current_heading,
                    "content": ' '.join(current_content)
                })
            current_heading = line
            current_content = []
        else:
            current_content.append(line)

    if current_content:
        sections.append({
            "heading": current_heading,
            "content": ' '.join(current_content)
        })

    return sections


def chunk_text(text: str, chunk_size: int = 400) -> list:
    """Fallback: chunk text when no headings found."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunk_words = words[i:i + chunk_size]
        chunk_text_str = ' '.join(chunk_words)
        # Use first meaningful words as heading
        meaningful = [w for w in chunk_words[:8] if w.lower() not in STOPWORDS]
        heading = ' '.join(meaningful[:4]).title() if meaningful else f"Section {i//chunk_size + 1}"
        chunks.append({"heading": heading, "content": chunk_text_str})
    return chunks


# ══════════════════════════════════════════════════════════════
#  KEYWORD EXTRACTION
# ══════════════════════════════════════════════════════════════

def extract_keywords(text: str, top_n: int = 20) -> list:
    """Extract important keywords using TF analysis."""
    clean = re.sub(r'[^\w\s]', ' ', text.lower())
    words = [w for w in clean.split() if w not in STOPWORDS and len(w) > 3]
    word_freq = Counter(words)

    # Also extract bigrams
    bigrams = []
    for i in range(len(words) - 1):
        bg = words[i] + ' ' + words[i+1]
        if words[i] not in STOPWORDS and words[i+1] not in STOPWORDS:
            bigrams.append(bg)
    bigram_freq = Counter(bigrams)

    # Score: unigrams
    scored = [(w, f * (1 + len(w)/10)) for w, f in word_freq.most_common(50)]
    # Add bigrams with boost
    scored += [(bg, f * 2.0) for bg, f in bigram_freq.most_common(30)]

    scored.sort(key=lambda x: x[1], reverse=True)
    seen = set()
    result = []
    for w, _ in scored:
        if w not in seen:
            seen.add(w)
            result.append(w)
        if len(result) >= top_n:
            break
    return result


# ══════════════════════════════════════════════════════════════
#  SECTION SCORING
# ══════════════════════════════════════════════════════════════

def score_section(heading: str, content: str, idx: int, total: int, global_keywords: list) -> float:
    score = 0.0
    heading_lower = heading.lower()
    content_lower = content.lower()
    words = content.split()

    # 1. Position bonus (not first, not last)
    pos = idx / max(total - 1, 1)
    score += 0.25 if 0.1 < pos < 0.85 else 0.05

    # 2. Heading keywords
    important_words = [
        'algorithm','architecture','design','model','system','method','process',
        'technique','concept','principle','theory','analysis','implementation',
        'overview','fundamental','basic','core','key','critical','essential',
        'security','network','database','memory','structure','function','class',
        'protocol','layer','service','interface','type','operation','management',
        'scheduling','synchronization','deadlock','virtual','file','input','output',
        'software','hardware','lifecycle','testing','requirement','specification'
    ]
    for w in important_words:
        if w in heading_lower:
            score += 0.2
            break

    # 3. Keyword density
    hits = sum(1 for kw in global_keywords[:20] if kw in content_lower)
    score += min(0.25, hits * 0.015)

    # 4. Content length
    if len(words) > 300:
        score += 0.2
    elif len(words) > 100:
        score += 0.1

    # 5. Definition/explanation patterns
    patterns = [r'\bdefined as\b', r'\brefers to\b', r'\bconsists of\b',
                r'\btypes of\b', r'\bfollowing\b', r'\bsteps\b', r'\bexample\b',
                r'\badvantages\b', r'\bdisadvantages\b', r'\bproperties\b']
    for p in patterns:
        if re.search(p, content_lower):
            score += 0.04

    return min(1.0, score)


# ══════════════════════════════════════════════════════════════
#  EXPLANATION & KEY POINTS
# ══════════════════════════════════════════════════════════════

def generate_explanation(heading: str, content: str) -> str:
    sentences = re.split(r'(?<=[.!?])\s+', content)
    good = [s.strip() for s in sentences if 40 < len(s.strip()) < 250][:2]
    if good:
        result = ' '.join(good)
    else:
        result = f"This section covers important concepts related to {heading}."
    return result[:300] + ('...' if len(result) > 300 else '')


def extract_key_points(content: str, keywords: list) -> list:
    sentences = re.split(r'(?<=[.!?])\s+', content)
    scored = []
    for s in sentences:
        s = s.strip()
        if 30 < len(s) < 200:
            hits = sum(1 for kw in keywords[:10] if kw.lower() in s.lower())
            if hits > 0:
                scored.append((hits, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    points = [s[:150] + ('...' if len(s) > 150 else '') for _, s in scored[:5]]
    if not points:
        points = [f"Understand the key concepts of {kw}" for kw in keywords[:3]]
    return points[:5]


def clean_heading(heading: str) -> str:
    heading = re.sub(r'^\d+[\.\)]\s*', '', heading).strip()
    return (heading[:60] + '...') if len(heading) > 60 else heading or "General Topic"


# ══════════════════════════════════════════════════════════════
#  NORMALIZE SCORES
# ══════════════════════════════════════════════════════════════

def normalize_scores(topics: list) -> list:
    if not topics:
        return topics
    raw = [t["importance_score"] for t in topics]
    mn, mx = min(raw), max(raw)
    if mx == mn:
        for i, t in enumerate(topics):
            t["importance_score"] = max(1, 10 - i)
            t["priority"] = "High" if t["importance_score"] >= 8 else "Medium" if t["importance_score"] >= 5 else "Low"
        return topics
    for t in topics:
        n = round(((t["importance_score"] - mn) / (mx - mn)) * 9 + 1)
        t["importance_score"] = max(1, min(10, n))
        t["priority"] = "High" if t["importance_score"] >= 8 else "Medium" if t["importance_score"] >= 5 else "Low"
    return topics


# ══════════════════════════════════════════════════════════════
#  MAIN EXTRACTION FUNCTION
# ══════════════════════════════════════════════════════════════

def extract_topics_local(document_text: str) -> list:
    """
    Extract and rank topics from document — no API, fully offline.
    """
    if len(document_text.strip()) < 100:
        raise ValueError("Document too short.")

    sections = split_into_sections(document_text)
    if len(sections) <= 2:
        sections = chunk_text(document_text)

    global_keywords = extract_keywords(document_text, top_n=40)
    total = len(sections)
    topics = []

    for idx, section in enumerate(sections):
        heading = section["heading"].strip()
        content = section["content"].strip()
        if len(content) < 50:
            continue

        local_kws = extract_keywords(content, top_n=15)
        raw_score = score_section(heading, content, idx, total, global_keywords)
        importance_score = max(1, min(10, round(raw_score * 10)))
        priority = "High" if importance_score >= 8 else "Medium" if importance_score >= 5 else "Low"
        word_count = len(content.split())
        estimated_hours = max(1, min(8, math.ceil(word_count / 500)))

        topics.append({
            "topic": clean_heading(heading),
            "importance_score": importance_score,
            "priority": priority,
            "explanation": generate_explanation(heading, content),
            "estimated_hours": estimated_hours,
            "key_points": extract_key_points(content, local_kws),
            "word_count": word_count
        })

    topics = normalize_scores(topics)
    topics.sort(key=lambda x: x["importance_score"], reverse=True)
    return topics[:15]


# ══════════════════════════════════════════════════════════════
#  SLIDING WINDOW FILTER
# ══════════════════════════════════════════════════════════════

def filter_topics_by_days(topics: list, days_left: int, total_days: int = 30) -> dict:
    sorted_topics = sorted(topics, key=lambda x: x.get("importance_score", 0), reverse=True)
    total = len(sorted_topics)

    if days_left >= 20:
        filtered = sorted_topics
        mode = "Full Study Mode"
        advice = "You have plenty of time! Cover all topics thoroughly and do practice questions."
    elif days_left >= 10:
        filtered = [t for t in sorted_topics if t.get("priority") in ("High", "Medium")]
        mode = "Focused Study Mode"
        advice = "Focus on High and Medium priority topics. Skip Low priority unless time allows."
    elif days_left >= 4:
        high = [t for t in sorted_topics if t.get("priority") == "High"]
        medium = [t for t in sorted_topics if t.get("priority") == "Medium"][:2]
        filtered = high + medium
        mode = "Priority Mode"
        advice = "Concentrate on High priority topics. Skim top Medium topics if possible."
    else:
        filtered = [t for t in sorted_topics if t.get("priority") == "High"][:5]
        if not filtered:
            filtered = sorted_topics[:3]
        mode = "Crisis Mode 🚨"
        advice = "Only the most critical topics! Memorize key points only. Do NOT start new topics."

    for topic in filtered:
        topic["days_context"] = _get_day_context(topic, days_left)

    return {
        "topics": filtered,
        "mode": mode,
        "advice": advice,
        "days_left": days_left,
        "topics_shown": len(filtered),
        "topics_total": total
    }


def _get_day_context(topic: dict, days_left: int) -> str:
    hours = topic.get("estimated_hours", 2)
    if days_left >= 10:
        return f"Allocate ~{hours} hours. Read thoroughly and take notes."
    elif days_left >= 4:
        return f"Spend ~{min(hours, 3)} focused hours. Use key points only."
    else:
        return f"Quick revision: 30-45 mins max. Memorize key points only."


# ══════════════════════════════════════════════════════════════
#  CONCEPT DEPENDENCY STRUCTURE
# ══════════════════════════════════════════════════════════════

# Words that signal a concept is foundational / introductory
FOUNDATIONAL_SIGNALS = {
    'introduction','overview','basic','fundamental','concept','definition',
    'what is','meaning','background','history','origin','principle','theory',
    'basics','foundation','elementary','primary','intro','getting started'
}

# Words that signal advanced / complex content
ADVANCED_SIGNALS = {
    'advanced','complex','optimization','implementation','integration','architecture',
    'design pattern','algorithm','performance','security','distributed','concurrent',
    'synchronization','deadlock','virtualization','scheduling','management',
    'analysis','evaluation','comparison','trade-off','case study','application'
}

# Dependency trigger words — if section B's content mentions section A's heading words,
# B depends on A
DEPENDENCY_CONNECTORS = [
    'requires', 'needs', 'based on', 'builds on', 'extends', 'uses',
    'depends on', 'after understanding', 'prerequisite', 'assume knowledge',
    'recall', 'previously', 'as discussed', 'from above', 'following'
]


def classify_concept_level(heading: str, content: str, idx: int, total: int) -> str:
    """Classify concept as Foundational, Intermediate, or Advanced."""
    h = heading.lower()
    c = content.lower()
    pos = idx / max(total - 1, 1)

    # Check foundational signals
    if any(sig in h for sig in FOUNDATIONAL_SIGNALS):
        return "Foundational"
    if pos < 0.25:
        return "Foundational"

    # Check advanced signals
    if any(sig in h for sig in ADVANCED_SIGNALS):
        return "Advanced"
    if pos > 0.75:
        return "Advanced"

    return "Intermediate"


def find_dependencies(concepts: list) -> list:
    """
    For each concept, find which earlier concepts it depends on
    by checking keyword overlap between headings and content.
    """
    for i, concept in enumerate(concepts):
        deps = []
        c_content = concept["content"].lower()
        c_heading_words = set(re.sub(r'[^\w\s]', '', concept["name"].lower()).split()) - STOPWORDS

        for j, other in enumerate(concepts):
            if i == j:
                continue
            # Only look at earlier concepts (by document order)
            if other["doc_order"] >= concept["doc_order"]:
                continue

            other_heading_words = set(
                re.sub(r'[^\w\s]', '', other["name"].lower()).split()
            ) - STOPWORDS

            # Check if other's heading words appear in this concept's content
            overlap = other_heading_words & set(c_content.split())
            if len(overlap) >= 1 and len(other_heading_words) > 0:
                overlap_ratio = len(overlap) / len(other_heading_words)
                if overlap_ratio >= 0.3:
                    deps.append(other["name"])

            # Also check dependency connector phrases
            for connector in DEPENDENCY_CONNECTORS:
                if connector in c_content:
                    # If connector found and other concept's name is nearby
                    if any(w in c_content for w in other_heading_words if len(w) > 4):
                        if other["name"] not in deps:
                            deps.append(other["name"])
                        break

        concept["depends_on"] = deps[:3]  # Max 3 dependencies per concept
    return concepts


def build_dependency_structure(document_text: str, topics: list) -> dict:
    """
    Build a full Concept Dependency Structure from document text and extracted topics.
    Returns structured data with foundational, intermediate, advanced concepts
    and a recommended learning sequence.
    """
    sections = split_into_sections(document_text)
    if len(sections) <= 2:
        sections = chunk_text(document_text)

    total = len(sections)

    # Build concept list from topics (already extracted and ranked)
    topic_names = {t["topic"].lower(): t for t in topics}

    concepts = []
    for idx, section in enumerate(sections[:20]):  # Max 20 sections
        heading = clean_heading(section["heading"])
        content = section["content"]
        if len(content) < 40:
            continue

        level = classify_concept_level(heading, content, idx, total)
        local_kws = extract_keywords(content, top_n=8)

        # Get importance from topics if available
        matched_topic = topic_names.get(heading.lower())
        importance = matched_topic["importance_score"] if matched_topic else 5

        # Build why_it_matters from content
        sentences = re.split(r'(?<=[.!?])\s+', content)
        why = next((s.strip() for s in sentences if 30 < len(s.strip()) < 200), f"Core concept in this subject.")
        if len(why) > 180:
            why = why[:180] + '...'

        concepts.append({
            "name": heading,
            "level": level,
            "doc_order": idx,
            "importance": importance,
            "why_it_matters": why,
            "key_terms": local_kws[:5],
            "content": content,
            "depends_on": []
        })

    # Find dependencies between concepts
    concepts = find_dependencies(concepts)

    # Group by level
    foundational = [c for c in concepts if c["level"] == "Foundational"]
    intermediate = [c for c in concepts if c["level"] == "Intermediate"]
    advanced = [c for c in concepts if c["level"] == "Advanced"]

    # Sort each group by document order
    foundational.sort(key=lambda x: x["doc_order"])
    intermediate.sort(key=lambda x: x["doc_order"])
    advanced.sort(key=lambda x: x["importance"], reverse=True)

    # Build recommended learning sequence
    sequence = (
        [c["name"] for c in foundational] +
        [c["name"] for c in intermediate] +
        [c["name"] for c in advanced]
    )

    # Generate subject overview from first section
    first_content = sections[0]["content"] if sections else ""
    overview_sentences = re.split(r'(?<=[.!?])\s+', first_content)
    overview = ' '.join(
        s.strip() for s in overview_sentences[:3] if len(s.strip()) > 30
    )[:400] or "This document covers a structured set of concepts that build upon each other progressively."

    # Clean concepts for output (remove raw content)
    def clean_concept(c):
        return {
            "name": c["name"],
            "level": c["level"],
            "importance": c["importance"],
            "why_it_matters": c["why_it_matters"],
            "key_terms": c["key_terms"],
            "depends_on": c["depends_on"]
        }

    return {
        "overview": overview,
        "foundational": [clean_concept(c) for c in foundational],
        "intermediate": [clean_concept(c) for c in intermediate],
        "advanced": [clean_concept(c) for c in advanced],
        "learning_sequence": sequence,
        "total_concepts": len(concepts)
    }