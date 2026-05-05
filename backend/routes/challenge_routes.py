import os, requests, json, random, base64
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime, timedelta

challenge_bp = Blueprint('challenge', __name__)

def get_db():
    from app import mongo
    return mongo.db

def _ai_call(messages, model="llama-3.3-70b-versatile"):
    """Groq AI call for Daily Challenge questions"""
    api_key = os.getenv("GROQ_API_KEY")
    url = "https://api.groq.com/openai/v1/chat/completions"
    
    if not api_key: return None
    
    for attempt in range(2):
        try:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "response_format": {"type": "json_object"}
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            if response.ok:
                content = response.json()['choices'][0]['message']['content']
                return json.loads(content)
            else:
                print(f"[⚠️] Groq Error ({model} - Attempt {attempt+1}): {response.status_code}")
        except Exception as e:
            print(f"[⚠️] AI Call Error (Groq - Attempt {attempt+1}): {e}")
    return None

def generate_questions(count, subject_context, is_gate=False):
    """Generate X questions using Groq with smart fallbacks"""
    subjects = ["database", "os", "computer organization and architecture", "computer networks", "dsa", "compiler design", "aptitude", "digital logics"]
    subject = subject_context or random.choice(subjects)
    
    gate_clause = "Use concepts or patterns common in GATE (Graduate Aptitude Test in Engineering) previous year questions." if is_gate else ""
    
    def _generate_set(num, model="llama-3.3-70b-versatile"):
        set_prompt = f"""
        Generate {num} technical questions for the subject: {subject}.
        {gate_clause}
        
        CRITICAL: Include exactly 2 MSQs and {num-2} MCQs.
        Each question MUST have a 'explanation' field (max 2 sentences).
        
        Format as JSON:
        {{ "questions": [ {{ "question": "text", "type": "mcq", "options": ["A", "B", "C", "D"], "correct_answers": [0], "explanation": "..." }} ] }}
        """
        return _ai_call([{"role": "user", "content": set_prompt}], model)

    # Use 2 sets of 10 for faster processing
    all_qs = []
    print(f"[🧠] Generating 2 sets of 10 questions using Llama 3.3 70b...")
    q1 = _generate_set(10)
    q2 = _generate_set(10)
    
    if q1 and 'questions' in q1: all_qs.extend(q1['questions'])
    if q2 and 'questions' in q2: all_qs.extend(q2['questions'])
    
    # Fallback to single 20 if both failed or too short
    if len(all_qs) < 15:
        print(f"[⚠️] Dual set failed or short. Trying single set of 20...")
        res = _generate_set(20)
        if res and 'questions' in res: all_qs = res['questions']
        
    # Final Fallback to 8b if still empty
    if len(all_qs) < 10:
        print(f"[⚠️] Llama 3.3 70b failed completely. Using 8b fallback...")
        res_8b = _generate_set(20, model="llama-3.1-8b-instant")
        if res_8b and 'questions' in res_8b:
            all_qs = res_8b['questions']

    random.shuffle(all_qs)
    for i, q in enumerate(all_qs):
        q['id'] = f"ch_q_{i}"
        
    final_questions = all_qs[:20]
    return final_questions, subject
@challenge_bp.route('/daily', methods=['GET'])
@jwt_required()
def get_daily_challenge():
    db = get_db()
    # Check for active challenge in last 5 hours
    now = datetime.utcnow()
    
    # Force generate if user asks or if none exists
    # We'll use a query param 'refresh=true' for manual refresh if needed
    force_refresh = request.args.get('refresh') == 'true'
    
    existing = db.daily_challenges.find_one({
        "expires_at": {"$gt": now},
        "is_active": True
    })

    # Check if user already completed this challenge
    user_id = get_jwt_identity()
    print(f"[🔍] Daily Challenge Request - User ID: {user_id}")
    has_completed = db.challenge_attempts.find_one({"user_id": user_id, "challenge_id": str(existing['_id']) if existing else ""}) is not None
    
    if not force_refresh:
        if existing:
            existing['_id'] = str(existing['_id'])
            existing['has_completed'] = has_completed
            if 'expires_at' in existing:
                existing['expires_at'] = existing['expires_at'].isoformat() + "Z"
            return jsonify(existing)
    
    try:
        # Generate new
        questions, subject = generate_questions(20, None, is_gate=True)
        
        # Ensure we got at least some questions
        if not questions:
            return jsonify({"error": "Failed to generate questions. AI returned empty list. Please try again."}), 500
    except Exception as e:
        print(f"[❌] Challenge Generation Exception: {e}")
        return jsonify({"error": f"Internal Error: {str(e)}"}), 500
        
    new_challenge = {
        "challenge_id": f"daily_{now.strftime('%Y%m%d%H')}",
        "subject": subject,
        "questions": questions,
        "generated_at": now,
        "expires_at": now + timedelta(hours=5),
        "is_active": True
    }
    
    res = db.daily_challenges.insert_one(new_challenge)
    new_challenge['_id'] = str(res.inserted_id)
    new_challenge['has_completed'] = False
    new_challenge['expires_at'] = new_challenge['expires_at'].isoformat() + "Z"
    new_challenge['generated_at'] = new_challenge['generated_at'].isoformat() + "Z"
    return jsonify(new_challenge)

@challenge_bp.route('/history', methods=['GET'])
@jwt_required()
def get_challenge_history():
    db = get_db()
    user_id = get_jwt_identity()
    print(f"[🔍] History Request - User ID: {user_id}")
    
    # Search for both string and ObjectId user_id to handle potential legacy data
    query = {"$or": [{"user_id": user_id}, {"user_id": ObjectId(user_id)}]}
    attempts = list(db.challenge_attempts.find(query).sort("submitted_at", -1).limit(10))
    for a in attempts:
        a['_id'] = str(a['_id'])
        if 'submitted_at' in a:
            a['submitted_at'] = a['submitted_at'].isoformat() + "Z"
        if 'started_at' in a:
            a['started_at'] = a['started_at'].isoformat() + "Z"
        # Try to find the subject
        if a['type'] == 'daily':
            c = db.daily_challenges.find_one({"_id": ObjectId(a['challenge_id'])})
            a['subject'] = c['subject'] if c else "Daily Challenge"
        else:
            a['subject'] = "Module Assessment"
            
    return jsonify(attempts)

@challenge_bp.route('/generate-assessment', methods=['POST'])
@jwt_required()
def generate_assessment():
    db = get_db()
    data = request.json
    module_id = data.get('module_id')
    
    if not module_id: return jsonify({"error": "module_id required"}), 400
    
    # Find the marker
    marker = db.assessments.find_one({"module_id": module_id})
    if not marker:
        return jsonify({"error": "No assessment found for this module. Please complete the module first."}), 404
        
    if marker.get('is_active'):
        marker['_id'] = str(marker['_id'])
        return jsonify(marker)
    
    # Generate 20 questions using Groq
    # We use the module_title as the subject context
    questions, _ = generate_questions(20, marker.get('module_title', 'Technical Module'))
    
    db.assessments.update_one(
        {"_id": marker['_id']},
        {
            "$set": {
                "questions": questions,
                "is_active": True,
                "generated_at": datetime.utcnow()
            }
        }
    )
    
    marker['questions'] = questions
    marker['is_active'] = True
    marker['_id'] = str(marker['_id'])
    return jsonify(marker)

@challenge_bp.route('/pending-assessments', methods=['GET'])
@jwt_required()
def get_pending_assessments():
    db = get_db()
    user_id = get_jwt_identity()
    
    # Modules completed by user
    # Search for both string and ObjectId user_id
    query = {"$or": [{"user_id": user_id}, {"user_id": ObjectId(user_id)}]}
    progress = db.course_progress.find_one(query) or {}
    completed_modules = progress.get("completed_modules", [])
    
    # User attempts for assessments
    attempts = list(db.challenge_attempts.find({"$and": [query, {"type": "assessment"}]}))
    attempted_ids = [str(a['challenge_id']) for a in attempts]
    
    # All assessments for these modules
    all_assessments = list(db.assessments.find({"module_id": {"$in": completed_modules}}))
    
    pending = []
    completed = []
    
    for a in all_assessments:
        a_id = str(a['_id'])
        a['_id'] = a_id
        
        # Check if user has attempted this
        user_att = next((att for att in attempts if str(att['challenge_id']) == a_id), None)
        
        if user_att:
            a['attempt'] = {
                "score": user_att.get('score'),
                "total": user_att.get('total'),
                "percentage": user_att.get('percentage'),
                "submitted_at": user_att.get('submitted_at').isoformat() + "Z" if user_att.get('submitted_at') else None
            }
            completed.append(a)
        else:
            pending.append(a)
            
    return jsonify({
        "pending": pending,
        "completed": completed
    })

@challenge_bp.route('/submit', methods=['POST'])
@jwt_required()
def submit_challenge():
    db = get_db()
    user_id = get_jwt_identity()
    data = request.json
    
    challenge_id = data.get('challenge_id')
    c_type = data.get('type') # daily / assessment
    user_answers = data.get('answers', {}) # {qid: [indices]}
    violations = data.get('violations', 0)
    auto_submitted = data.get('auto_submitted', False)
    
    # Fetch questions
    if c_type == 'daily':
        challenge = db.daily_challenges.find_one({"_id": ObjectId(challenge_id)})
    else:
        challenge = db.assessments.find_one({"_id": ObjectId(challenge_id)})
        
    if not challenge: return jsonify({"error": "Challenge not found"}), 404
    
    questions = challenge['questions']
    results = []
    score = 0
    total = len(questions)
    
    for q in questions:
        qid = q['id']
        correct = q['correct_answers']
        user_sel = user_answers.get(qid, [])
        
        # Scoring logic
        is_correct = False
        if q['type'] == 'mcq':
            is_correct = (len(user_sel) == 1 and user_sel[0] in correct)
        else: # msq
            is_correct = (set(user_sel) == set(correct))
            
        if is_correct: score += 1
        
        results.append({
            "id": qid,
            "correct": is_correct,
            "user_sel": user_sel,
            "correct_sel": correct,
            "explanation": q.get("explanation", "")
        })
        
    percentage = round((score / total) * 100, 2) if total > 0 else 0
    
    points_gained = score * (10 if c_type == 'daily' else 25)
    
    attempt = {
        "user_id": user_id,
        "challenge_id": challenge_id,
        "type": c_type,
        "answers": user_answers,
        "score": score,
        "total": total,
        "percentage": percentage,
        "points_gained": points_gained,
        "started_at": datetime.utcnow() - timedelta(minutes=15), # Approximate
        "submitted_at": datetime.utcnow(),
        "proctoring_violations": violations,
        "auto_submitted": auto_submitted
    }
    
    db.challenge_attempts.insert_one(attempt)
    
    # Update points
    point_field = "daily_challenge_points" if c_type == 'daily' else "assessment_points"
    db.users.update_one({"_id": ObjectId(user_id)}, {"$inc": {point_field: points_gained, "xp": points_gained}})
    
    return jsonify({
        "status": "success",
        "score": score,
        "total": total,
        "percentage": percentage,
        "points_gained": points_gained,
        "results": results
    })

@challenge_bp.route('/proctor-check', methods=['POST'])
@jwt_required()
def proctor_check():
    data = request.json
    image_b64 = data.get('image') # Base64
    
    if not image_b64: return jsonify({"violation": False, "reason": "No image"})
    
    # Vision check via OpenRouter
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key: return jsonify({"violation": False, "reason": "Vision AI offline"})
    
    try:
        # Standard OpenRouter payload for vision
        prompt = """
        EXAM PROCTORING: Analyze this webcam frame. Respond with JSON only. 
        Detect violations: 
        1) Multiple people in frame. 
        2) User looking away. 
        3) Electronic devices visible (phones, tablets, smartwatches, headphones).
        4) Low light or No light (cannot see user clearly).
        5) User not visible/frame is blocked.
        
        If any suspicious activity is found, set 'violation' to true and give a specific 'reason'. 
        If everything is fine, 'violation' is false and 'reason' is empty.
        JSON Format: { "violation": boolean, "reason": string }
        """
        
        # Handle base64 format (strip prefix if exists)
        if "," in image_b64: image_b64 = image_b64.split(",")[1]
        
        payload = {
            "model": "stepfun/step-3.5-flash:free",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                    ]
                }
            ],
            "max_tokens": 300
        }
        
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        print(f"[🛡️] Proctoring model: stepfun/step-3.5-flash:free")
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=15)
        
        if response.ok:
            content = response.json()['choices'][0]['message']['content']
            print(f"[🛡️] AI Response: {content}")
            if "```" in content: content = content.split("```")[1].replace("json", "").strip()
            res = json.loads(content)
            return jsonify(res)
        else:
            print(f"[🛡️] API Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"[🛡️] Proctor Check Exception: {e}")
        
    return jsonify({"violation": False, "reason": "Check skipped"})
