"""
Quiz Routes — Groq AI powered with smart token management
  POST /generate/<doc_id>   Generate quiz via Groq (token-safe)
  GET  /list                List user's quizzes
  GET  /<quiz_id>           Get quiz (no answers)
  POST /submit              Submit + grade + get AI explanations
  GET  /attempts            List attempts
  GET  /attempt/<id>        Get attempt detail
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime, timedelta
import os, json, uuid, requests, logging, traceback
from collections import defaultdict

logger = logging.getLogger(__name__)
quiz_bp = Blueprint("quiz", __name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.1-8b-instant"

# ── Token budget constants ─────────────────────────────────────
# Groq free tier: ~6000 tokens per request safe limit
# We split budget: ~2500 for generation, ~2000 for explanations
MAX_DOC_CHARS_QUIZ   = 3500   # doc text sent to Groq for generation (~875 tokens)
MAX_DOC_CHARS_EXPL   = 2000   # doc snippet for explanation context  (~500 tokens)
MAX_GEN_TOKENS       = 1800   # Groq output tokens for quiz generation
MAX_EXPL_TOKENS      = 1200   # Groq output tokens for explanations
MAX_MCQ              = 8      # Cap MCQ to stay in budget
MAX_FIB              = 4      # Cap fill-in-blank
MAX_DESC             = 0      # Skip descriptive — too many tokens


def get_db():
    from app import mongo
    return mongo.db


def _groq_key():
    return os.getenv("GROQ_API_KEY", "").strip()


def _groq_headers():
    return {"Authorization": f"Bearer {_groq_key()}", "Content-Type": "application/json"}


def _clean_json(raw):
    raw = raw.strip()
    # Handle illegal backslashes
    import re
    raw = re.sub(r'\\(?![nrtbf"\\/u])', r'\\\\', raw)

    # Aggressively isolate the first JSON object/array
    start = raw.find('{')
    start_arr = raw.find('[')
    if start == -1 or (start_arr != -1 and start_arr < start):
        start = start_arr
    
    if start != -1:
        try:
            import json
            decoder = json.JSONDecoder()
            _, idx = decoder.raw_decode(raw[start:])
            return raw[start:start+idx]
        except:
            # Fallback to rfind if raw_decode fails
            end = raw.rfind('}' if raw[start] == '{' else ']')
            if end != -1: return raw[start:end+1]
            
    return raw.strip().rstrip("`").strip()


def _groq_call(messages, model=None, max_tokens=1800, temp=0.3):
    key = _groq_key()
    if not key:
        raise RuntimeError("GROQ_API_KEY not set in .env")
    
    target_model = model if model else GROQ_MODEL
    
    r = requests.post(
        GROQ_API_URL,
        headers=_groq_headers(),
        json={"model": target_model, "messages": messages,
              "max_tokens": max_tokens, "temperature": temp},
        timeout=60,
    )
    if not r.ok:
        try: msg = r.json().get("error", {}).get("message", r.text)
        except: msg = r.text
        raise RuntimeError(f"Groq {r.status_code}: {msg}")
    return r.json()["choices"][0]["message"]["content"]


# ══════════════════════════════════════════════════════════════
#  QUIZ GENERATION PROMPT  (token-efficient)
# ══════════════════════════════════════════════════════════════

def _build_gen_prompt(text, n_mcq, n_fib, difficulty, is_topic=False):
    system = f"""You are a quiz generator. Generate a quiz.
Mode: {'Topic-based (use your own knowledge)' if is_topic else 'Document-based (use provided text)'}
Difficulty: {difficulty}
MCQ questions: {n_mcq}

Respond ONLY with valid JSON. No markdown. Structure:
{{
  "questions": [
    {{
      "id": "q1",
      "type": "mcq",
      "topic": "Concept Name",
      "question": "Question text?",
      "options": ["A", "B", "C", "D"],
      "correct_answer": "Option text",
      "explanation": "Brief rationale."
    }}
  ]
}}

Rules:
- MCQ must have exactly 4 options.
- correct_answer for MCQ MUST be the EXACT text string from the 'options' array.
- topic should be 1-3 words representing the specific concept being tested.
- Variety: Shuffled concepts, avoid repetition.
- Difficulty {difficulty}: {'simple recall' if difficulty=='easy' else 'understanding and application' if difficulty=='medium' else 'analysis and synthesis'}"""

    user_content = f"Topic: {text}" if is_topic else f"Document Text:\n{text[:MAX_DOC_CHARS_QUIZ]}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{user_content}\n\nGenerate the quiz JSON now."}
    ]


# ══════════════════════════════════════════════════════════════
#  EXPLANATION PROMPT  (token-efficient, batched)
# ══════════════════════════════════════════════════════════════
def _build_explain_prompt(wrong_answers, doc_snippet, difficulty):
    """
    Generate explanations only for WRONG answers to save tokens.
    Batched in one call.
    """
    q_list = []
    for i, w in enumerate(wrong_answers):
        q_list.append(
            f"Q{i+1}: {w['question']}\n"
            f"Student answered: {w['user_answer']}\n"
            f"Correct answer: {w['correct_answer']}"
        )

    questions_text = "\n\n".join(q_list)

    system = """You are a study tutor. For each wrong answer, give a SHORT explanation (max 2 sentences).
Respond ONLY with valid JSON. No markdown. Structure:
{"explanations": [{"question_id": "q1", "explanation": "2 sentence max explanation"}]}"""

    user = f"Document context:\n{doc_snippet[:MAX_DOC_CHARS_EXPL]}\n\nWrong answers to explain:\n{questions_text}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user}
    ]


# ══════════════════════════════════════════════════════════════
#  LOCAL FALLBACK GENERATOR (no API needed)
# ══════════════════════════════════════════════════════════════
def _generate_local_fallback(text, n_mcq, n_fib, difficulty):
    """
    Simple local quiz generator used when:
    - Groq API fails
    - Token budget exceeded
    Returns same format as Groq output.
    """
    # If text is too short (e.g. just a topic), provide some context to help the generator
    if len(text.strip()) < 50:
        text = f"General information and fundamental concepts about {text}. " * 10

    from ml_models.quiz_generator import generate_quiz
    questions = generate_quiz(text, n_mcq=n_mcq, n_fib=n_fib, n_desc=0, difficulty=difficulty)
    # Normalize IDs
    for i, q in enumerate(questions):
        if not q.get("id"):
            q["id"] = f"q{i+1}"
    return questions


# ══════════════════════════════════════════════════════════════
#  ROUTE 1 — Generate Quiz (Groq + local fallback)
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/generate/<doc_id>", methods=["POST"])
@jwt_required()
def generate(doc_id):
    user_id = get_jwt_identity()
    db      = get_db()
    body    = request.get_json(silent=True) or {}
    n_mcq   = min(int(body.get("n_mcq", 5)), 10)
    n_fib   = 0
    difficulty = body.get("difficulty", "medium")

    is_topic = (doc_id == "topic")
    if is_topic:
        text = body.get("topic", "General Knowledge")
    else:
        doc = db.documents.find_one({"_id": ObjectId(doc_id), "user_id": user_id})
        if not doc:
            return jsonify({"error": "Document not found"}), 404
        text = doc.get("content_text", "")

    questions  = []
    source     = "groq"

    # ── Try Groq first ──────────────────────────────────────
    if _groq_key():
        try:
            # Randomly sample the text if it's very long and NOT a topic gen
            sample_text = text
            if not is_topic and len(text) > MAX_DOC_CHARS_QUIZ * 2:
                import random
                start = random.randint(0, len(text) - MAX_DOC_CHARS_QUIZ)
                sample_text = text[start : start + MAX_DOC_CHARS_QUIZ]
            elif not is_topic:
                sample_text = text[:MAX_DOC_CHARS_QUIZ]

            import random
            salt = random.randint(1000, 9999)
            msgs = _build_gen_prompt(sample_text, n_mcq, n_fib, difficulty, is_topic=is_topic)
            # Add salt to user prompt to force variety
            msgs[-1]["content"] += f"\n\nRandom Factor: {salt}. Focus on different concepts than before."
            
            # Higher temperature (0.7) for more variety in question generation
            raw  = _groq_call(msgs, max_tokens=MAX_GEN_TOKENS, temp=0.8)
            parsed = json.loads(_clean_json(raw))
            questions = parsed.get("questions", [])
            # Filter out any null or malformed entries from Groq
            questions = [q for q in questions if q and isinstance(q, dict) and q.get("question")]

            # Validate and fix IDs
            for i, q in enumerate(questions):
                if not q.get("id"): q["id"] = f"q{i+1}"
                if q.get("type") == "mcq" and len(q.get("options", [])) != 4:
                    q["options"] = (q.get("options", []) + ["Option A","Option B","Option C","Option D"])[:4]

        except json.JSONDecodeError:
            logger.warning("Groq returned invalid JSON — using local fallback")
            questions = _generate_local_fallback(text, n_mcq, n_fib, difficulty)
            source = "local"
        except RuntimeError as e:
            logger.warning("Groq error (%s) — using local fallback", e)
            questions = _generate_local_fallback(text, n_mcq, n_fib, difficulty)
            source = "local"
        except Exception as e:
            logger.error("Quiz generation error: %s", e)
            questions = _generate_local_fallback(text, n_mcq, n_fib, difficulty)
            source = "local"
    else:
        questions = _generate_local_fallback(text, n_mcq, n_fib, difficulty)
        source = "local"

    if not questions:
        return jsonify({"error": "Could not generate questions from this document. Try a longer document."}), 422

    doc_name = doc.get('original_name', 'Document') if (not is_topic and 'doc' in locals() and doc) else 'Topic Quiz'
    quiz = {
        "user_id":      user_id,
        "document_id":  str(doc_id) if not is_topic else None,
        "doc_text":     text[:MAX_DOC_CHARS_EXPL] if not is_topic else "",
        "title":        f"Quiz: {text[:50]}" if is_topic else f"Quiz: {doc_name}",
        "questions":    questions,
        "difficulty":   difficulty,
        "source":       source,
        "created_at":   datetime.utcnow(),
    }
    res       = db.quizzes.insert_one(quiz)
    quiz["_id"] = str(res.inserted_id)

    return jsonify({
        "message": f"Quiz generated ({source})",
        "quiz":    quiz,
        "source":  source,
        "n_questions": len(questions)
    }), 201


# ══════════════════════════════════════════════════════════════
#  ROUTE 2 — List Quizzes
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/list", methods=["GET"])
@jwt_required()
def list_quizzes():
    user_id = get_jwt_identity()
    db      = get_db()
    quizzes = list(db.quizzes.find(
        {"user_id": user_id},
        {"questions": 0, "doc_text": 0}
    ))
    for q in quizzes:
        q["_id"] = str(q["_id"])
    return jsonify({"quizzes": quizzes}), 200


# ══════════════════════════════════════════════════════════════
#  ROUTE 3 — Get Quiz (strip answers for taking)
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/<quiz_id>", methods=["GET"])
@jwt_required()
def get_quiz(quiz_id):
    user_id = get_jwt_identity()
    db      = get_db()
    quiz    = db.quizzes.find_one({"_id": ObjectId(quiz_id), "user_id": user_id})
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404

    show_answers = request.args.get("show_answers", "false").lower() == "true"
    questions = []
    for q in quiz.get("questions", []):
        q_copy = dict(q)
        if not show_answers:
            q_copy.pop("correct_answer", None)
            q_copy.pop("explanation", None)
        questions.append(q_copy)

    quiz["_id"]       = str(quiz["_id"])
    quiz["questions"] = questions
    quiz.pop("doc_text", None)
    return jsonify(quiz), 200


# ══════════════════════════════════════════════════════════════
#  ROUTE 4 — Submit Quiz (grade + AI explanations for wrong)
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/submit", methods=["POST"])
@jwt_required()
def submit():
    user_id = get_jwt_identity()
    data    = request.get_json()
    quiz_id = data.get("quiz_id")
    answers = data.get("answers", [])
    time_s  = data.get("time_taken_seconds", 0)
    emotion_data = data.get("emotion_data", {})

    if not quiz_id or not answers:
        return jsonify({"error": "quiz_id and answers required"}), 400

    db   = get_db()
    quiz = db.quizzes.find_one({"_id": ObjectId(quiz_id)})
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404

    # ── Grade answers ──────────────────────────────────────
    q_map  = {str(q["id"]): q for q in quiz.get("questions", [])}
    graded = []
    score  = 0
    wrong_for_explanation = []

    for ans in answers:
        qid      = str(ans.get("question_id"))
        q        = q_map.get(qid, {})
        q_type   = q.get("type", "")
        correct  = str(q.get("correct_answer", "")).strip()
        user_ans = str(ans.get("user_answer", "")).strip()

        # Priority 1: Use frontend evaluation if provided (requested by user)
        is_correct = ans.get("is_correct")
        
        if is_correct is None:
            # Fallback to backend logic if flag is missing
            is_correct = False
            if q_type != "descriptive":
                # Robust comparison logic matching frontend heuristics
                clean_user = str(user_ans).strip().lower()
                clean_corr = str(correct).strip().lower()
                
                # 1. Direct Match
                if clean_user == clean_corr:
                    is_correct = True
                # 2. Heuristic: AI might include "A. Option" as correct_answer
                elif len(clean_corr) > 2 and (clean_corr[1] == "." or clean_corr[2] == "."):
                    if clean_user in clean_corr:
                        is_correct = True
                # 3. Heuristic: User answer is part of the correct string or vice versa
                elif clean_user and (clean_user in clean_corr or clean_corr in clean_user):
                    is_correct = True
        
        if is_correct: score += 1

        # Use stored explanation (from Groq generation) if available
        stored_expl = q.get("explanation", "")

        g = {
            "question_id":   qid,
            "question":      q.get("question", ""),
            "type":          q_type,
            "user_answer":   user_ans,
            "correct_answer": correct,
            "is_correct":    is_correct,
            "explanation":   stored_expl,  # will be enriched for wrong answers
        }
        graded.append(g)

        # Collect wrong answers for AI explanation
        if not is_correct and q_type != "descriptive":
            wrong_for_explanation.append({
                "question_id":   qid,
                "question":      q.get("question", ""),
                "user_answer":   user_ans,
                "correct_answer": correct,
            })

    # ── AI Explanations for wrong answers only ─────────────
    # Only call Groq if there are wrong answers AND within token budget
    # Cap at 5 wrong answers to stay within 6k tokens
    doc_snippet = quiz.get("doc_text", "")
    if wrong_for_explanation and _groq_key():
        try:
            to_explain = wrong_for_explanation[:5]  # max 5 to stay in budget
            msgs = _build_explain_prompt(to_explain, doc_snippet, quiz.get("difficulty","medium"))
            raw  = _groq_call(msgs, max_tokens=MAX_EXPL_TOKENS, temp=0.3)
            parsed = json.loads(_clean_json(raw))

            # Map explanations back to graded answers
            expl_list = parsed.get("explanations", [])
            expl_map  = {}
            for i, e in enumerate(expl_list):
                # Match by position (Groq returns in order)
                if i < len(to_explain):
                    expl_map[to_explain[i]["question_id"]] = e.get("explanation", "")

            for g in graded:
                if g["question_id"] in expl_map and expl_map[g["question_id"]]:
                    g["explanation"] = expl_map[g["question_id"]]

        except Exception as e:
            logger.warning("Explanation generation failed (%s) — using stored explanations", e)

    # ── Calculate results ──────────────────────────────────
    gradable = [g for g in graded if g["type"] != "descriptive"]
    total    = len(gradable)
    score    = sum(1 for g in gradable if g["is_correct"])
    pct      = round((score / total) * 100, 2) if total else 0

    # Calculate Streak
    max_streak = 0
    current_streak = 0
    for g in gradable:
        if g["is_correct"]:
            current_streak += 1
            if current_streak > max_streak: max_streak = current_streak
        else:
            current_streak = 0

    # Calculate Speed & Difficulty Bonus
    avg_speed = time_s / total if total else 0
    diff = quiz.get("difficulty", "medium")
    diff_mult = 1.0 if diff == "easy" else 1.5 if diff == "medium" else 2.0
    
    # Speed Bonus: Higher if time per question < 8s
    speed_bonus = max(0, (8 - avg_speed) * 10) if avg_speed > 0 else 0
    
    # Final Skill Score Calculation
    # Factors: Accuracy (60%), Streak (20%), Speed (10%), Difficulty (10%)
    skill_score = round((pct * 10) + (max_streak * 50 * diff_mult) + speed_bonus)

    # Primary Topic extraction
    topics = [q.get("topic") for q in quiz.get("questions", []) if q.get("topic")]
    primary_topic = max(set(topics), key=topics.count) if topics else "General"

    # Performance feedback
    if pct >= 90:
        feedback_tag = "excellent"
        ai_feedback  = "🎉 Outstanding! You have an excellent grasp of this material."
    elif pct >= 75:
        feedback_tag = "good"
        ai_feedback  = "👍 Great job! You understand most of the material. Review the missed topics."
    elif pct >= 50:
        feedback_tag = "average"
        ai_feedback  = "📚 Fair performance. Focus on the topics you missed — they need more attention."
    else:
        feedback_tag = "needs_work"
        ai_feedback  = "⚠️ Needs more study. Review the explanations carefully and re-read the document."

    attempt = {
        "user_id":           user_id,
        "quiz_id":           ObjectId(quiz_id),
        "answers":           graded,
        "score":             score,
        "total_questions":   total,
        "percentage":        pct,
        "max_streak":        max_streak,
        "avg_speed":         round(avg_speed, 2),
        "skill_score":       skill_score,
        "difficulty":        diff,
        "topic":             primary_topic,
        "performance":       feedback_tag,
        "time_taken_seconds":time_s,
        "emotion_data":      emotion_data,
        "completed_at":      datetime.utcnow(),
    }
    res = db.quiz_attempts.insert_one(attempt)

    return jsonify({
        "message":        "Quiz submitted",
        "attempt_id":     str(res.inserted_id),
        "score":          score,
        "total":          total,
        "percentage":     pct,
        "skill_score":    skill_score,
        "max_streak":     max_streak,
        "performance":    feedback_tag,
        "ai_feedback":    ai_feedback,
        "graded_answers": graded,
    }), 200


# ══════════════════════════════════════════════════════════════
#  ROUTE 5 — List Attempts
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/attempts", methods=["GET"])
@jwt_required()
def list_attempts():
    user_id  = get_jwt_identity()
    db       = get_db()
    attempts = list(db.quiz_attempts.find(
        {"user_id": user_id},
        {"answers": 0},
        sort=[("completed_at", -1)],
        limit=50
    ))
    for a in attempts:
        a["_id"]     = str(a["_id"])
        a["quiz_id"] = str(a["quiz_id"])
    return jsonify({"attempts": attempts}), 200


# ══════════════════════════════════════════════════════════════
#  ROUTE 6 — Get Attempt Detail
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/attempt/<attempt_id>", methods=["GET"])
@jwt_required()
def get_attempt(attempt_id):
    user_id = get_jwt_identity()
    db      = get_db()
    attempt = db.quiz_attempts.find_one({"_id": ObjectId(attempt_id), "user_id": user_id})
    if not attempt:
        return jsonify({"error": "Attempt not found"}), 404
    attempt["_id"]     = str(attempt["_id"])
    attempt["quiz_id"] = str(attempt["quiz_id"])
    return jsonify(attempt), 200


# ══════════════════════════════════════════════════════════════
#  GEMINI helper (direct HTTP, no extra lib needed)
# ══════════════════════════════════════════════════════════════
def _gemini_call(prompt, max_tokens=800):
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    
    # Expanded model list and API versions for robustness
    models = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-1.5-flash-latest", "gemini-pro"]
    versions = ["v1", "v1beta"]
    
    last_err = ""
    for ver in versions:
        for m in models:
            try:
                url = f"https://generativelanguage.googleapis.com/{ver}/models/{m}:generateContent?key={api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.4},
                }
                r = requests.post(url, headers={"Content-Type": "application/json"},
                                  json=payload, timeout=30)
                if r.ok:
                    res_json = r.json()
                    if "candidates" in res_json and res_json["candidates"]:
                        return res_json["candidates"][0]["content"]["parts"][0]["text"]
                
                # Capture error for logging if all fail
                try:
                    err_data = r.json()
                    last_err = f"[{ver}/{m}] {err_data.get('error', {}).get('message', r.text)}"
                except:
                    last_err = f"[{ver}/{m}] {r.status_code}: {r.text}"
                    
            except Exception as e:
                last_err = f"[{ver}/{m}] Exception: {str(e)}"
            
    raise RuntimeError(f"Gemini All Models/Versions Failed. Last error: {last_err[:300]}")


# ══════════════════════════════════════════════════════════════
#  ROUTE 7 — Battle Mode Start  (Groq, ≤1800 tokens out)
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/battle/start", methods=["POST"])
@jwt_required()
def battle_start():
    data     = request.get_json() or {}
    topic    = data.get("topic", "General Knowledge")
    doc_text = data.get("doc_text", "")[:2500]

    system = (
        "You are a battle-quiz generator. Generate exactly 10 MCQ questions. "
        "Mix: 3 easy, 4 medium, 3 hard. Each has exactly 4 options. "
        "IMPORTANT: 'correct_answer' MUST be the EXACT string matching one of the options. "
        "Respond ONLY with valid JSON — no markdown:\n"
        '{"questions":[{"id":"bq1","question":"What is 2+2?","options":["3","4","5","6"],'
        '"correct_answer":"4","difficulty":"easy","topic":"Math"}]}'
    )
    user_msg = (f"Document context:\n{doc_text}\nTopic: {topic}"
                if doc_text else f"Topic: {topic}")
    try:
        raw  = _groq_call([{"role":"system","content":system},
                           {"role":"user","content":user_msg}],
                          max_tokens=2500, temp=0.5)
        data_out = json.loads(_clean_json(raw))
        
        # Robust parsing: Handle if data_out is a list or contains 'questions' key
        if isinstance(data_out, list):
            qs = data_out
        else:
            qs = data_out.get("questions", [])

        if not qs and isinstance(data_out, dict):
            # Try to find any list in the dict if 'questions' is missing
            for val in data_out.values():
                if isinstance(val, list):
                    qs = val
                    break

        for i, q in enumerate(qs):
            if not q.get("id"): q["id"] = f"bq{i+1}"
            if len(q.get("options", [])) != 4:
                q["options"] = (q.get("options", []) +
                                ["Option A","Option B","Option C","Option D"])[:4]
        # Save battle quiz to DB so it can be submitted/graded
        db = get_db()
        user_id = get_jwt_identity()
        quiz_doc = {
            "user_id": user_id,
            "topic": topic,
            "questions": qs,
            "created_at": datetime.utcnow(),
            "mode": "battle",
            "difficulty": "mixed"
        }
        res = db.quizzes.insert_one(quiz_doc)
        
        return jsonify({
            "quiz_id": str(res.inserted_id),
            "questions": qs, 
            "total": len(qs)
        }), 200
    except Exception as e:
        logger.error("battle_start: %s", e)
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  ROUTE 8 — Adaptive Question  (Groq, ≤400 tokens out)
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/adaptive", methods=["POST"])
@jwt_required()
def adaptive_question():
    data       = request.get_json() or {}
    topic      = data.get("topic", "")
    difficulty = data.get("difficulty", "medium")
    exclude    = ", ".join(data.get("exclude", [])[:5]) or "none"
    doc_text   = data.get("doc_text", "")[:1500]

    system = (
        f"Generate ONE MCQ about '{topic}' at {difficulty} difficulty. "
        f"Do NOT repeat: {exclude}. "
        "Respond ONLY with valid JSON — no markdown:\n"
        '{"id":"aq1","question":"...","options":["A","B","C","D"],'
        f'"correct_answer":"A","explanation":"1-sentence why.","difficulty":"{difficulty}","topic":"{topic}"}}'
    )
    user_msg = doc_text or f"Generate a {difficulty} question about: {topic}"
    try:
        raw = _groq_call([{"role":"system","content":system},
                          {"role":"user","content":user_msg}],
                         max_tokens=400, temp=0.6)
        q = json.loads(_clean_json(raw))
        if len(q.get("options", [])) != 4:
            q["options"] = (q.get("options", []) + ["A","B","C","D"])[:4]
        return jsonify(q), 200
    except Exception as e:
        logger.error("adaptive_question: %s", e)
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  ROUTE 9 — Deep Feedback  (Gemini, ≤1200 tokens out)
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/feedback", methods=["POST"])
@jwt_required()
def deep_feedback():
    wrong = (request.get_json() or {}).get("wrong_answers", [])[:5]
    if not wrong:
        return jsonify({"feedbacks": []}), 200

    blocks = "\n\n".join(
        f"Q: {w.get('question','')}\n"
        f"User answered: {w.get('user_answer','')}\n"
        f"Correct answer: {w.get('correct_answer','')}"
        for w in wrong
    )
    prompt = (
        "You are a patient tutor. For each wrong answer explain: "
        "(1) why the user's answer is incorrect, "
        "(2) why the correct answer is right, "
        "(3) a quick memory tip. Max 3 sentences per question.\n"
        "Respond ONLY with valid JSON:\n"
        '{"feedbacks":[{"why_wrong":"...","why_correct":"...","tip":"..."}]}\n\n'
        f"Wrong answers:\n{blocks}"
    )
    try:
        result  = _gemini_call(prompt, max_tokens=1200)
        parsed  = json.loads(_clean_json(result))
        return jsonify(parsed), 200
    except Exception as e:
        logger.error("deep_feedback: %s", e)
        fallback = [{"why_wrong": "Review carefully.", "why_correct": w.get("correct_answer",""),
                     "tip": "Re-read the relevant section."} for w in wrong]
        return jsonify({"feedbacks": fallback}), 200


# ══════════════════════════════════════════════════════════════
#  ROUTE 10 — Session Summary  (Gemini, ≤600 tokens out)
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/summary", methods=["POST"])
@jwt_required()
def session_summary():
    r      = (request.get_json() or {}).get("results", {})
    score  = r.get("score", 0)
    total  = r.get("total", 1)
    weak   = ", ".join(r.get("weak_topics", [])[:4]) or "none"
    strong = ", ".join(r.get("strong_topics", [])[:4]) or "none"
    pct    = round(score / total * 100) if total else 0

    prompt = (
        f"Student quiz result: {score}/{total} ({pct}%). "
        f"Strong: {strong}. Weak: {weak}.\n"
        "Give a personalized JSON summary:\n"
        '{"mastery_summary":"2 sentences","weak_areas":["t1","t2"],'
        '"next_steps":["step1","step2","step3"],"motivation":"1 sentence"}'
    )
    try:
        result = _gemini_call(prompt, max_tokens=600)
        return jsonify(json.loads(_clean_json(result))), 200
    except Exception as e:
        logger.error("session_summary: %s", e)
        return jsonify({
            "mastery_summary": f"You scored {pct}%. Keep practicing!",
            "weak_areas": r.get("weak_topics", [])[:3],
            "next_steps": ["Review incorrect answers", "Re-read the document", "Retry the quiz"],
            "motivation": "Every mistake is a step toward mastery!"
        }), 200


# ══════════════════════════════════════════════════════════════
#  ROUTE 11 — Fix Mistake Variant  (Groq, ≤500 tokens out)
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/fix_mistake", methods=["POST"])
@jwt_required()
def fix_mistake():
    d    = request.get_json() or {}
    orig = d.get("question", "")
    ans  = d.get("correct_answer", "")
    topic = d.get("topic", ans)
    import random
    salt = random.randint(1000, 9999)

    system = (
        f"Create ONE new MCQ that tests the SAME concept as this question "
        f"but with different wording. Original: '{orig}'. Concept: '{topic}'.\n"
        "Rules:\n"
        "- The correct answer MUST be scientifically/logically accurate.\n"
        "- Options must be plausible distractors.\n"
        "- Respond ONLY with valid JSON — no markdown.\n"
        'Structure: {"question":"...","options":["A","B","C","D"],"correct_answer":"Exact Option Text","explanation":"Brief why."}'
    )
    user_content = f"Generate a unique variant for: {orig}. Salt: {salt}"
    try:
        raw = _groq_call([{"role":"system","content":system},
                          {"role":"user","content":user_content}],
                         max_tokens=500, temp=0.8)
        q = json.loads(_clean_json(raw))
        if len(q.get("options", [])) != 4:
            q["options"] = (q.get("options", []) + ["A","B","C","D"])[:4]
        return jsonify(q), 200
    except Exception as e:
        logger.error("fix_mistake: %s", e)
        return jsonify({"error": "AI variant generation failed. Please try again."}), 500


# ══════════════════════════════════════════════════════════════
#  ROUTE 12 — Leaderboard  (DB only, no AI)
# ══════════════════════════════════════════════════════════════
# (Old leaderboard route removed to prevent conflict with new formula)



# ══════════════════════════════════════════════════════════════
#  ROUTE 13 — Personal Best  (DB only)
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/personal_best", methods=["GET"])
@jwt_required()
def personal_best():
    user_id = get_jwt_identity()
    db      = get_db()
    best = db.quiz_attempts.find_one({"user_id": user_id},
                                     sort=[("skill_score", -1)])
    last = db.quiz_attempts.find_one({"user_id": user_id},
                                     sort=[("completed_at", -1)])
    return jsonify({
        "best_score":      best.get("skill_score", 0) if best else 0,
        "best_percentage": best.get("percentage", 0)  if best else 0,
        "last_score":      last.get("skill_score", 0) if last else 0,
        "total_attempts":  db.quiz_attempts.count_documents({"user_id": user_id}),
    }), 200


# ══════════════════════════════════════════════════════════════
#  ROUTE 14 — Mastery Aggregation
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/mastery", methods=["GET"])
@jwt_required()
def get_mastery():
    user_id = get_jwt_identity()
    db      = get_db()
    
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$unwind": "$answers"},
        {"$group": {
            "_id":   "$topic",
            "correct": {"$sum": {"$cond": ["$answers.is_correct", 1, 0]}},
            "total":   {"$sum": 1}
        }},
        {"$sort": {"total": -1}}
    ]
    results = list(db.quiz_attempts.aggregate(pipeline))
    
    mastery = {}
    for r in results:
        topic = r["_id"] or "General"
        mastery[topic] = [r["correct"], r["total"]]
        
    return jsonify({"mastery": mastery}), 200


# ══════════════════════════════════════════════════════════════
#  ROUTE 15 — Specialized Quiz Leaderboard (New Formula)
# ══════════════════════════════════════════════════════════════
@quiz_bp.route("/leaderboard", methods=["GET"])
@jwt_required()
def quiz_leaderboard():
    db = get_db()
    current_user_id = get_jwt_identity()
    
    # Optional filters from frontend
    scope = request.args.get("scope", "global")
    topic_filter = request.args.get("topic")
    diff_filter  = request.args.get("difficulty")
    time_filter  = request.args.get("time", "all") 
    
    if scope == "personal":
        # Handle My History tab - Revert to simple history list
        query = {"user_id": current_user_id}
        if topic_filter and topic_filter != "All Topics":
            query["topic"] = topic_filter
        if diff_filter and diff_filter != "All Difficulties":
            query["difficulty"] = diff_filter.lower()
            
        rows = list(db.quiz_attempts.find(query, {"answers": 0}, sort=[("completed_at", -1)], limit=50))
        for r in rows:
            r["_id"] = str(r["_id"])
            if "completed_at" in r:
                r["completed_at"] = r["completed_at"].isoformat()
        return jsonify({
            "leaderboard": rows,
            "scope": "personal",
            "topics": sorted(db.quiz_attempts.distinct("topic"))
        }), 200

    # 1. Fetch Users
    users = list(db.users.find({}, {"username": 1, "profile.avatar": 1}))
    user_map = {str(u["_id"]): u for u in users}
    
    # 2. Prepare Query
    query = {"type": {"$ne": "assessment"}} # Specific to regular quizzes
    if topic_filter and topic_filter != "All Topics":
        query["topic"] = topic_filter
    if diff_filter and diff_filter != "All Difficulties":
        query["difficulty"] = diff_filter.lower()
        
    if time_filter == "7d":
        query["completed_at"] = {"$gte": datetime.utcnow() - timedelta(days=7)}
    elif time_filter == "30d":
        query["completed_at"] = {"$gte": datetime.utcnow() - timedelta(days=30)}

    # 3. Fetch All Relevant Attempts
    attempts = list(db.quiz_attempts.find(query, {
        "user_id": 1, "score": 1, "total_questions": 1, "topic": 1, "percentage": 1, "completed_at": 1
    }))
    
    # 4. Group by User
    user_attempts_grouped = defaultdict(list)
    for a in attempts:
        user_attempts_grouped[str(a["user_id"])].append(a)
        
    leaderboard_data = []
    for uid, u_attempts in user_attempts_grouped.items():
        if uid not in user_map: continue
        
        # --- Formula Components ---
        # accuracy = total right questions / total attempted questions
        total_right = sum(a.get("score", 0) for a in u_attempts)
        total_qs    = sum(a.get("total_questions", 0) for a in u_attempts)
        accuracy_val = (total_right / total_qs) if total_qs > 0 else 0
        
        # mastery = mastered_topics (avg > 80%) / total_topics
        topic_scores = defaultdict(list)
        for a in u_attempts:
            t = a.get("topic", "General")
            topic_scores[t].append(a.get("percentage", 0))
        
        mastered_count = sum(1 for t, s in topic_scores.items() if (sum(s)/len(s)) >= 80)
        mastery_val    = mastered_count / len(topic_scores) if topic_scores else 0
        
        # attempt_score = min(no. of attempts / 100, 1)
        attempt_count = len(u_attempts)
        attempt_score_val = min(attempt_count / 100, 1)
        
        # Streaks
        dates = sorted({a["completed_at"].date() for a in u_attempts if "completed_at" in a})
        best_streak = 0
        sum_streaks = 0
        if dates:
            streak_list = []
            curr = 1
            for i in range(1, len(dates)):
                if dates[i] == dates[i-1] + timedelta(days=1):
                    curr += 1
                else:
                    streak_list.append(curr)
                    curr = 1
            streak_list.append(curr)
            best_streak = max(streak_list)
            sum_streaks = sum(streak_list)
            
        current_streak_score_val = min(best_streak / 30, 1)
        total_streak_score_val   = min(sum_streaks / 200, 1)
        
        # --- Final Composite Formula ---
        # Skill Score = 100 * (0.35 * accuracy + 0.25 * mastery + 0.10 * attempt_score + 0.15 * current_streak_score + 0.15 * total_streak_score)
        skill_score = 100 * (
            0.35 * accuracy_val +
            0.25 * mastery_val +
            0.10 * attempt_score_val +
            0.15 * current_streak_score_val +
            0.15 * total_streak_score_val
        )
        
        u_info = user_map[uid]
        leaderboard_data.append({
            "user_id": uid,
            "username": u_info.get("username", "Unknown"),
            "is_me": (uid == current_user_id),
            "avg_accuracy": round(accuracy_val * 100, 1),
            "max_streak": best_streak,
            "total_correct": total_right,
            "total_questions": total_qs,
            "total_attempts": attempt_count,
            "best_skill_score": round(skill_score, 2),
            "score": round(skill_score, 2)
        })
        
    # Sort and rank
    leaderboard_data.sort(key=lambda x: x["score"], reverse=True)
    for i, entry in enumerate(leaderboard_data):
        entry["rank"] = i + 1
        
    # Topics for dropdown
    all_topics = db.quiz_attempts.distinct("topic")
        
    return jsonify({
        "leaderboard": leaderboard_data[:20],
        "my_rank": next((x["rank"] for x in leaderboard_data if x["user_id"] == current_user_id), None),
        "topics": sorted(all_topics),
        "scope": request.args.get("scope", "global")
    }), 200