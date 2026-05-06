"""
Analytics Routes — /api/analytics
  GET /dashboard          Overview stats
  GET /progress           Quiz score trend over time
  GET /topics             Per-topic mastery breakdown
  GET /engagement         Emotion/attention trends
  GET /leaderboard        Optional class leaderboard
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime, timedelta
from collections import defaultdict
from bson import ObjectId

def serialize(obj):
    if isinstance(obj, ObjectId):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

analytics_bp = Blueprint("analytics", __name__)


def get_db():
    from app import mongo
    return mongo.db


# ── Dashboard ─────────────────────────────────────────────────────────────────
@analytics_bp.route("/dashboard", methods=["GET"])
@jwt_required()
def dashboard():
    user_id = get_jwt_identity()
    db      = get_db()

    total_docs     = db.documents.count_documents({"user_id": user_id})
    total_quizzes  = db.quizzes.count_documents({"user_id": user_id})
    
    # Aggregated Stats
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$group": {
            "_id": None, 
            "avg_pct": {"$avg": "$percentage"},
            "total_xp": {"$sum": "$skill_score"},
            "total_correct": {"$sum": "$score"},
            "total_qs": {"$sum": "$total_questions"},
            "attempts": {"$sum": 1}
        }}
    ]
    agg = list(db.quiz_attempts.aggregate(pipeline))
    avg_score    = round(agg[0]["avg_pct"], 2) if agg else 0
    quiz_xp      = agg[0].get("total_xp", 0) if agg else 0
    quiz_correct = agg[0].get("total_correct", 0) if agg else 0
    quiz_qs      = agg[0].get("total_qs", 0) if agg else 0
    total_attempts = agg[0].get("attempts", 0) if agg else 0

    # Course progress & Practice stats
    c_prog = db.course_progress.find_one({"user_id": user_id}) or {}
    lessons_done = len(c_prog.get("completed_lessons", []))
    course_xp    = c_prog.get("total_xp", 0)
    
    course_correct = 0
    course_qs = 0
    for l_id, s in c_prog.get("lesson_stats", {}).items():
        course_correct += s.get("correct", 0)
        course_qs += s.get("total", 0)

    # Combined Stats
    total_xp = quiz_xp + course_xp
    total_correct = quiz_correct + course_correct
    total_attempted = quiz_qs + course_qs
    combined_acc = round((total_correct / total_attempted * 100), 2) if total_attempted > 0 else 0

    # Recent activity
    recent = list(db.quiz_attempts.find(
        {"user_id": user_id},
        {"answers": 0},
        sort=[("completed_at", -1)],
        limit=5
    ))
    for r in recent:
        r["_id"]     = str(r["_id"])
        r["quiz_id"] = str(r["quiz_id"])
        if "completed_at" in r:
            r["completed_at"] = r["completed_at"].isoformat()

    streak = _calc_streak(user_id, db)
    
    # Fetch emotion points
    user_doc = db.users.find_one({"_id": ObjectId(user_id)}, {"emotion_points": 1, "daily_challenge_points": 1, "assessment_points": 1})
    emotion_pts = user_doc.get("emotion_points", 0) if user_doc else 0
    daily_pts   = user_doc.get("daily_challenge_points", 0) if user_doc else 0
    assess_pts  = user_doc.get("assessment_points", 0) if user_doc else 0

    return jsonify({
        "total_documents": total_docs,
        "total_quizzes": total_quizzes,
        "total_attempts": total_attempts,
        "average_score": avg_score,
        "total_xp": total_xp,
        "total_solved": total_correct,
        "total_attempted": total_attempted,
        "lessons_completed": lessons_done,
        "accuracy": combined_acc,
        "streak_days": streak,
        "recent_activity": recent,
        "course_xp": course_xp,
        "quiz_correct": quiz_correct,
        "quiz_total": quiz_qs,
        "course_correct": course_correct,
        "course_total": course_qs,
        "emotion_points": emotion_pts,
        "daily_challenge_points": daily_pts,
        "assessment_points": assess_pts
    }), 200


# ── Leaderboard (Advanced Multi-Factor) ────────────────────────
# ── Leaderboard Configuration (Modular & Adjustable) ──────────────────
SCORING_CONFIG = {
    "WEIGHTS": {
        "accuracy": 0.40,      # 40% - Global performance quality
        "consistency": 0.30,   # 30% - Streak & Engagement (Emotion)
        "effort": 0.20,        # 20% - Lessons & XP
        "volume": 0.10         # 10% - Total attempts (to reward activity)
    },
    "TARGETS": {
        "lessons": 50,         # Max normalization target for lessons
        "xp": 5000,            # Max normalization target for XP
        "emotion_pts": 1000,   # Max normalization target for Emotion Points
        "streak": 30           # Max normalization target for Streak days
    }
}

@analytics_bp.route("/leaderboard", methods=["GET"])
@jwt_required()
def leaderboard():
    db = get_db()
    current_user_id = get_jwt_identity()
    cfg = SCORING_CONFIG
    
    print(f"\n[💎 ADVANCED LEADERBOARD] Re-calculating with weighted metrics for: {current_user_id}")
    
    try:
        # 1. Fetch Users
        users = {str(u["_id"]): u for u in db.users.find({}, {
            "username": 1, "profile.avatar": 1, "emotion_points": 1, "streak": 1
        })}
        user_ids = list(users.keys())
        
        # 2. Bulk Fetch Stats (with mixed ID support)
        user_ids_mixed = []
        for uid in user_ids:
            user_ids_mixed.append(uid)
            try: user_ids_mixed.append(ObjectId(uid))
            except: pass

        quiz_stats_raw = list(db.quiz_attempts.aggregate([
            {"$match": {"user_id": {"$in": user_ids_mixed}}},
            {"$group": {
                "_id": "$user_id",
                "xp": {"$sum": "$skill_score"},
                "correct": {"$sum": "$score"},
                "total": {"$sum": "$total_questions"},
                "attempts": {"$sum": 1}
            }}
        ]))
        quiz_map = {str(s["_id"]): s for s in quiz_stats_raw}
        
        course_progress_raw = list(db.course_progress.find({"user_id": {"$in": user_ids_mixed}}))
        course_map = {str(cp["user_id"]): cp for cp in course_progress_raw}
        
        leaderboard_data = []
        for uid, u in users.items():
            # Data Gathering
            qa = quiz_map.get(uid, {})
            cp = course_map.get(uid, {})
            
            # --- Metrics Calculation ---
            # A. Effort Metrics
            lessons_done = len(cp.get("completed_lessons", []))
            total_xp     = qa.get("xp", 0) + cp.get("total_xp", 0)
            
            # B. Accuracy Metrics (Safely handled)
            quiz_correct = qa.get("correct", 0)
            quiz_total   = qa.get("total", 0)
            
            course_correct = 0
            course_total   = 0
            for s in cp.get("lesson_stats", {}).values():
                if isinstance(s, dict):
                    course_correct += s.get("correct", 0)
                    course_total   += s.get("total", 0)
            
            total_correct = quiz_correct + course_correct
            total_attempted = quiz_total + course_total
            
            global_accuracy = (total_correct / total_attempted * 100) if total_attempted > 0 else 0
            quiz_accuracy   = (quiz_correct / quiz_total * 100) if quiz_total > 0 else 0
            
            # C. Consistency Metrics
            emotion_pts = u.get("emotion_points", 0) or 0
            streak      = u.get("streak", 0) or 0
            
            # D. Volume Metrics
            quiz_attempts = qa.get("attempts", 0)
            
            # --- Normalization (0-100 scale) ---
            n_accuracy    = min(100, global_accuracy)
            n_lessons     = min(100, (lessons_done / cfg["TARGETS"]["lessons"]) * 100)
            n_xp          = min(100, (total_xp / cfg["TARGETS"]["xp"]) * 100)
            n_emotion     = min(100, (emotion_pts / cfg["TARGETS"]["emotion_pts"]) * 100)
            n_streak      = min(100, (streak / cfg["TARGETS"]["streak"]) * 100)
            n_attempts    = min(100, (quiz_attempts / 20) * 100) # Target 20 quizzes for full volume score
            
            # --- Grouping Normalized Scores ---
            score_acc    = n_accuracy
            score_cons   = (n_streak * 0.6) + (n_emotion * 0.4)
            score_effort = (n_lessons * 0.5) + (n_xp * 0.5)
            score_vol    = n_attempts
            
            # --- Final Composite Score ---
            composite_score = (
                (score_acc    * cfg["WEIGHTS"]["accuracy"]) +
                (score_cons   * cfg["WEIGHTS"]["consistency"]) +
                (score_effort * cfg["WEIGHTS"]["effort"]) +
                (score_vol    * cfg["WEIGHTS"]["volume"])
            )
            
            leaderboard_data.append({
                "user_id": uid,
                "username": u.get("username", "Unknown"),
                "avatar": u.get("profile", {}).get("avatar", ""),
                "score": round(composite_score, 2),
                "metrics": {
                    "accuracy": round(global_accuracy, 1),
                    "xp": total_xp,
                    "lessons": lessons_done,
                    "streak": streak,
                    "attempts": quiz_attempts
                }
            })
            
        # 5. Tie-Breaking & Sorting
        # Order: Composite Score -> Accuracy -> XP -> Lessons
        leaderboard_data.sort(key=lambda x: (
            x["score"], 
            x["metrics"]["accuracy"], 
            x["metrics"]["xp"], 
            x["metrics"]["lessons"]
        ), reverse=True)
        
        # 6. Assign Rank
        for i, entry in enumerate(leaderboard_data):
            entry["rank"] = i + 1
            
        print(f"  -> SUCCESS: Generated advanced rankings for {len(leaderboard_data)} users.\n")
        
        return jsonify({
            "leaderboard": leaderboard_data[:20],
            "current_user_rank": next((x["rank"] for x in leaderboard_data if x["user_id"] == current_user_id), None)
        }), 200
        
    except Exception as e:
        import traceback
        print(f"  -> ❌ LEADERBOARD CALC ERROR: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": "Failed to calculate advanced rankings", "details": str(e)}), 500


# ── Score Progress ─────────────────────────────────────────────────────────────
@analytics_bp.route("/progress", methods=["GET"])
@jwt_required()
def progress():
    user_id = get_jwt_identity()
    db      = get_db()
    days    = int(request.args.get("days", 30))
    since   = datetime.utcnow() - timedelta(days=days)

    attempts = list(db.quiz_attempts.find(
        {"user_id": user_id, "completed_at": {"$gte": since}},
        {"percentage": 1, "completed_at": 1, "quiz_id": 1, "total_questions": 1, "score": 1},
        sort=[("completed_at", 1)]
    ))

    data = []
    for a in attempts:
        data.append({
            "date": a["completed_at"].strftime("%Y-%m-%d"),
            "percentage": a.get("percentage", 0),
            "score": a.get("score", 0),
            "total": a.get("total_questions", 0),
            "quiz_id": str(a["quiz_id"]),
        })

    return jsonify({"progress": data, "days": days}), 200


# ── Per-topic Mastery ─────────────────────────────────────────────────────────
@analytics_bp.route("/topics", methods=["GET"])
@jwt_required()
def topic_mastery():
    user_id = get_jwt_identity()
    db      = get_db()

    attempts = list(db.quiz_attempts.find(
        {"user_id": user_id},
        {"quiz_id": 1, "percentage": 1},
        sort=[("completed_at", -1)],
        limit=30
    ))

    topic_data = defaultdict(list)
    for a in attempts:
        quiz = db.quizzes.find_one({"_id": a["quiz_id"]}, {"title": 1, "document_id": 1})
        if quiz:
            title = quiz.get("title", "General")
            topic = " ".join(title.replace("Quiz:", "").strip().split()[:4])
            topic_data[topic].append(a.get("percentage", 0))

    result = []
    for topic, scores in topic_data.items():
        result.append({
            "topic": topic,
            "mastery": round(sum(scores) / len(scores), 2),
            "attempts": len(scores),
            "best": round(max(scores), 2),
        })

    result.sort(key=lambda x: x["mastery"])
    return jsonify({"topics": result}), 200


# ── Engagement (emotion) trends ───────────────────────────────────────────────
@analytics_bp.route("/engagement", methods=["GET"])
@jwt_required()
def engagement():
    user_id = get_jwt_identity()
    db      = get_db()
    days    = int(request.args.get("days", 14))
    since   = datetime.utcnow() - timedelta(days=days)

    logs = list(db.emotion_logs.find(
        {"user_id": user_id, "logged_at": {"$gte": since}},
        sort=[("logged_at", 1)]
    ))

    data = []
    for log in logs:
        data.append({
            "date": log["logged_at"].strftime("%Y-%m-%d"),
            "avg_attention": log.get("avg_attention", 0),
            "dominant_emotion": log.get("dominant_emotion", "unknown"),
            "engagement_level": log.get("engagement_level", "unknown"),
        })
    return jsonify({"engagement": data}), 200


# ── Advanced Analytics ─────────────────────────────────────────────────────────
@analytics_bp.route("/advanced", methods=["GET"])
@jwt_required()
def advanced_analytics():
    user_id = get_jwt_identity()
    db      = get_db()
    
    # 1. Base Stats
    total_docs = db.documents.count_documents({"user_id": user_id})
    agg = list(db.quiz_attempts.aggregate([
        {"$match": {"user_id": user_id}},
        {"$group": {
            "_id": None, 
            "avg_pct": {"$avg": "$percentage"},
            "total_xp": {"$sum": "$skill_score"},
            "total_correct": {"$sum": "$score"},
            "total_qs": {"$sum": "$total_questions"},
            "attempts": {"$sum": 1}
        }}
    ]))
    quiz_xp      = agg[0].get("total_xp", 0) if agg else 0
    quiz_correct = agg[0].get("total_correct", 0) if agg else 0
    quiz_qs      = agg[0].get("total_qs", 0) if agg else 0
    quiz_attempts = agg[0].get("attempts", 0) if agg else 0

    c_prog = db.course_progress.find_one({"user_id": user_id}) or {}
    lessons_done = len(c_prog.get("completed_lessons", []))
    course_xp    = c_prog.get("total_xp", 0)
    
    course_correct = 0
    course_qs = 0
    for s in c_prog.get("lesson_stats", {}).values():
        if isinstance(s, dict):
            course_correct += s.get("correct", 0)
            if s.get("total", 0) > 0: course_qs += s.get("total", 0)

    total_xp = quiz_xp + course_xp
    total_correct = quiz_correct + course_correct
    total_attempted = quiz_qs + course_qs
    accuracy = round((total_correct / total_attempted * 100), 1) if total_attempted > 0 else 0
    
    user_doc = db.users.find_one({"_id": ObjectId(user_id)}, {"emotion_points": 1, "streak": 1})
    emotion_pts = user_doc.get("emotion_points", 0) if user_doc else 0
    streak = user_doc.get("streak", 0) if user_doc else 0

    # 2. Topic Mastery
    all_attempts = list(db.quiz_attempts.find({"user_id": user_id}, {"quiz_id": 1, "percentage": 1}))
    topic_scores = defaultdict(list)
    for a in all_attempts:
        quiz = db.quizzes.find_one({"_id": a["quiz_id"]}, {"title": 1})
        if quiz:
            topic = " ".join(quiz.get("title", "Gen").replace("Quiz:","").strip().split()[:3])
            topic_scores[topic].append(a["percentage"])
    
    mastery = {"strong":[], "average":[], "weak":[]}
    for topic, scores in topic_scores.items():
        avg = sum(scores) / len(scores)
        item = {"topic": topic, "mastery": round(avg, 1), "attempts": len(scores)}
        if avg >= 75: mastery["strong"].append(item)
        elif avg >= 50: mastery["average"].append(item)
        else: mastery["weak"].append(item)

    # 3. Charts
    since_30 = datetime.utcnow() - timedelta(days=30)
    history_30 = list(db.quiz_attempts.find(
        {"user_id": user_id, "completed_at": {"$gte": since_30}},
        sort=[("completed_at", 1)]
    ))
    line_data = [{"date": a["completed_at"].strftime("%m/%d"), "score": a["percentage"]} for a in history_30]
    
    # Chronological accuracy vs speed
    speed_acc_data = []
    for a in history_30:
        speed_acc_data.append({
            "date": a["completed_at"].strftime("%m/%d %H:%M"),
            "percentage": a.get("percentage", 0),
            "time_seconds": a.get("time_taken_seconds", 45)
        })

    # 4. History
    recent_10 = list(db.quiz_attempts.find({"user_id": user_id}, sort=[("completed_at", -1)], limit=10))
    history_10 = []
    for r in recent_10:
        q = db.quizzes.find_one({"_id": r["quiz_id"]}, {"title": 1})
        history_10.append({
            "title": q.get("title", "Quiz") if q else "Quiz",
            "score": r["score"],
            "total": r["total_questions"],
            "percentage": r["percentage"],
            "date": r["completed_at"].strftime("%b %d")
        })

    return jsonify({
        "stats": {
            "docs": total_docs,
            "accuracy": accuracy,
            "streak": streak,
            "total_xp": total_xp,
            "lessons": lessons_done,
            "course_xp": course_xp,
            "course_score": f"{course_correct}/{course_qs}",
            "quiz_attempts": quiz_attempts,
            "quiz_score": f"{quiz_correct}/{quiz_qs}",
            "quiz_acc": round(quiz_correct/quiz_qs*100, 1) if quiz_qs > 0 else 0,
            "total_solved": f"{total_correct}/{total_attempted}",
            "emotion_points": emotion_pts
        },
        "mastery": mastery,
        "line_data": line_data,
        "speed_acc_data": speed_acc_data,
        "history": history_10,
        "challenge_history": [
             {**{k: str(v) if isinstance(v, ObjectId) else v for k, v in doc.items()}, "_id": str(doc["_id"])}
             for doc in db.challenge_attempts.find(
                 {"user_id": user_id},
                 {"submitted_at": 1, "score": 1, "percentage": 1, "type": 1},
                 sort=[("submitted_at", -1)],
                 limit=10
             )
         ]
    }), 200

@analytics_bp.route("/compare/<target_user_id>", methods=["GET"])
@jwt_required()
def compare_users(target_user_id):
    me_id = get_jwt_identity()
    db = get_db()
    
    # 1. Calculate Global Bounds for Normalization (Fair scaling 1-100)
    all_users = list(db.users.find({}, {"daily_challenge_points": 1, "assessment_points": 1}))
    all_c_prog = list(db.course_progress.find({}, {"total_xp": 1}))
    
    xp_vals = [cp.get("total_xp", 0) for cp in all_c_prog]
    assess_vals = [u.get("assessment_points", 0) for u in all_users]
    challenge_vals = [u.get("daily_challenge_points", 0) for u in all_users]
    
    # Global Avg Speed bounds
    speed_raw = list(db.quiz_attempts.aggregate([
        {"$group": {"_id": "$user_id", "avg_speed": {"$avg": "$avg_speed"}}}
    ]))
    speed_vals = [s["avg_speed"] for s in speed_raw if s["avg_speed"] > 0]

    def get_b(vals):
        if not vals: return {"min": 0, "max": 100}
        return {"min": min(vals), "max": max(vals)}
    
    bounds = {
        "xp": get_b(xp_vals),
        "assess": get_b(assess_vals),
        "challenge": get_b(challenge_vals),
        "speed": get_b(speed_vals)
    }

    def normalize(val, b, inv=False):
        if b["max"] == b["min"]: return 50
        if inv:
            score = ((b["max"] - val) / (b["max"] - b["min"])) * 99 + 1
        else:
            score = ((val - b["min"]) / (b["max"] - b["min"])) * 99 + 1
        return round(max(1, min(100, score)), 1)

    def get_user_full_stats(uid):
        user_doc = db.users.find_one({"_id": ObjectId(uid)}, {"username": 1, "profile.avatar": 1, "emotion_points": 1, "streak": 1, "assessment_points": 1, "daily_challenge_points": 1})
        if not user_doc: return None
        
        # Mixed ID handling
        uid_str = str(uid)
        uid_obj = ObjectId(uid)
        uid_filter = {"$in": [uid_str, uid_obj]}

        # --- Part 1: Correctness & Speed Aggregation ---
        q_agg = list(db.quiz_attempts.aggregate([
            {"$match": {"user_id": uid_filter}},
            {"$group": {"_id": None, 
                        "correct": {"$sum": "$score"}, 
                        "total": {"$sum": "$total_questions"}, 
                        "count": {"$sum": 1},
                        "avg_speed": {"$avg": "$avg_speed"}}}
        ]))
        quiz_correct = q_agg[0].get("correct", 0) if q_agg else 0
        quiz_total   = q_agg[0].get("total", 0) if q_agg else 0
        user_avg_speed = q_agg[0].get("avg_speed", 0) if q_agg else 0

        c_prog = db.course_progress.find_one({"user_id": uid_filter}) or {}
        course_correct = sum(s.get("correct", 0) for s in c_prog.get("lesson_stats", {}).values() if isinstance(s, dict))
        course_total   = sum(s.get("total", 0) for s in c_prog.get("lesson_stats", {}).values() if isinstance(s, dict))
        lessons_completed = len(c_prog.get("completed_lessons", []))
        course_xp = c_prog.get("total_xp", 0)

        ch_agg = list(db.challenge_attempts.aggregate([
            {"$match": {"user_id": uid_filter}},
            {"$group": {"_id": "$type", "correct": {"$sum": "$score"}, "total": {"$sum": "$total"}, "count": {"$sum": 1}}}
        ]))
        ch_map = {item["_id"]: item for item in ch_agg}
        
        assess_correct = ch_map.get("assessment", {}).get("correct", 0)
        assess_total   = ch_map.get("assessment", {}).get("total", 0)
        assess_done    = ch_map.get("assessment", {}).get("count", 0)
        
        daily_correct  = ch_map.get("daily", {}).get("correct", 0)
        daily_total    = ch_map.get("daily", {}).get("total", 0)
        daily_done     = ch_map.get("daily", {}).get("count", 0)

        total_correct = quiz_correct + course_correct + assess_correct + daily_correct
        total_attempted = quiz_total + course_total + assess_total + daily_total
        overall_accuracy = round((total_correct / total_attempted * 100), 1) if total_attempted > 0 else 0

        assess_pts = user_doc.get("assessment_points", 0)
        daily_pts  = user_doc.get("daily_challenge_points", 0)

        # --- Part 2: Topic Mastery ---
        all_attempts = list(db.quiz_attempts.find({"user_id": uid_filter}, {"quiz_id": 1, "percentage": 1}))
        topic_scores = defaultdict(list)
        for a in all_attempts:
            q = db.quizzes.find_one({"_id": a["quiz_id"]}, {"title": 1})
            if q:
                t = " ".join(q.get("title", "Gen").replace("Quiz:","").strip().split()[:2])
                topic_scores[t].append(a["percentage"])
        
        mastery = {"strong":[], "average":[], "weak":[]}
        for t, s in topic_scores.items():
            if s:
                avg = sum(s)/len(s)
                if avg >= 75: mastery["strong"].append(t)
                elif avg >= 50: mastery["average"].append(t)
                else: mastery["weak"].append(t)

        # --- Part 3: Lessons Learned (Title + Accuracy) ---
        from .course_routes import COURSES
        def get_lt(lid):
            for c in COURSES:
                for m in c.get("modules", []):
                    for l in m.get("lessons", []):
                        if l.get("id") == lid: return l.get("title")
            return lid

        lessons_learned = []
        for lid, s in c_prog.get("lesson_stats", {}).items():
            if isinstance(s, dict) and s.get("total", 0) > 0:
                lessons_learned.append({
                    "title": get_lt(lid),
                    "accuracy": round((s.get("correct", 0) / s.get("total", 0) * 100), 1)
                })

        return {
            "username": user_doc.get("username", "User"),
            "avatar": user_doc.get("profile", {}).get("avatar", ""),
            "metrics": {
                "accuracy": overall_accuracy,
                "lessons": lessons_completed,
                "assess_done": assess_done,
                "daily_done": daily_done,
                "course_xp_score": normalize(course_xp, bounds["xp"]),
                "assess_score": normalize(assess_pts, bounds["assess"]),
                "challenge_score": normalize(daily_pts, bounds["challenge"]),
                "speed_score": normalize(user_avg_speed, bounds["speed"], inv=True),
                "raw": {
                    "lessons": lessons_completed,
                    "assessments": assess_done,
                    "challenges": daily_done,
                    "accuracy": overall_accuracy,
                    "c_xp": normalize(course_xp, bounds["xp"]),
                    "a_pts": normalize(assess_pts, bounds["assess"]),
                    "ch_pts": normalize(daily_pts, bounds["challenge"]),
                    "speed_score": normalize(user_avg_speed, bounds["speed"], inv=True),
                    "speed": round(user_avg_speed, 1)
                }
            },
            "topics": mastery,
            "lessons_learned": lessons_learned
        }

    return jsonify({
        "me": get_user_full_stats(me_id),
        "competitor": get_user_full_stats(target_user_id)
    }), 200

@analytics_bp.route("/ai-suggestions", methods=["POST"])
@jwt_required()
def ai_suggestions():
    import os, requests
    data = request.json
    me = data.get("me", {})
    comp = data.get("competitor", {})
    
    prompt = f"""
    Compare these two learners and provide 4-6 specific actionable suggestions for '{me['username']}' to outperform '{comp['username']}'.
    
    {me['username']} Stats:
    - Overall Accuracy: {me['metrics']['accuracy']}%
    - Lessons Completed: {me['metrics']['lessons']}
    - Assessments Done: {me['metrics']['assess_done']}
    - Challenges Done: {me['metrics']['daily_done']}
    - Course XP Score (1-100): {me['metrics']['course_xp_score']}
    - Assessment Points Score (1-100): {me['metrics']['assess_score']}
    - Strong Topics: {', '.join(me['topics']['strong'])}
    - Weak Topics: {', '.join(me['topics']['weak'])}
    
    {comp['username']} Stats:
    - Overall Accuracy: {comp['metrics']['accuracy']}%
    - Lessons Completed: {comp['metrics']['lessons']}
    - Assessments Done: {comp['metrics']['assess_done']}
    - Challenges Done: {comp['metrics']['daily_done']}
    - Course XP Score (1-100): {comp['metrics']['course_xp_score']}
    - Assessment Points Score (1-100): {comp['metrics']['assess_score']}
    - Strong Topics: {', '.join(comp['topics']['strong'])}
    - Weak Topics: {', '.join(comp['topics']['weak'])}
    
    Suggestions should be short, punchy, and highly tactical. Return only a JSON list of strings.
    """
    
    try:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key: return jsonify({"suggestions": ["Complete more lessons to build XP", "Focus on accuracy in your next quiz", "Maintain your streak to build momentum"]}), 200

        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "mistralai/mistral-7b-instruct",
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        ai_data = res.json()
        text = ai_data['choices'][0]['message']['content']
        # Very simple extraction in case AI doesn't return pure JSON
        import re
        suggestions = re.findall(r'"([^"]*)"', text)
        if not suggestions: suggestions = [s.strip('- ').strip() for s in text.split('\n') if s.strip()]
        
        return jsonify({"suggestions": suggestions[:6]}), 200
    except:
        return jsonify({"suggestions": ["Focus on Weak topics to bridge the gap", "Increase quiz frequency to match challenger", "Leverage your Strong topics to gain rapid XP"]}), 200

def _calc_streak(user_id: str, db) -> int:
    attempts = list(db.quiz_attempts.find(
        {"user_id": user_id},
        {"completed_at": 1},
        sort=[("completed_at", -1)]
    ))
    if not attempts:
        return 0

    days_with_activity = sorted(
        {a["completed_at"].date() for a in attempts}, reverse=True
    )

    streak  = 0
    today   = datetime.utcnow().date()
    current = today

    if days_with_activity[0] < today - timedelta(days=1):
        return 0

    for day in days_with_activity:
        if day == current or day == current - timedelta(days=1):
            streak += 1
            current = day
        else:
            break
    return streak
