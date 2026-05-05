import os
import json
import logging
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
import PyPDF2
import google.generativeai as genai

logger = logging.getLogger(__name__)
revision_bp = Blueprint('revision', __name__)

def _clean_json(text):
    text = text.strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    return text.strip()

def _groq(messages, max_tokens=1000, temp=0.2):
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key: raise Exception("Missing GROQ_API_KEY")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": "llama-3.1-8b-instant", "messages": messages, "max_tokens": max_tokens, "temperature": temp},
        timeout=30
    )
    if not r.ok: raise Exception(r.text)
    return r.json()["choices"][0]["message"]["content"]

def _gemini_explain(topics_json):
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key: return topics_json
    
    prompt = (
        "You are an expert tutor. I have extracted some key topics for revision. "
        "Return the EXACT SAME JSON array, but enhance the 'explanation' field for each topic "
        "to be a brief, concise summary of EXACTLY 2 sentences. "
        "Output ONLY a valid JSON object with a 'topics' array key."
        f"\n\nTopics:\n{json.dumps(topics_json)}"
    )
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }
        r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=30)
        
        if r.ok:
            data = r.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(_clean_json(content))
            new_topics = parsed.get("topics", []) if isinstance(parsed, dict) else parsed
            
            # Safely merge explanations back to avoid losing other fields
            if isinstance(new_topics, list):
                # Try to map by topic name to be safe
                exp_map = {str(t.get("topic", "")).lower(): t.get("explanation", "") for t in new_topics if isinstance(t, dict)}
                for t in topics_json:
                    name = str(t.get("topic", "")).lower()
                    if name in exp_map and exp_map[name]:
                        t["explanation"] = exp_map[name]
                return topics_json
    except Exception as e:
        logger.error("Gemini explain failed: %s", e)
    return topics_json

def _openrouter_explain(topics_json):
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key: return topics_json
    
    prompt = (
        "You are an expert tutor. I have extracted some key topics for revision. "
        "Return the EXACT SAME JSON array, but enhance the 'explanation' field for each topic "
        "to be a brief, high-level overview of EXACTLY 2 sentences. "
        "Output ONLY a valid JSON object with a 'topics' array key."
        f"\n\nTopics:\n{json.dumps(topics_json)}"
    )
    
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5000",
            "X-Title": "AI Learning Assistant"
        }
        payload = {
            "model": "nvidia/nemotron-nano-12b-v2-vl:free", # Fast NVIDIA model as requested
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4
        }
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if r.ok:
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            print(f"OpenRouter Response Success.") # Debug
            parsed = json.loads(_clean_json(content))
            new_topics = parsed.get("topics", []) if isinstance(parsed, dict) else parsed
            
            if isinstance(new_topics, list):
                exp_map = {str(t.get("topic", "")).lower(): t.get("explanation", "") for t in new_topics if isinstance(t, dict)}
                for t in topics_json:
                    name = str(t.get("topic", "")).lower()
                    if name in exp_map and exp_map[name]:
                        t["explanation"] = exp_map[name]
                return topics_json
        else:
            print(f"OpenRouter Error: {r.status_code} - Falling back to Gemini.") 
            return _gemini_explain(topics_json) # SILENT FALLBACK
    except Exception as e:
        logger.error("OpenRouter explain failed, falling back: %s", e)
        return _gemini_explain(topics_json) # SILENT FALLBACK
    return topics_json

ANALYZE_SYS = """
You are a strict JSON generator.
Analyze the provided study material and extract key topics.
IMPORTANT: Assign "priority" (High, Medium, Low) based STRICTLY on the ESTIMATED FREQUENCY of questions asked from this topic in standard examinations (GATE, UPSC, University exams, etc.). 
If a topic is a core examiner favorite, set priority to "High".

Return ONLY valid JSON.
Do NOT include any explanation, text, markdown, or code blocks.
Do NOT write anything before or after JSON.

Follow this EXACT structure:

{
  "overview": "(Generate a 2-3 sentence subject overview here)",
  "topics": [
    {
      "topic": "(Generate Topic Name here)",
      "importance_score": 8,
      "priority": "High", 
      "explanation": "",
      "key_points": ["point 1", "point 2"],
      "estimated_hours": 2
    }
  ],
  "dependency_structure": {
    "overview": "How concepts connect",
    "foundational": [
      {
        "name": "Concept",
        "level": "Foundational",
        "importance": 9,
        "why_it_matters": "short explanation",
        "key_terms": ["t1"],
        "depends_on": []
      }
    ],
    "intermediate": [],
    "advanced": [],
    "learning_sequence": ["Concept 1"]
  }
}

NOTE: You MUST generate AT LEAST 15 topics if the input allows it! Include a mix of priorities (High, Medium, Low). To save tokens, leave the "explanation" field as an empty string "".
"""

def extract_text_from_file(file):
    if file.filename.endswith(".pdf"):
        reader = PyPDF2.PdfReader(file)
        return "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
    return file.read().decode('utf-8', errors='ignore')

@revision_bp.route("/analyze", methods=["POST"])
@jwt_required()
def analyze_document():
    text_prompt = request.form.get("text_prompt", "").strip()
    file = request.files.get("file")
    
    text = ""
    
    if text_prompt:
        text = text_prompt
    elif file:
        try:
            text = extract_text_from_file(file)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    else:
        return jsonify({"error": "No file or text provided"}), 400

    try:
        if len(text.strip()) < 3:
            return jsonify({"error": "Input too short. Please provide at least a few words."}), 400

        truncated = text[:4000]
        raw = _groq([
            {"role": "system", "content": ANALYZE_SYS},
            {"role": "user",   "content": f"Analyze this text and extract at least 15 topics:\n\n{truncated}"}
        ], max_tokens=3000, temp=0.2)

        parsed = json.loads(_clean_json(raw))
        topics = parsed.get("topics", [])
        
        # TRI-API PIPELINE: Shift more load to OpenRouter (80/20 split)
        if topics:
            split_idx = int(len(topics) * 0.8) # 80% to OpenRouter
            half1 = topics[:split_idx]
            half2 = topics[split_idx:]
            
            # OpenRouter handles the majority
            if half1:
                half1 = _openrouter_explain(half1)
            
            # Gemini handles the rest
            if half2:
                half2 = _gemini_explain(half2)
            topics = half1 + half2
            print(f"Total topics after Tri-API merge: {len(topics)}") # Debug

        return jsonify({
            "overview": parsed.get("overview", "Overview available."),
            "topics": topics,
            "dependency_structure": parsed.get("dependency_structure", {})
        })
    except Exception as e:
        logger.error("Analyze error: %s", e)
        return jsonify({"error": "Failed to analyze document."}), 500

@revision_bp.route('/chat', methods=['POST'])
def revision_chat():
    data = request.json
    message = data.get("message", "")
    context = data.get("context", "") # Optional topic context
    
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return jsonify({"error": "OpenRouter API Key not found"}), 500
        
    prompt = f"Context: {context}\n\nUser Question: {message}\n\nExpert Answer:"
    
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5000",
            "X-Title": "AI Learning Assistant"
        }
        payload = {
            "model": "openrouter/free",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        if r.ok:
            resp = r.json()
            answer = resp["choices"][0]["message"]["content"]
            return jsonify({"answer": answer})
        else:
            return jsonify({"error": f"OpenRouter failed: {r.status_code}"}), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@revision_bp.route('/masterclass', methods=['POST'])
def revision_masterclass():
    data = request.json
    topic = data.get("topic", "")
    
    # Prompt for OpenRouter (Exhaustive Deep Explanation)
    exp_prompt = (
        f"Provide an EXTREMELY exhaustive, masterclass-level deep-dive explanation of '{topic}' "
        "consisting of AT LEAST 30-40 detailed lines. "
        "Cover every technical nuance, practical implementation step, common pitfalls, and advanced applications. "
        "Format with clear headings (using bold text) and bulleted deep-dives where appropriate. "
        "Do NOT be brief. I need a complete, verbose masterclass."
    )
    
    try:
        # Get Explanation from OpenRouter (NVIDIA Nemotron is fast and supports long context)
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "Content-Type": "application/json",
            "X-Title": "AI Learning Assistant"
        }
        payload = {
            "model": "nvidia/nemotron-nano-12b-v2-vl:free",
            "messages": [{"role": "user", "content": exp_prompt}],
            "temperature": 0.4
        }
        r = requests.post(url, headers=headers, json=payload, timeout=40)
        explanation = r.json()["choices"][0]["message"]["content"] if r.ok else "Failed to generate explanation."
        
        return jsonify({
            "explanation": explanation
        })
    except Exception as e:
        logger.error("Masterclass failed: %s", e)
        return jsonify({"error": str(e)}), 500
