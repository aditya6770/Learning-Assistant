"""
emotion_routes.py  —  Enhanced Emotion Intelligence System
Endpoints:
  POST /api/emotion/analyze          — analyze face frame + context signals
  POST /api/emotion/session/end      — save session summary
  POST /api/emotion/ai-insight       — Groq/DeepSeek AI coaching response
  POST /api/emotion/adapt            — get difficulty adaptation for quiz/qa/revision
  GET  /api/emotion/session-history  — past sessions for the user
  GET  /api/emotion/leaderboard      — emotion score leaderboard (optional)
"""
import os, base64, logging, json, time
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, Response, stream_with_context
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
import requests as req_lib

logger   = logging.getLogger(__name__)
emotion_bp = Blueprint("emotion", __name__)

GROQ_API_KEY     = os.getenv("GROQ_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
GROQ_URL         = "https://api.groq.com/openai/v1/chat/completions"
DS_URL           = "https://api.deepseek.com/v1/chat/completions"
GROQ_MODEL       = "llama-3.1-8b-instant"
DS_MODEL         = "deepseek-chat"

# Token budget constants (conservative to stay under limits)
GROQ_TOKEN_BUDGET = 800   # per AI insight call
DS_TOKEN_BUDGET   = 600   # per DeepSeek call

# ── Frustration Tracking ──
user_frustration_tracker = {}
user_puzzle_history = {}

def _check_frustration_duration(user_id, state):
    import time
    now = time.time()

    if user_id not in user_frustration_tracker:
        user_frustration_tracker[user_id] = {"start": None}

    tracker = user_frustration_tracker[user_id]

    if state == "frustrated":
        if tracker["start"] is None:
            tracker["start"] = now

        duration = now - tracker["start"]
        return duration >= 4   # 🔥 4 seconds condition

    else:
        tracker["start"] = None
        return False

def get_db():
    from app import mongo
    return mongo.db


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _groq_headers():
    return {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

def _ds_headers():
    return {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}

def filter_new_puzzles(user_id, puzzles):
    if user_id not in user_puzzle_history:
        user_puzzle_history[user_id] = set()

    new_puzzles = []

    for p in puzzles:
        if p["question"] not in user_puzzle_history[user_id]:
            new_puzzles.append(p)
            user_puzzle_history[user_id].add(p["question"])

    return new_puzzles

def _map_emotion_to_state(emotion: str, confidence: float) -> dict:
    """Map raw emotion label to learning state."""
    mapping = {
        "happy":     {"state": "engaged",   "score": 90, "color": "#10b981"},
        "neutral":   {"state": "focused",   "score": 70, "color": "#06b6d4"},
        "surprised": {"state": "curious",   "score": 75, "color": "#f59e0b"},
        "sad":       {"state": "frustrated","score": 35, "color": "#ef4444"},
        "angry":     {"state": "frustrated","score": 20, "color": "#ef4444"},
        "fear":      {"state": "anxious",   "score": 30, "color": "#f97316"},
        "disgusted": {"state": "bored",     "score": 25, "color": "#8b5cf6"},
        "unknown":   {"state": "unknown",   "score": 50, "color": "#64748b"},
    }
    result = mapping.get(emotion.lower(), mapping["unknown"]).copy()
    result["raw_emotion"]  = emotion
    result["confidence"]   = confidence
    return result

def _analyze_typing_pattern(typing_data: dict) -> dict:
    """Derive emotion cues from typing speed, backspaces, pauses."""
    wpm          = typing_data.get("wpm", 0)
    backspace_rt = typing_data.get("backspace_rate", 0)   # backspaces per word
    pause_count  = typing_data.get("pause_count", 0)       # pauses >3s
    idle_seconds = typing_data.get("idle_seconds", 0)

    cues = []
    if wpm < 10 and idle_seconds > 30:
        cues.append({"signal": "slow_typing_long_idle", "state": "confused", "weight": 0.7})
    if backspace_rt > 1.5:
        cues.append({"signal": "high_backspace_rate",   "state": "frustrated", "weight": 0.6})
    if wpm > 60:
        cues.append({"signal": "fast_typing",           "state": "engaged",    "weight": 0.5})
    if pause_count > 3:
        cues.append({"signal": "frequent_pauses",       "state": "confused",   "weight": 0.5})
    if idle_seconds > 120:
        cues.append({"signal": "extended_idle",         "state": "bored",      "weight": 0.8})
    return {"cues": cues}

def _analyze_quiz_performance(quiz_data: dict) -> dict:
    """Derive emotion cues from recent quiz performance."""
    wrong_streak    = quiz_data.get("wrong_streak", 0)
    avg_time_per_q  = quiz_data.get("avg_time_per_question", 0)
    accuracy        = quiz_data.get("recent_accuracy", 1.0)

    cues = []
    if wrong_streak >= 3:
        cues.append({"signal": "wrong_streak_3+", "state": "frustrated", "weight": 0.9})
    if avg_time_per_q > 45:
        cues.append({"signal": "slow_on_questions","state": "confused",   "weight": 0.7})
    if accuracy < 0.3:
        cues.append({"signal": "low_accuracy",     "state": "frustrated", "weight": 0.8})
    if accuracy > 0.9 and avg_time_per_q < 10:
        cues.append({"signal": "high_accuracy_fast","state": "bored",     "weight": 0.6})
    return {"cues": cues}

def _compute_composite_emotion(face_state: dict, typing_cues: list, quiz_cues: list) -> dict:
    """
    Weighted voting from three signal sources.
    Returns dominant state, composite score, and recommended difficulty delta.
    """
    state_votes = {}
    # Face (weight 0.5)
    fs = face_state.get("state", "unknown")
    state_votes[fs] = state_votes.get(fs, 0) + 0.8 * face_state.get("score", 50) / 100

    # Typing cues (weight 0.25 each cue)
    for c in typing_cues:
        s = c["state"]; w = c["weight"] * 0.05
        state_votes[s] = state_votes.get(s, 0) + w

    # Quiz cues (weight 0.35 each cue)
    for c in quiz_cues:
        s = c["state"]; w = c["weight"] * 0.05
        state_votes[s] = state_votes.get(s, 0) + w

    # Face priority override
    if face_state.get("confidence", 0) > 0.6:
        dominant = face_state.get("state", "focused")
    else:
        dominant = max(state_votes, key=state_votes.get) if state_votes else "focused"

    total_w  = sum(state_votes.values()) or 1
    confidence = round(state_votes.get(dominant, 0) / total_w * 100, 1)

    # Difficulty delta: -2 frustrated/anxious, -1 confused, 0 focused/unknown,
    #                   +1 engaged/curious, +2 bored
    delta_map = {
        "frustrated": -2, "anxious": -2, "confused": -1,
        "focused": 0, "unknown": 0, "engaged": 1, "curious": 1, "bored": 2
    }
    diff_delta = delta_map.get(dominant, 0)

    # Engagement score 0-100
    score_map = {
    "bored": 30, "frustrated": 25, "anxious": 35, "confused": 45,
    "unknown": 50, "focused": 70, "curious": 80, "engaged": 95
    }

   # base score from emotion
    eng_score = score_map.get(dominant, 50)

    # blend with real face attention
    face_score = face_state.get("score", 50)

    eng_score = int(0.7 * face_score + 0.3 * eng_score)

    # slight variation using confidence
    eng_score += int(confidence * 0.1)

    eng_score = max(10, min(100, eng_score))

    return {
        "dominant_state":  dominant,
        "confidence":      confidence,
        "state_votes":     state_votes,
        "difficulty_delta": diff_delta,
        "engagement_score": eng_score,
    }

def _get_motivation(state: str) -> str:
    messages = {
        "frustrated": "💪 You're struggling — that means you're growing! Take a breath and try again.",
        "confused":   "🤔 Confusion is the doorway to understanding. Break it down step by step.",
        "bored":      "⚡ Ready for a challenge? Let's crank up the intensity!",
        "anxious":    "😌 Relax — you know more than you think. Trust your preparation.",
        "focused":    "🎯 Great focus! You're in the zone. Keep it up!",
        "curious":    "🔍 Love the curiosity! Dive deeper — that's how mastery is built.",
        "engaged":    "🚀 You're absolutely killing it right now! Maximum engagement!",
        "unknown":    "📚 Stay consistent and the results will follow.",
    }
    return messages.get(state, messages["unknown"])

def generate_puzzle_ai():
    prompt = """
    Generate 3 different puzzles.

    Mix types:
    - number pattern
    - logical reasoning
    - riddle

    Return JSON array:
    [
      {
        "question": "...",
        "options": ["A","B","C","D"],
        "answer": "A",
        "hint": "..."
      }
    ]
    """

    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 400
    }

    try:
        r = req_lib.post(GROQ_URL, headers=_groq_headers(), json=payload)
        text = r.json()["choices"][0]["message"]["content"]
        return json.loads(text)

    except:
        return [
            {
                "question": "2, 6, 7, 21, 22, ?",
                "options": ["66", "44", "23", "42"],
                "answer": "66",
                "hint": "×3 then +1"
            },
            {
                "question": "What has keys but can't open locks?",
                "options": ["Piano", "Door", "Map", "Clock"],
                "answer": "Piano",
                "hint": "Musical"
            }
        ]
# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@emotion_bp.route("/analyze", methods=["POST"])
@jwt_required()
def analyze():
    """
    Enhanced analysis combining:
      - face frame (base64 JPEG)  → simulated face emotion
      - typing_data               → pattern analysis
      - quiz_data                 → performance cues
    Returns composite emotion state + adaptation recommendations.
    """
    user_id = get_jwt_identity()
    data    = request.get_json() or {}

    frame        = data.get("frame", "")           # base64 JPEG
    session_id   = data.get("session_id", "")
    typing_data  = data.get("typing_data", {})
    quiz_data    = data.get("quiz_data", {})

    # ── Simulated face emotion (real model would process `frame`) ──
    # Real ML-based emotion detection
    from ml_models.emotion_detector import analyze_frame
    det = analyze_frame(frame)

    raw_emotion = det.get("emotion", "unknown")
    face_confidence = det.get("confidence", 0.5)
    attention_score = det.get("attention_score", 0.5)

# KEEP THIS LINE
    face_state = _map_emotion_to_state(raw_emotion, face_confidence)

# Override score with real attention
    face_state["score"] = int(attention_score * 100)

    print("RAW EMOTION:", raw_emotion)
    print("FACE STATE:", face_state)

# handle no face detected
    if not det.get("face_detected", True):
        face_state["score"] = 10
    

    # ── Typing & quiz signal analysis ──
    typing_result = _analyze_typing_pattern(typing_data)
    quiz_result   = _analyze_quiz_performance(quiz_data)

    # ── Composite scoring ──
    composite = _compute_composite_emotion(
        face_state,
        typing_result["cues"],
        quiz_result["cues"]
    )

    # ── Special triggers ──
    triggers = []
    state = composite["dominant_state"]
    if _check_frustration_duration(user_id, state):
        puzzles = generate_puzzle_ai()
        puzzles = filter_new_puzzles(user_id, puzzles)

        triggers.append({
            "type": "puzzle",
            "action": "show_puzzle",
            "puzzles": puzzles   # ✅ array
        })
    if state == "bored":
        triggers.append({
            "type":    "speed_quiz_unlock",
            "message": "😴 Boredom detected! ⚡ Speed Quiz Mode is now available in Quizzes!",
            "action":  "unlock_speed_quiz"
        })

    print("Emotion:", raw_emotion, "Attention:", attention_score)
    result = {
        "emotion":          raw_emotion,
        "attention_score":  face_state["score"] / 100,
        "face_state":       face_state,
        "composite":        composite,
        "dominant_state":   state,
        "engagement_score": composite["engagement_score"],
        "difficulty_delta": composite["difficulty_delta"],
        "motivation":       _get_motivation(state),
        "triggers":         triggers,
        "timestamp":        datetime.utcnow().isoformat(),
        "session_id":       session_id,
    }

    # Persist snapshot
    try:
        db = get_db()
        db.emotion_snapshots.insert_one({
            "user_id":       user_id,
            "session_id":    session_id,
            "raw_emotion":   raw_emotion,
            "dominant_state": state,
            "engagement_score": composite["engagement_score"],
            "difficulty_delta": composite["difficulty_delta"],
            "face_confidence": face_confidence,
            "composite":     composite,
            "logged_at":     datetime.utcnow(),
        })
    except Exception as e:
        logger.warning("Snapshot save failed: %s", e)
    
    # smooth last 3 frames
    if not hasattr(analyze, "last_scores"):
        analyze.last_scores = []

    analyze.last_scores.append(result["engagement_score"])

    if len(analyze.last_scores) > 3:
        analyze.last_scores.pop(0)

    result["engagement_score"] = int(sum(analyze.last_scores) / len(analyze.last_scores))
    return jsonify(result), 200


@emotion_bp.route("/session/end", methods=["POST"])
@jwt_required()
def session_end():
    """Save session summary with timeline, aggregated stats, and emotion points."""
    user_id = get_jwt_identity()
    data    = request.get_json() or {}
    session_id = data.get("session_id", "")
    snapshots  = data.get("snapshots", [])
    duration_s = data.get("duration_seconds", 0)

    if not snapshots:
        return jsonify({"message": "No snapshots"}), 200

    # Aggregate
    states = [s.get("dominant_state", "unknown") for s in snapshots]
    scores = [s.get("engagement_score", 50) for s in snapshots]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 50

    from collections import Counter
    state_counts  = Counter(states)
    dominant_overall = state_counts.most_common(1)[0][0]

    # Emotion points calculation
    points = int(avg_score * 0.4 + len(snapshots) * 2 + duration_s / 30)
    if dominant_overall in ("engaged", "curious"):   points += 20
    if dominant_overall in ("frustrated", "bored"):  points = max(points - 10, 0)

    # Timeline segments (group consecutive same-state into segments)
    timeline = []
    if snapshots:
        cur_state  = snapshots[0].get("dominant_state", "unknown")
        seg_start  = 0
        for i, snap in enumerate(snapshots[1:], 1):
            ns = snap.get("dominant_state", "unknown")
            if ns != cur_state:
                timeline.append({
                    "start_snap": seg_start, "end_snap": i-1,
                    "state": cur_state,
                    "start_min": round(seg_start * (duration_s/len(snapshots))/60, 1),
                    "end_min":   round((i-1) * (duration_s/len(snapshots))/60, 1),
                })
                cur_state = ns; seg_start = i
        timeline.append({
            "start_snap": seg_start, "end_snap": len(snapshots)-1,
            "state": cur_state,
            "start_min": round(seg_start * (duration_s/len(snapshots))/60, 1),
            "end_min":   round(duration_s/60, 1),
        })

    session_doc = {
        "user_id":          user_id,
        "session_id":       session_id,
        "snapshot_count":   len(snapshots),
        "duration_seconds": duration_s,
        "avg_engagement":   avg_score,
        "dominant_state":   dominant_overall,
        "state_counts":     dict(state_counts),
        "emotion_points":   points,
        "timeline":         timeline,
        "score_over_time":  scores,
        "ended_at":         datetime.utcnow(),
    }

    try:
        db = get_db()
        db.emotion_sessions.insert_one(session_doc)
        # Add points to user's cumulative total
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"emotion_points": points}},
            upsert=False
        )
    except Exception as e:
        logger.warning("Session save failed: %s", e)

    return jsonify({
        "message":          "Session saved",
        "emotion_points":   points,
        "avg_engagement":   avg_score,
        "dominant_state":   dominant_overall,
        "timeline":         timeline,
    }), 200


@emotion_bp.route("/ai-insight", methods=["POST"])
@jwt_required()
def ai_insight():
    """
    Dual-AI coaching:
    - Groq  → quick motivational message + suggestion (≤400 tokens)
    - DeepSeek → personalised feedback based on quiz wrong count, time, emotion (≤500 tokens)
    Returns combined coaching block.
    """
    user_id = get_jwt_identity()
    data    = request.get_json() or {}

    dominant_state  = data.get("dominant_state", "focused")
    wrong_count     = data.get("wrong_questions", 0)
    time_spent_min  = data.get("time_spent_minutes", 0)
    topic           = data.get("recent_topic", "general study")
    session_avg     = data.get("session_avg_score", 50)
    recent_question = data.get("recent_question", "")

    groq_result  = {"message": "", "suggestions": []}
    ds_result    = {"feedback": "", "difficulty_action": ""}

    # ── Groq: quick motivation + suggestions ──
    if GROQ_API_KEY:
        try:
            prompt = (
                f"Student emotion: {dominant_state}. "
                f"Wrong answers: {wrong_count}. "
                f"Time spent: {time_spent_min:.1f} min. "
                f"Topic: {topic}. "
                f"Engagement score: {session_avg}%.\n"
                "Give: 1) ONE motivational sentence (max 25 words). "
                "2) TWO concrete study suggestions (max 15 words each). "
                "Format as JSON: {\"motivation\":\"...\",\"suggestions\":[\"...\",\"...\"]}"
            )
            resp = req_lib.post(GROQ_URL, headers=_groq_headers(), json={
                "model": GROQ_MODEL, "max_tokens": GROQ_TOKEN_BUDGET,
                "messages": [{"role":"user","content": prompt}],
                "temperature": 0.7,
            }, timeout=15)
            if resp.ok:
                text = resp.json()["choices"][0]["message"]["content"]
                # Strip JSON fences
                text = text.strip().lstrip("```json").rstrip("```").strip()
                parsed = json.loads(text)
                groq_result["message"]     = parsed.get("motivation", "")
                groq_result["suggestions"] = parsed.get("suggestions", [])
        except Exception as e:
            logger.warning("Groq insight error: %s", e)
            groq_result["message"] = _get_motivation(dominant_state)

    # ── DeepSeek: detailed personalised feedback ──
    if DEEPSEEK_API_KEY:
        try:
            prompt = (
                f"Learning analytics — emotion: {dominant_state}, "
                f"wrong questions: {wrong_count}, "
                f"time on task: {time_spent_min:.1f} minutes, "
                f"recent topic: {topic}, "
                f"engagement: {session_avg}%"
                + (f", last question: {recent_question[:100]}" if recent_question else "") + ".\n"
                "Write: 1) Specific feedback on performance (2 sentences, max 40 words). "
                "2) Difficulty action: one of [increase, decrease, maintain] with reason (1 sentence). "
                "Format JSON: {\"feedback\":\"...\",\"difficulty_action\":\"increase|decrease|maintain\","
                "\"reason\":\"...\"}"
            )
            resp = req_lib.post(DS_URL, headers=_ds_headers(), json={
                "model": DS_MODEL, "max_tokens": DS_TOKEN_BUDGET,
                "messages": [{"role":"user","content": prompt}],
                "temperature": 0.6, "stream": False,
            }, timeout=20)
            if resp.ok:
                text = resp.json()["choices"][0]["message"]["content"]
                text = text.strip().lstrip("```json").rstrip("```").strip()
                parsed = json.loads(text)
                ds_result["feedback"]           = parsed.get("feedback", "")
                ds_result["difficulty_action"]  = parsed.get("difficulty_action", "maintain")
                ds_result["reason"]             = parsed.get("reason", "")
        except Exception as e:
            logger.warning("DeepSeek insight error: %s", e)

    # Fallback if both APIs unavailable
    if not groq_result["message"]:
        groq_result["message"] = _get_motivation(dominant_state)
    if not groq_result["suggestions"]:
        sugg_map = {
            "frustrated": ["Take a 2-minute break, then retry.", "Review the hardest concept once more."],
            "confused":   ["Re-read the relevant section.", "Ask the AI tutor to explain it simply."],
            "bored":      ["Try the speed quiz mode.", "Increase difficulty to stay challenged."],
            "engaged":    ["Keep going — you're in flow!", "Try a harder topic while focused."],
            "focused":    ["Maintain this focus, great work.", "Tackle your weakest topic now."],
        }
        groq_result["suggestions"] = sugg_map.get(dominant_state, ["Stay consistent.", "Keep reviewing."])

    if not ds_result["difficulty_action"]:
        delta_to_action = {-2: "decrease", -1: "decrease", 0: "maintain", 1: "increase", 2: "increase"}
        state_delta = {"frustrated": -2, "anxious": -2, "confused": -1, "focused": 0,
                       "engaged": 1, "curious": 1, "bored": 2, "unknown": 0}
        ds_result["difficulty_action"] = delta_to_action.get(
            state_delta.get(dominant_state, 0), "maintain"
        )
        ds_result["feedback"] = (
            f"Based on {wrong_count} incorrect answers and {time_spent_min:.0f} min, "
            f"your engagement is {'below' if session_avg < 50 else 'above'} average. "
            f"Consider {'reviewing basics' if wrong_count > 3 else 'pushing to harder questions'}."
        )

    return jsonify({
        "groq":      groq_result,
        "deepseek":  ds_result,
        "combined_motivation": groq_result["message"],
        "suggestions": groq_result["suggestions"],
        "feedback":    ds_result["feedback"],
        "difficulty_action": ds_result["difficulty_action"],
        "difficulty_reason": ds_result.get("reason", ""),
    }), 200


@emotion_bp.route("/adapt", methods=["POST"])
@jwt_required()
def adapt():
    """
    Returns adapted parameters for quiz / qa / revision
    based on current emotion state.
    """
    data  = request.get_json() or {}
    state = data.get("dominant_state", "focused")
    delta = data.get("difficulty_delta", 0)

    difficulty_levels = ["very_easy", "easy", "medium", "hard", "very_hard"]
    current_idx       = difficulty_levels.index(data.get("current_difficulty", "medium"))
    new_idx           = max(0, min(4, current_idx + delta))
    new_difficulty    = difficulty_levels[new_idx]
    changed           = new_difficulty != difficulty_levels[current_idx]

    messages = {
        "increase": f"📈 Difficulty increased to **{new_difficulty}** — you're doing great!",
        "decrease": f"📉 Difficulty reduced to **{new_difficulty}** — let's rebuild confidence.",
        "maintain": f"✅ Difficulty stays at **{new_difficulty}** — keep the momentum.",
    }
    action  = "increase" if delta > 0 else "decrease" if delta < 0 else "maintain"
    msg     = messages[action]

    qa_tone = {
        "frustrated": "very_simple",
        "confused":   "simple_with_examples",
        "focused":    "standard",
        "engaged":    "detailed_and_challenging",
        "curious":    "exploratory",
        "bored":      "advanced_and_fast",
        "anxious":    "reassuring_and_simple",
        "unknown":    "standard",
    }.get(state, "standard")

    return jsonify({
        "new_difficulty":  new_difficulty,
        "changed":         changed,
        "action":          action,
        "banner_message":  msg,
        "qa_tone":         qa_tone,
        "state":           state,
    }), 200


@emotion_bp.route("/session-history", methods=["GET"])
@jwt_required()
def session_history():
    user_id = get_jwt_identity()
    db      = get_db()
    limit   = int(request.args.get("limit", 10))
    sessions = list(db.emotion_sessions.find(
        {"user_id": user_id},
        {"session_id": 1, "avg_engagement": 1, "dominant_state": 1,
         "emotion_points": 1, "duration_seconds": 1, "ended_at": 1,
         "state_counts": 1, "timeline": 1, "score_over_time": 1},
        sort=[("ended_at", -1)],
        limit=limit
    ))
    total_points = sum(s.get("emotion_points", 0) for s in sessions)
    for s in sessions:
        s["_id"] = str(s["_id"])
    return jsonify({"sessions": sessions, "total_emotion_points": total_points}), 200