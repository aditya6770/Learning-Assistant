"""
Smart Mentor Recommendation Engine
──────────────────────────────────
Acts as a personalized tutor by analyzing:
  • Accuracy & Mastery trends
  • Response speed & Stress patterns
  • Streak consistency
  • Concept dependencies (via document analysis)
Generates:
  • Personalized Mentor Advice (LLM-driven)
  • Micro-Missions (Actionable tasks)
  • Roadmap status (Completed, Weak, Locked)
"""
import os, logging, requests, json
from datetime import datetime, timedelta
from typing import List, Dict

logger = logging.getLogger(__name__)

def _groq_call(messages, max_tokens=1000, temp=0.7):
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key: return "Set your GROQ_API_KEY to get mentor insights."
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "llama-3.1-8b-instant", "messages": messages, "max_tokens": max_tokens, "temperature": temp},
            timeout=10
        )
        return r.json()["choices"][0]["message"]["content"] if r.ok else ""
    except: return ""

def generate_recommendations(user_id: str, db) -> Dict:
    """Return a comprehensive mentor object for the user."""
    # 1. Gather Performance Data
    attempts = list(db.quiz_attempts.find({"user_id": user_id}, sort=[("completed_at", -1)], limit=20))
    topic_stats = _compute_detailed_topic_stats(user_id, db)
    
    # 2. Analyze Trends
    avg_acc   = sum(a.get("percentage", 0) for a in attempts) / len(attempts) if attempts else 0
    avg_speed = sum(a.get("avg_speed", 0) for a in attempts) / len(attempts) if attempts else 0
    best_streak = max([a.get("max_streak", 0) for a in attempts] + [0])
    
    # 3. Fetch Course Progress
    courses_data = list(db.course_progress.find({"user_id": user_id}))
    course_xp = sum(c.get("total_xp", 0) for c in courses_data)
    total_completed = sum(len(c.get("completed_lessons", [])) for c in courses_data)
    
    # 4. Generate Mentor Advice & Missions via LLM
    mentor_data = _generate_mentor_llm_detailed(avg_acc, avg_speed, best_streak, topic_stats, course_xp, total_completed)
    
    # 5. Attach YouTube Videos to Missions
    for mission in mentor_data.get("missions", []):
        query = mission.get("search_query") or f"{mission.get('topic', 'General')} tutorial"
        mission["video"] = _get_youtube_video(query)

    # 6. Structure Roadmap
    roadmap = []
    strong_topics_count = 0
    for topic, s in topic_stats.items():
        score = s["correct"] / s["total"] if s["total"] > 0 else 0
        if score >= 0.8: strong_topics_count += 1
        status = "mastered" if score >= 0.8 else "struggling" if score < 0.5 else "learning"
        roadmap.append({
            "topic": topic, 
            "progress": round(score*100), 
            "status": status,
            "details": f"{s['correct']}/{s['total']} Q • {s['lessons']} Lessons"
        })
    
    if len(roadmap) < 5:
        roadmap.append({"topic": "Advanced Applications", "progress": 0, "status": "locked", "details": "Unlock with XP"})

    return {
        "mentor_advice": mentor_data.get("advice", "Keep practicing to unlock more insights!"),
        "missions":      mentor_data.get("missions", []),
        "roadmap":       roadmap,
        "metrics": {
            "avg_accuracy": round(avg_acc),
            "avg_speed":    round(avg_speed, 1),
            "top_streak":   best_streak,
            "mastery_count": strong_topics_count,
            "course_xp":    course_xp,
            "lessons_completed": total_completed
        }
    }

def _get_youtube_video(query: str) -> Dict:
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    vid_id = ""
    title = f"Lesson: {query}"
    
    # 1. Try Official API (with Embeddable filter)
    if api_key:
        try:
            print(f"--- [YouTube API] Requesting video for: '{query}' ---")
            url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                "part": "snippet", 
                "q": f"{query} tutorial", 
                "type": "video", 
                "videoEmbeddable": "true", 
                "maxResults": 3, 
                "key": api_key
            }
            r = requests.get(url, params=params, timeout=5)
            if r.ok:
                items = r.json().get("items", [])
                if items:
                    vid_id = items[0]["id"]["videoId"]
                    title = items[0]["snippet"]["title"]
                    print(f"✅ [YouTube API] Success: {vid_id}")
            elif r.status_code == 403:
                print("⚠️ [YouTube API] Quota Exceeded (403).")
            else:
                print(f"❌ [YouTube API] Error: {r.status_code}")
        except Exception as e:
            print(f"❌ [YouTube API] Connection Error: {str(e)}")
    
    # 2. Scrape Fallback (If API fails or Quota Exceeded)
    if not vid_id:
        try:
            print(f"--- [YouTube SCRAPER] Fallback mode for: '{query}' ---")
            search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}+educational+tutorial"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            r = requests.get(search_url, headers=headers, timeout=5)
            if r.ok:
                import re
                ids = re.findall(r'"videoId":"([^"]+)"', r.text)
                if ids:
                    vid_id = ids[0]
                    print(f"✅ [YouTube SCRAPER] Found ID: {vid_id}")
        except Exception as e:
            print(f"❌ [YouTube SCRAPER] Failed: {str(e)}")

    if not vid_id:
        return {
            "title": title,
            "url": f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}",
            "embed_url": ""
        }

    return {
        "title": title,
        "url": f"https://www.youtube.com/watch?v={vid_id}",
        "embed_url": f"https://www.youtube.com/embed/{vid_id}?modestbranding=1&rel=0&iv_load_policy=3&enablejsapi=1"
    }

def _generate_mentor_llm_detailed(acc, speed, streak, topic_stats, course_xp, total_completed) -> Dict:
    # Format topic stats for the prompt
    topic_summary = ""
    for t, s in topic_stats.items():
        score = (s['correct']/s['total']*100) if s['total']>0 else 0
        topic_summary += f"- {t}: {s['correct']}/{s['total']} Correct, {s['lessons']} Lessons Completed. Accuracy: {score:.1f}%\n"

    prompt = f"""You are an Expert Academic Mentor. 
User Global Performance: 
- Document Quiz Accuracy: {acc}%
- Avg Response Speed: {speed}s
- Max Day Streak: {streak}
- Total Course XP: {course_xp}
- Total Lessons Completed: {total_completed}

Detailed Topic Stats:
{topic_summary}

Your task:
1. Provide a 2-sentence mentorship insight focusing on the 'Right vs Attempted' ratio and lesson completion topics.
2. Generate EXACTLY 5 Micro-Missions.
3. CRITICAL: At least TWO missions MUST be 'Course Missions' (e.g., 'Master Module X' or 'Complete Lesson Y' from the video section).
4. Base missions on topics where the user has low accuracy or hasn't completed many lessons.

Format JSON:
{{
  "advice": "...",
  "missions": [
    {{ 
      "title": "...", 
      "description": "...", 
      "reward": "... XP", 
      "type": "revision|practice|challenge|course",
      "search_query": "topic search"
    }}
  ]
}}
"""
    raw = _groq_call([{"role": "user", "content": prompt}])
    try:
        start = raw.find('{')
        end = raw.rfind('}') + 1
        return json.loads(raw[start:end])
    except:
        return {
            "advice": "Focus on topics where your question accuracy is low. Bridging video lessons with active recall is the key to mastery.",
            "missions": [
                { "title": "Course Master", "description": "Complete the next lesson in your highest progress course.", "reward": "100 XP", "type": "course", "search_query": "educational tutorial" },
                { "title": "Accuracy Boost", "description": "Practice 5 questions on your weakest topic.", "reward": "50 XP", "type": "practice", "search_query": "basics" }
            ]
        }

def _compute_detailed_topic_stats(user_id: str, db) -> Dict[str, Dict]:
    stats = {} # {topic: {"correct": 0, "total": 0, "lessons": 0}}
    
    # 1. Document Quiz Mastery
    attempts = list(db.quiz_attempts.find({"user_id": user_id}, sort=[("completed_at", -1)], limit=50))
    for a in attempts:
        topic = a.get("topic", "General")
        if topic not in stats: stats[topic] = {"correct": 0, "total": 0, "lessons": 0}
        stats[topic]["correct"] += a.get("score", 0)
        stats[topic]["total"] += a.get("total_questions", 1)
    
    # 2. Course Module Mastery
    course_progress = list(db.course_progress.find({"user_id": user_id}))
    for cp in course_progress:
        l_stats = cp.get("lesson_stats", {})
        for lesson_id, s in l_stats.items():
            topic = lesson_id.split('_')[0].upper() if '_' in lesson_id else "Course"
            if topic not in stats: stats[topic] = {"correct": 0, "total": 0, "lessons": 0}
            stats[topic]["correct"] += s.get("correct", 0)
            stats[topic]["total"] += s.get("total", 0)
            if s.get("completed"):
                stats[topic]["lessons"] += 1

    return stats
