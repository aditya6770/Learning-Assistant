"""
Notes Routes
"""
import os
import logging
import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime

from models.db_models import NoteModel

logger = logging.getLogger(__name__)
notes_bp = Blueprint('notes', __name__)

def get_db():
    from app import mongo
    return mongo.db

# ── CRUD Operations ──────────────────────────────────────────────────────────

@notes_bp.route('/', methods=['GET'])
@jwt_required()
def get_notes():
    user_id = get_jwt_identity()
    db = get_db()
    # Sort by pinned (True first), then updated_at descending
    notes_cursor = db.notes.find({"user_id": user_id}).sort([("is_pinned", -1), ("updated_at", -1)])
    
    notes = []
    for note in notes_cursor:
        note["_id"] = str(note["_id"])
        if note.get("document_id"): note["document_id"] = str(note["document_id"])
        if "created_at" in note and isinstance(note["created_at"], datetime):
            note["created_at"] = note["created_at"].isoformat()
        if "updated_at" in note and isinstance(note["updated_at"], datetime):
            note["updated_at"] = note["updated_at"].isoformat()
        notes.append(note)
        
    return jsonify({"notes": notes}), 200


@notes_bp.route('/', methods=['POST'])
@jwt_required()
def create_note():
    user_id = get_jwt_identity()
    data = request.get_json()
    
    if not data or not data.get("title") or not data.get("content"):
        return jsonify({"error": "Title and content are required"}), 400
        
    db = get_db()
    note_doc = NoteModel.schema(
        user_id=user_id,
        title=data.get("title"),
        content=data.get("content"),
        document_id=data.get("document_id"),
        is_pinned=data.get("is_pinned", False)
    )
    
    result = db.notes.insert_one(note_doc)
    note_doc["_id"] = str(result.inserted_id)
    
    return jsonify({"message": "Note created", "note": note_doc}), 201


@notes_bp.route('/<note_id>', methods=['PUT'])
@jwt_required()
def update_note(note_id):
    user_id = get_jwt_identity()
    data = request.get_json()
    db = get_db()
    
    update_fields = {"updated_at": datetime.utcnow()}
    if "title" in data: update_fields["title"] = data["title"]
    if "content" in data: update_fields["content"] = data["content"]
    if "document_id" in data: update_fields["document_id"] = data["document_id"]
    if "is_pinned" in data: update_fields["is_pinned"] = data["is_pinned"]
        
    result = db.notes.update_one(
        {"_id": ObjectId(note_id), "user_id": user_id},
        {"$set": update_fields}
    )
    
    if result.matched_count == 0:
        return jsonify({"error": "Note not found"}), 404
        
    return jsonify({"message": "Note updated"}), 200


@notes_bp.route('/<note_id>', methods=['DELETE'])
@jwt_required()
def delete_note(note_id):
    user_id = get_jwt_identity()
    db = get_db()
    
    result = db.notes.delete_one({"_id": ObjectId(note_id), "user_id": user_id})
    if result.deleted_count == 0:
        return jsonify({"error": "Note not found"}), 404
        
    return jsonify({"message": "Note deleted"}), 200


@notes_bp.route('/<note_id>/pin', methods=['PATCH'])
@jwt_required()
def toggle_pin(note_id):
    user_id = get_jwt_identity()
    data = request.get_json()
    is_pinned = data.get("is_pinned", False)
    
    db = get_db()
    result = db.notes.update_one(
        {"_id": ObjectId(note_id), "user_id": user_id},
        {"$set": {"is_pinned": is_pinned, "updated_at": datetime.utcnow()}}
    )
    
    if result.matched_count == 0:
        return jsonify({"error": "Note not found"}), 404
        
    return jsonify({"message": "Pin status updated", "is_pinned": is_pinned}), 200


# ── AI Improvement (DeepSeek & Groq Fallback) ────────────────────────────────

def ask_deepseek(prompt):
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key: raise Exception("DEEPSEEK_API_KEY not set")
    
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are an AI assistant that improves, organizes, and formats student notes clearly. Output ONLY the improved notes in markdown, without any conversational filler."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 1000
    }
    
    resp = requests.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def ask_groq(prompt):
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key: raise Exception("GROQ_API_KEY not set")
    
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": "You are an AI assistant that improves, organizes, and formats student notes clearly. Output ONLY the improved notes in markdown, without any conversational filler."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 1000
    }
    
    resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


@notes_bp.route('/improve', methods=['POST'])
@jwt_required()
def improve_note():
    data = request.get_json()
    content = data.get("content")
    
    if not content:
        return jsonify({"error": "Note content is required"}), 400
        
    prompt = f"Please improve and nicely format the following notes. Fix any typos, organize with bullet points if helpful, and make it concise:\n\n{content}"
    
    improved_content = None
    provider_used = None
    errors = []
    
    # Try DeepSeek first
    try:
        improved_content = ask_deepseek(prompt)
        provider_used = "deepseek"
    except Exception as e:
        logger.warning(f"DeepSeek failed: {e}")
        errors.append(f"DeepSeek: {str(e)}")
        
        # Fallback to Groq
        try:
            improved_content = ask_groq(prompt)
            provider_used = "groq"
        except Exception as e2:
            logger.warning(f"Groq failed: {e2}")
            errors.append(f"Groq: {str(e2)}")
            
    if not improved_content:
        return jsonify({"error": "Both AI providers failed to improve the notes.", "details": errors}), 503
        
    return jsonify({
        "improved_content": improved_content,
        "provider": provider_used
    }), 200
