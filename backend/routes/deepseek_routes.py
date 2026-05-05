"""
DeepSeek AI Routes — /api/deepseek
  POST /chat              Send a message and get a full response
  POST /chat/stream       Streaming response (SSE)
  POST /explain           Explain a concept
  GET  /history           Conversation history
  DELETE /history         Clear history
  GET  /debug             Diagnose API key + connectivity issues
"""
import os
import logging
from flask import Blueprint, request, jsonify, Response, stream_with_context
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime
import requests
import json

logger = logging.getLogger(__name__)
deepseek_bp = Blueprint("deepseek", __name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL   = "deepseek-chat"


def get_api_key():
    """Always read fresh from env so hot-reload picks up changes."""
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def get_db():
    from app import mongo
    return mongo.db


def _build_headers():
    return {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": "application/json",
    }


def _system_prompt(context: str = "") -> str:
    base = (
        "You are an expert AI tutor integrated into a Personalized Learning Assistant. "
        "Your role is to help students understand complex concepts clearly, "
        "provide examples, and guide learners step-by-step. "
        "Be concise yet thorough. Use markdown formatting where helpful. "
        "Always encourage the learner and suggest follow-up topics when appropriate."
    )
    if context:
        base += (
            f"\n\nContext from the student's document:\n\"\"\"\n{context[:4000]}\n\"\"\""
            "\nUse this context to give more relevant answers."
        )
    return base


# ── Debug / Health Check ───────────────────────────────────────────────────────
@deepseek_bp.route("/debug", methods=["GET"])
@jwt_required()
def debug():
    """
    Hit this URL to diagnose your setup:
      curl -H "Authorization: Bearer <jwt>" http://127.0.0.1:5000/api/deepseek/debug
    """
    key = get_api_key()
    result = {
        "key_loaded":   bool(key),
        "key_prefix":   key[:8] + "..." if len(key) > 8 else "(empty)",
        "key_length":   len(key),
        "model":        DEEPSEEK_MODEL,
        "api_url":      DEEPSEEK_API_URL,
        "connectivity": None,
        "api_response": None,
        "error":        None,
    }

    if not key:
        result["error"] = "DEEPSEEK_API_KEY is empty. Check your .env file and restart Flask."
        return jsonify(result), 503

    try:
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers=_build_headers(),
            json={
                "model":    DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": "Say OK"}],
                "max_tokens": 5,
                "stream":   False,
            },
            timeout=15,
        )
        result["connectivity"] = "reachable"
        result["http_status"]  = resp.status_code
        if resp.status_code == 200:
            result["api_response"] = "SUCCESS - API key is valid and working"
        else:
            result["api_response"] = resp.text[:300]
            result["error"] = f"HTTP {resp.status_code} from DeepSeek API"
    except requests.exceptions.ConnectionError:
        result["connectivity"] = "unreachable"
        result["error"] = "Cannot reach api.deepseek.com - check internet/firewall"
    except requests.exceptions.Timeout:
        result["connectivity"] = "timeout"
        result["error"] = "Request timed out after 15s"
    except Exception as e:
        result["connectivity"] = "error"
        result["error"] = str(e)

    return jsonify(result), 200


# ── Chat (non-streaming) ───────────────────────────────────────────────────────
@deepseek_bp.route("/chat", methods=["POST"])
@jwt_required()
def chat():
    key = get_api_key()
    if not key:
        return jsonify({"error": "DEEPSEEK_API_KEY not set. Add it to your .env file and restart Flask."}), 503

    user_id = get_jwt_identity()
    data    = request.get_json() or {}

    message     = (data.get("message") or "").strip()
    doc_id      = data.get("document_id")
    history     = data.get("history", [])
    temperature = float(data.get("temperature", 0.7))
    max_tokens  = int(data.get("max_tokens", 1024))

    if not message:
        return jsonify({"error": "message is required"}), 400

    db      = get_db()
    context = _load_doc_context(db, doc_id, user_id)
    messages = _build_messages(context, history, message)

    payload = {
        "model":       DEEPSEEK_MODEL,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "stream":      False,
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=_build_headers(), json=payload, timeout=60)
    except requests.exceptions.Timeout:
        return jsonify({"error": "DeepSeek API timed out. Try again."}), 504
    except requests.exceptions.ConnectionError as e:
        logger.error("DeepSeek connection error: %s", e)
        return jsonify({"error": "Cannot reach DeepSeek API. Check your internet connection."}), 503
    except Exception as e:
        logger.error("DeepSeek unexpected error: %s", e)
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

    if not resp.ok:
        try:
            err_body = resp.json()
            err_msg  = err_body.get("error", {}).get("message", resp.text)
        except Exception:
            err_msg = resp.text
        logger.error("DeepSeek HTTP %s: %s", resp.status_code, err_msg)
        return jsonify({"error": f"DeepSeek API error ({resp.status_code}): {err_msg}"}), resp.status_code

    try:
        result = resp.json()
        answer = result["choices"][0]["message"]["content"]
        usage  = result.get("usage", {})
    except (KeyError, IndexError, ValueError) as e:
        logger.error("DeepSeek malformed response: %s | body: %s", e, resp.text[:500])
        return jsonify({"error": "Malformed response from DeepSeek API"}), 502

    try:
        db.deepseek_conversations.insert_one({
            "user_id":      user_id,
            "document_id":  doc_id,
            "user_message": message,
            "ai_response":  answer,
            "model":        DEEPSEEK_MODEL,
            "tokens_used":  usage.get("total_tokens", 0),
            "created_at":   datetime.utcnow(),
        })
    except Exception as e:
        logger.warning("Could not save conversation: %s", e)

    return jsonify({
        "answer":            answer,
        "model":             DEEPSEEK_MODEL,
        "tokens_used":       usage.get("total_tokens", 0),
        "prompt_tokens":     usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
    }), 200


# ── Streaming Chat ─────────────────────────────────────────────────────────────
@deepseek_bp.route("/chat/stream", methods=["POST"])
@jwt_required()
def chat_stream():
    key = get_api_key()
    if not key:
        return jsonify({"error": "DEEPSEEK_API_KEY not set."}), 503

    user_id  = get_jwt_identity()
    data     = request.get_json() or {}
    message  = (data.get("message") or "").strip()
    doc_id   = data.get("document_id")
    history  = data.get("history", [])

    if not message:
        return jsonify({"error": "message is required"}), 400

    db       = get_db()
    context  = _load_doc_context(db, doc_id, user_id)
    messages = _build_messages(context, history, message)

    payload = {
        "model":       DEEPSEEK_MODEL,
        "messages":    messages,
        "temperature": float(data.get("temperature", 0.7)),
        "max_tokens":  int(data.get("max_tokens", 1024)),
        "stream":      True,
    }

    def generate():
        try:
            with requests.post(
                DEEPSEEK_API_URL,
                headers=_build_headers(),
                json=payload,
                stream=True,
                timeout=120,
            ) as r:
                if not r.ok:
                    yield f"data: {json.dumps({'error': f'HTTP {r.status_code}'})}\n\n"
                    return
                for line in r.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        if line.startswith("data: "):
                            chunk = line[6:]
                            if chunk == "[DONE]":
                                yield "data: [DONE]\n\n"
                                return
                            try:
                                obj   = json.loads(chunk)
                                delta = obj["choices"][0]["delta"].get("content", "")
                                if delta:
                                    yield f"data: {json.dumps({'content': delta})}\n\n"
                            except Exception:
                                pass
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Explain a concept ──────────────────────────────────────────────────────────
@deepseek_bp.route("/explain", methods=["POST"])
@jwt_required()
def explain():
    key = get_api_key()
    if not key:
        return jsonify({"error": "DEEPSEEK_API_KEY not set. Add it to your .env file and restart Flask."}), 503

    user_id = get_jwt_identity()
    data    = request.get_json() or {}
    concept = (data.get("concept") or "").strip()
    doc_id  = data.get("document_id")
    level   = data.get("level", "intermediate")

    if not concept:
        return jsonify({"error": "concept is required"}), 400

    db      = get_db()
    context = _load_doc_context(db, doc_id, user_id)

    prompt = (
        f"Explain the concept of '{concept}' at a {level} level. "
        "Structure your explanation with: "
        "1) A simple definition, "
        "2) Key points, "
        "3) A real-world example, "
        "4) Common misconceptions (if any), "
        "5) A quick summary. "
        "Use clear, engaging language."
    )

    messages = [
        {"role": "system", "content": _system_prompt(context)},
        {"role": "user",   "content": prompt},
    ]
    payload = {
        "model":       DEEPSEEK_MODEL,
        "messages":    messages,
        "temperature": 0.6,
        "max_tokens":  1500,
        "stream":      False,
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=_build_headers(), json=payload, timeout=60)
    except requests.exceptions.Timeout:
        logger.error("DeepSeek explain timed out")
        return jsonify({"error": "DeepSeek API timed out. Try again."}), 504
    except requests.exceptions.ConnectionError as e:
        logger.error("DeepSeek explain connection error: %s", e)
        return jsonify({"error": "Cannot reach DeepSeek API. Check your internet connection."}), 503
    except Exception as e:
        logger.error("DeepSeek explain unexpected error: %s", e)
        return jsonify({"error": f"Request failed: {str(e)}"}), 500

    if not resp.ok:
        try:
            err_body = resp.json()
            err_msg  = err_body.get("error", {}).get("message", resp.text)
        except Exception:
            err_msg = resp.text
        logger.error("DeepSeek explain HTTP %s: %s", resp.status_code, err_msg)
        return jsonify({"error": f"DeepSeek API error ({resp.status_code}): {err_msg}"}), resp.status_code

    try:
        result = resp.json()
        answer = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        logger.error("DeepSeek explain malformed response: %s | body: %s", e, resp.text[:500])
        return jsonify({"error": "Malformed response from DeepSeek API"}), 502

    return jsonify({"concept": concept, "explanation": answer, "level": level}), 200


# ── History ────────────────────────────────────────────────────────────────────
@deepseek_bp.route("/history", methods=["GET"])
@jwt_required()
def get_history():
    user_id = get_jwt_identity()
    db      = get_db()
    limit   = int(request.args.get("limit", 50))
    convos  = list(db.deepseek_conversations.find(
        {"user_id": user_id},
        {"user_message": 1, "ai_response": 1, "document_id": 1, "tokens_used": 1, "created_at": 1},
        sort=[("created_at", -1)],
        limit=limit,
    ))
    for c in convos:
        c["_id"] = str(c["_id"])
    return jsonify({"history": convos, "count": len(convos)}), 200


@deepseek_bp.route("/history", methods=["DELETE"])
@jwt_required()
def clear_history():
    user_id = get_jwt_identity()
    db      = get_db()
    result  = db.deepseek_conversations.delete_many({"user_id": user_id})
    return jsonify({"message": f"Cleared {result.deleted_count} conversation(s)"}), 200


# ── Internal helpers ───────────────────────────────────────────────────────────
def _load_doc_context(db, doc_id, user_id) -> str:
    if not doc_id:
        return ""
    try:
        doc = db.documents.find_one({"_id": ObjectId(doc_id), "user_id": user_id})
        return doc.get("content_text", "") if doc else ""
    except Exception:
        return ""


def _build_messages(context: str, history: list, message: str) -> list:
    msgs = [{"role": "system", "content": _system_prompt(context)}]
    for turn in history[-20:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            msgs.append({"role": turn["role"], "content": turn["content"]})
    msgs.append({"role": "user", "content": message})
    return msgs