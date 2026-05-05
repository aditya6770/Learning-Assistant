from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime
import os
import requests
import json

import re

course_bp = Blueprint('courses', __name__)

def fetch_youtube_duration(video_url):
    try:
        video_id = ""
        if "embed/" in video_url:
            video_id = video_url.split("embed/")[1].split("?")[0]
        elif "v=" in video_url:
            video_id = video_url.split("v=")[1].split("&")[0]
            
        if not video_id: return "0:00"
        
        response = requests.get(f"https://www.youtube.com/watch?v={video_id}", timeout=5)
        if not response.ok: return "0:00"
        
        # Look for duration in the page source (approxDurationMs)
        match = re.search(r'"approxDurationMs":"(\d+)"', response.text)
        if match:
            ms = int(match.group(1))
            seconds = int(ms / 1000)
            mins = seconds // 60
            secs = seconds % 60
            return f"{mins:02d}:{secs:02d}"
    except Exception as e:
        print(f"Error fetching duration: {e}")
    return "0:00"

# --- Helper for OpenRouter (AI Summaries) ---
def get_ai_lesson_summary(lesson_title, refresh=False):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "AI Summary unavailable (No OpenRouter API Key)."
    
    # Variety instruction if refreshed
    variety = "Provide a fresh perspective, focusing on different technical details or a unique real-world use-case than before." if refresh else ""
    
    prompt = f"""
    You are a technical mentor. Generate a concise study guide for the topic: '{lesson_title}'.
    Focus only on this technical topic based on its name.
    {variety}
    
    Include:
    1. What is this? (2 sentences)
    2. 3 Key Concepts to master.
    3. A 'Pro-Tip' for exams/interviews.
    4. Suggested next topic.
    Format with clean markdown.
    """
    
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:5000",
                "X-Title": "AI Learning Assistant"
            },
            data=json.dumps({
                "model": "nvidia/nemotron-nano-12b-v2-vl:free", # Nemotron Nano 12B v2 VL (free)
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.8 if refresh else 0.5 # Higher temperature for variety on refresh
            }),
            timeout=15
        )
        if response.ok:
            return response.json()['choices'][0]['message']['content']
        else:
            print(f"OpenRouter API Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Summary Exception: {e}")
    return "Could not generate AI summary at this time."

# --- Fixed Course Data (Seed) ---
COURSES = [
    {
        "_id": "dsa_001",
        "title": "Data Structures & Algorithms Mastery",
        "subject": "DSA",
        "difficulty": "Intermediate",
        "duration": "24h",
        "xp_reward": 500,
        "thumbnail": "https://images.unsplash.com/photo-1515879218367-8466d910aaa4?w=400",
        "modules": [
            {
                "title": "Module 1: Foundations & Time Complexity",
                "lessons": [
                    {"id": "dsa_l1", "title": "Big O Notation Explained", "video": "https://www.youtube.com/embed/7dz8Iaf_weM", "duration": "07:11"},
                    {"id": "dsa_l2", "title": "Space Complexity Basics", "video": "https://www.youtube.com/embed/jOMxKsUd6e0", "duration": "05:43"}
                ]
            },
            {
                "title": "Module 2: Arrays & String Manipulation",
                "lessons": [
                    {"id": "dsa_l3", "title": "Dynamic Arrays Implementation", "video": "https://www.youtube.com/embed/q_vIAn-oJ_0", "duration": "13:58"},
                    {"id": "dsa_l4", "title": "Sliding Window Technique", "video": "https://www.youtube.com/embed/jM28UBHD86U", "duration": "17:15"}
                ]
            }
        ]
    },
    {
        "_id": "os_001",
        "title": "Operating Systems: Core Concepts",
        "subject": "OS",
        "difficulty": "Advanced",
        "duration": "18h",
        "xp_reward": 400,
        "thumbnail": "https://images.unsplash.com/photo-1518770660439-4636190af475?w=400",
        "modules": [
            {
                "title": "Module 1: Process Management",
                "lessons": [
                    {"id": "os_l1", "title": "Process vs Thread", "video": "https://www.youtube.com/embed/ITc09gOrqZk", "duration": "14:20"},
                    {"id": "os_l2", "title": "CPU Scheduling Algorithms", "video": "https://www.youtube.com/embed/pPAKs7tT8sw", "duration": "25:00"}
                ]
            }, 
            {
            "title": "Module 2: Memory Management",
            "lessons": [
                {"id": "os_l3", "title": "Paging & Segmentation", "video": "https://www.youtube.com/embed/dz9Tk6KCMlQ", "duration": "13:58"},
                {"id": "os_l4", "title": "Virtual Memory", "video": "https://www.youtube.com/embed/o2_iCzS9-ZQ", "duration": "17:15"}
            ]
        }
        ]
    },

    

    {
    "_id": "dbms_001",
    "title": "DBMS Mastery",
    "subject": "DBMS",
    "difficulty": "Intermediate",
    "duration": "24h",
    "xp_reward": 500,
    "thumbnail": "https://tse2.mm.bing.net/th/id/OIP.NBP75gNl1xNaKi2Ycck6iAHaFw?pid=Api&P=0&h=180",
    "modules": [
        {
            "title": "Module 1: ER Model & Relational Model",
            "lessons": [
                {"id": "dbms_l1", "title": "ER Diagram Basics", "video": "https://www.youtube.com/embed/gbVev8RuZLg", "duration": "07:11"},
                {"id": "dbms_l2", "title": "Relational Algebra", "video": "https://www.youtube.com/embed/4YilEjkNPrQ", "duration": "05:43"}
            ]
        },
        {
            "title": "Module 2: SQL & Normalization",
            "lessons": [
                {"id": "dbms_l3", "title": "SQL Queries", "video": "https://www.youtube.com/embed/niFUzvtGyLs", "duration": "13:58"},
                {"id": "dbms_l4", "title": "Normalization Techniques", "video": "https://www.youtube.com/embed/5GDTIUVlHB8", "duration": "17:15"}
            ]
        }
    ]
},

{
    "_id": "cn_001",
    "title": "Computer Networks Mastery",
    "subject": "CN",
    "difficulty": "Intermediate",
    "duration": "24h",
    "xp_reward": 500,
    "thumbnail": "https://tse1.mm.bing.net/th/id/OIP.Y53joBwaQQ7BV7QwkCZnDAHaE7?pid=Api&P=0&h=180",
    "modules": [
        {
            "title": "Module 1: OSI Model & Basics",
            "lessons": [
                {"id": "cn_l1", "title": "OSI Model Explained", "video": "https://www.youtube.com/embed/vv4y_uOneC0", "duration": "07:11"},
                {"id": "cn_l2", "title": "TCP/IP Basics", "video": "https://www.youtube.com/embed/GfaHdjApnhU", "duration": "05:43"}
            ]
        },
        {
            "title": "Module 2: Routing & Protocols",
            "lessons": [
                {"id": "cn_l3", "title": "Routing Algorithms", "video": "https://www.youtube.com/embed/5vKu_RColVI", "duration": "13:58"},
                {"id": "cn_l4", "title": "HTTP & DNS", "video": "https://www.youtube.com/embed/vhfRArT11jc", "duration": "17:15"}
            ]
        }
    ]
},

{
    "_id": "toc_001",
    "title": "Theory of Computation Mastery",
    "subject": "TOC",
    "difficulty": "Intermediate",
    "duration": "24h",
    "xp_reward": 500,
    "thumbnail": "https://tse3.mm.bing.net/th/id/OIP.JJd5L_n0SXyHoo6WpsSDAwHaDt?pid=Api&P=0&h=180",
    "modules": [
        {
            "title": "Module 1: Automata Theory",
            "lessons": [
                {"id": "toc_l1", "title": "Finite Automata", "video": "https://www.youtube.com/embed/Qa6csfkK7_I", "duration": "07:11"},
                {"id": "toc_l2", "title": "Regular Expressions", "video": "https://www.youtube.com/embed/rjG5LwbqAp4", "duration": "05:43"}
            ]
        },
        {
            "title": "Module 2: CFG & Turing Machines",
            "lessons": [
                {"id": "toc_l3", "title": "Context Free Grammar", "video": "https://www.youtube.com/embed/SlSA9vEXCm4", "duration": "13:58"},
                {"id": "toc_l4", "title": "Turing Machine Basics", "video": "https://www.youtube.com/embed/LE_7krgRGt8", "duration": "17:15"}
            ]
        }
    ]
},

{
    "_id": "coa_001",
    "title": "Computer Organization & Architecture Mastery",
    "subject": "COA",
    "difficulty": "Intermediate",
    "duration": "24h",
    "xp_reward": 500,
    "thumbnail": "https://tse1.mm.bing.net/th/id/OIP.8wIG46M4rejDKX4_yuMBrAHaEK?pid=Api&P=0&h=180",
    "modules": [
        {
            "title": "Module 1: Digital Logic Basics",
            "lessons": [
                {"id": "coa_l1", "title": "Logic Gates", "video": "https://www.youtube.com/embed/47u7b2yh7s8", "duration": "07:11"},
                {"id": "coa_l2", "title": "Number Systems", "video": "https://www.youtube.com/embed/MxjJqq3B6JU", "duration": "05:43"}
            ]
        },
        {
            "title": "Module 2: CPU & Memory",
            "lessons": [
                {"id": "coa_l3", "title": "Instruction Cycle", "video": "https://www.youtube.com/embed/rOw9Q7PCtHg", "duration": "13:58"},
                {"id": "coa_l4", "title": "Cache Memory", "video": "https://www.youtube.com/embed/joWVGwnEiYw", "duration": "17:15"}
            ]
        }
    ]
},

{
    "_id": "compiler_001",
    "title": "Compiler Design Mastery",
    "subject": "CD",
    "difficulty": "Intermediate",
    "duration": "24h",
    "xp_reward": 500,
    "thumbnail": "https://tse4.mm.bing.net/th/id/OIP.d7qzHSYv4oqa3tt2qcDgeAHaE2?pid=Api&P=0&h=180",
    "modules": [
        {
            "title": "Module 1: Lexical Analysis",
            "lessons": [
                {"id": "cd_l1", "title": "Tokenization", "video": "https://www.youtube.com/embed/MZ9NZdZteG4", "duration": "07:11"},
                {"id": "cd_l2", "title": "Regular Expressions in Compiler", "video": "https://www.youtube.com/embed/YmgA7GkgaPY", "duration": "05:43"}
            ]
        },
        {
            "title": "Module 2: Parsing Techniques",
            "lessons": [
                {"id": "cd_l3", "title": "Top Down Parsing", "video": "https://www.youtube.com/embed/mP6YNYSpZV4", "duration": "13:58"},
                {"id": "cd_l4", "title": "Bottom Up Parsing", "video": "https://www.youtube.com/embed/SemmXpNeTx4", "duration": "17:15"}
            ]
        }
    ]
}
]

@course_bp.route('/', methods=['GET'])
@jwt_required()
def get_courses():
    from app import mongo
    db = mongo.db
    user_id = get_jwt_identity()
    
    # Fetch user progress
    progress_doc = db.course_progress.find_one({"user_id": user_id}) or {"completed_lessons": [], "bookmarks": [], "notes": {}}
    
    # Enrich courses with progress and recommendations
    # Simple recommendation: if subject is a 'weak_topic' in analytics, mark as recommended
    # We'd need to fetch analytics, but for now let's use a dummy check
    weak_topics = [] # This would come from a helper
    
    enriched = []
    for c in COURSES:
        total_lessons = sum(len(m['lessons']) for m in c['modules'])
        user_completed = [l for l in progress_doc.get("completed_lessons", []) if l.startswith(c['subject'].lower())]
        
        # Calculate completion %
        count_completed = 0
        for m in c['modules']:
            for l in m['lessons']:
                if l['id'] in progress_doc.get("completed_lessons", []):
                    count_completed += 1
        
        percentage = round((count_completed / total_lessons) * 100) if total_lessons > 0 else 0
        
        enriched.append({
            **c,
            "progress": percentage,
            "is_recommended": c['subject'] in weak_topics or percentage < 10, # Recommend new or relevant
            "last_lesson": progress_doc.get("last_lessons", {}).get(c['_id'])
        })
        
    # Calculate Global Stats
    all_progress = list(db.course_progress.find({"user_id": user_id}))
    total_xp = sum(p.get("total_xp", 0) for p in all_progress)
    
    # Simple streak logic: check last_updated or use user document
    user = db.users.find_one({"_id": ObjectId(user_id)})
    streak = user.get("streak", 0) if user else 0

    return jsonify({
        "courses": enriched,
        "total_xp": total_xp,
        "streak": streak
    })

@course_bp.route('/refresh_durations', methods=['POST'])
@jwt_required()
def refresh_durations():
    for course in COURSES:
        for module in course['modules']:
            for lesson in module['lessons']:
                dur = fetch_youtube_duration(lesson['video'])
                lesson['duration'] = dur
    return jsonify({"message": "Durations updated", "courses": COURSES})

@course_bp.route('/<course_id>', methods=['GET'])
@jwt_required()
def get_course_details(course_id):
    from app import mongo
    db = mongo.db
    course = next((c for c in COURSES if c['_id'] == course_id), None)
    if not course:
        return jsonify({"error": "Course not found"}), 404
        
    user_id = get_jwt_identity()
    progress = db.course_progress.find_one({"user_id": user_id}) or {}
    
    # Mark lessons as completed/locked
    # Simple logic: all unlocked for now, or sequentially unlocked
    return jsonify({
        "course": course,
        "completed_lessons": progress.get("completed_lessons", []),
        "bookmarks": progress.get("bookmarks", []),
        "notes": progress.get("notes", {}),
        "lesson_stats": progress.get("lesson_stats", {}),
        "completed_modules": progress.get("completed_modules", []),
        "total_xp": progress.get("total_xp", 0)
    })

def _check_module_completion(user_id, lesson_id):
    from app import mongo
    db = mongo.db
    
    # Find which course/module this lesson belongs to
    target_course = None
    target_module = None
    for c in COURSES:
        for m in c['modules']:
            if any(l['id'] == lesson_id for l in m['lessons']):
                target_course = c
                target_module = m
                break
        if target_course: break
        
    if not target_module: return
    
    # Get user progress
    progress = db.course_progress.find_one({"user_id": user_id})
    if not progress: return
    
    completed_lessons = set(progress.get("completed_lessons", []))
    module_lessons = [l['id'] for l in target_module['lessons']]
    
    if all(lid in completed_lessons for lid in module_lessons):
        # Module complete!
        module_key = f"{target_course['_id']}_{target_module['title']}"
        db.course_progress.update_one(
            {"user_id": user_id},
            {"$addToSet": {"completed_modules": module_key}}
        )
        
        # Trigger assessment generation if not exists
        existing = db.assessments.find_one({"module_id": module_key})
        if not existing:
            # We can't easily call the route, so we'll do a minimal insert or 
            # let the frontend handle it. User said: "after saving progress call a helper function 
            # that checks if an assessment exists for that module and if not inserts a new pending assessment record"
            
            # Since generating 20 questions is slow, we'll just insert a marker or 
            # we can use the same logic as challenge.py's generate_questions
            # But importing challenge_routes might cause circular imports.
            # Minimal approach: insert a "to-be-generated" record
            db.assessments.insert_one({
                "module_id": module_key,
                "module_title": target_module['title'],
                "course_id": target_course['_id'],
                "is_active": False, # Flag to indicate it needs generation
                "generated_at": datetime.utcnow()
            })

@course_bp.route('/lesson/<lesson_id>/complete', methods=['POST'])
@jwt_required()
def complete_lesson(lesson_id):
    from app import mongo
    db = mongo.db
    user_id = get_jwt_identity()
    
    # Initialize stats for this lesson if not exists
    db.course_progress.update_one(
        {"user_id": user_id},
        {
            "$addToSet": {"completed_lessons": lesson_id},
            "$inc": {"total_xp": 50}, # 50 XP for watching the lesson
            "$set": {f"lesson_stats.{lesson_id}.completed": True}
        },
        upsert=True
    )
    
    progress = db.course_progress.find_one({"user_id": user_id})
    if progress: progress['_id'] = str(progress['_id'])
    
    # Check if this completes a module
    _check_module_completion(user_id, lesson_id)
    
    return jsonify({"message": "Lesson completed", "xp_gained": 50, "progress": progress})

@course_bp.route('/lesson/<lesson_id>/summary', methods=['GET'])
@jwt_required()
def get_summary(lesson_id):
    # Find lesson title
    title = "Technical Lesson"
    for c in COURSES:
        for m in c['modules']:
            for l in m['lessons']:
                if l['id'] == lesson_id:
                    title = l['title']
                    break
    
    summary = get_ai_lesson_summary(title)
    return jsonify({"summary": summary})

@course_bp.route('/lesson/<lesson_id>/notes', methods=['POST'])
@jwt_required()
def save_notes(lesson_id):
    from app import mongo
    db = mongo.db
    user_id = get_jwt_identity()
    content = request.json.get("content", "")
    
    db.course_progress.update_one(
        {"user_id": user_id},
        {"$set": {f"notes.{lesson_id}": content}},
        upsert=True
    )
    return jsonify({"message": "Notes saved"})
@course_bp.route('/lesson/<lesson_id>/quiz', methods=['GET'])
@jwt_required()
def get_lesson_quiz(lesson_id):
    # Find lesson title
    title = "Technical Topic"
    for c in COURSES:
        for m in c['modules']:
            for l in m['lessons']:
                if l['id'] == lesson_id:
                    title = l['title']
                    break
                    
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return jsonify({"error": "No API Key"}), 500
        
    prompt = f"""
    Generate 3 Multiple Choice Questions (MCQs) for the topic: '{title}'.
    Format the response as a JSON array of objects. Each object must have:
    - 'question': The question text.
    - 'options': An array of 4 strings.
    - 'answer': The correct option (must match one of the options exactly).
    - 'explanation': A brief 1-sentence explanation.
    
    Return ONLY the JSON array. No conversational text.
    """
    
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:5000",
                "X-Title": "AI Learning Assistant"
            },
            json={
                "model": "nvidia/nemotron-nano-12b-v2-vl:free",
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=20
        )
        if response.ok:
            content = response.json()['choices'][0]['message']['content']
            # Clean JSON
            content = content.strip().replace("```json", "").replace("```", "")
            return jsonify({"quiz": json.loads(content)})
    except Exception as e:
        print(f"Quiz Generation Error: {e}")
        
    return jsonify({"error": "Could not generate quiz"}), 500

@course_bp.route('/lesson/<lesson_id>/quiz_result', methods=['POST'])
@jwt_required()
def save_quiz_result(lesson_id):
    from app import mongo
    db = mongo.db
    user_id = get_jwt_identity()
    data = request.json
    correct = data.get("correct", 0)
    total = data.get("total", 0)
    xp_gained = correct * 20
    
    db.course_progress.update_one(
        {"user_id": user_id},
        {
            "$inc": {
                "total_xp": xp_gained,
                f"lesson_stats.{lesson_id}.correct": correct,
                f"lesson_stats.{lesson_id}.total": total,
                f"lesson_stats.{lesson_id}.quiz_xp": xp_gained
            }
        },
        upsert=True
    )
    return jsonify({"message": "Quiz result saved", "xp_added": xp_gained})
@course_bp.route('/module/<int:mod_idx>/reset', methods=['POST'])
@jwt_required()
def reset_module(mod_idx):
    from app import mongo
    db = mongo.db
    user_id = get_jwt_identity()
    
    if not COURSES or mod_idx < 0 or mod_idx >= len(COURSES[0]['modules']):
        return jsonify({"error": "Invalid module index"}), 400
        
    module = COURSES[0]['modules'][mod_idx]
    lesson_ids = [l['id'] for l in module['lessons']]
    
    unset_fields = {}
    for lid in lesson_ids:
        unset_fields[f"notes.{lid}"] = ""
        unset_fields[f"lesson_stats.{lid}"] = ""
        
    db.course_progress.update_one(
        {"user_id": user_id},
        {
            "$pull": {"completed_lessons": {"$in": lesson_ids}},
            "$unset": unset_fields
        }
    )
    
    progress = db.course_progress.find_one({"user_id": user_id})
    if progress: progress['_id'] = str(progress['_id'])
    return jsonify({"message": "Module reset successful", "progress": progress})
