"""
Learning Routes — /api/learning
  POST /upload           Upload PDF / notes
  GET  /documents        List user's documents
  GET  /document/<id>    Get document detail + summary
  DELETE /document/<id>  Delete document
  POST /ask              Ask question about a document
  POST /summarize/<id>   Re-summarize a document
  GET  /recommendations  Get personalized recommendations
  POST /translate        Translate text snippet
"""
import os, uuid, logging
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from bson import ObjectId

from ml_models.nlp_engine import (
    extract_text_from_pdf, summarize_text, summarize_text_groq,
    answer_question, extract_key_topics, translate_text
)
from ml_models.recommendation_engine import generate_recommendations

logger = logging.getLogger(__name__)
learning_bp = Blueprint("learning", __name__)

ALLOWED_EXT = {"pdf", "txt", "md"}


def get_db():
    from app import mongo
    return mongo.db


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


# ── Upload Document ───────────────────────────────────────────────────────────
@learning_bp.route("/upload", methods=["POST"])
@jwt_required()
def upload_document():
    user_id = get_jwt_identity()

    if "file" not in request.files:
        return jsonify({"error": "No file part in request"}), 400

    file = request.files["file"]
    if file.filename == "" or not _allowed(file.filename):
        return jsonify({"error": "Invalid or unsupported file type"}), 400

    ext    = file.filename.rsplit(".", 1)[1].lower()
    unique = f"{uuid.uuid4().hex}.{ext}"
    safe   = secure_filename(unique)

    # ── Ensure upload folder exists ──
    upload_folder = current_app.config.get("UPLOAD_FOLDER", "/tmp/uploads")
    os.makedirs(upload_folder, exist_ok=True)
    path = os.path.join(upload_folder, safe)

    # ── Debug logging ──
    logger.warning(f"[UPLOAD] Upload folder: {upload_folder}")
    logger.warning(f"[UPLOAD] Saving to: {path}")
    logger.warning(f"[UPLOAD] Folder exists: {os.path.exists(upload_folder)}")

    try:
        file.save(path)
    except Exception as e:
        logger.error(f"[UPLOAD] File save failed: {e}")
        return jsonify({"error": f"File save failed: {str(e)}"}), 500

    # ── Verify file saved correctly ──
    if not os.path.exists(path):
        logger.error(f"[UPLOAD] File not found after save: {path}")
        return jsonify({"error": "File could not be saved on server"}), 500

    file_size = os.path.getsize(path)
    logger.warning(f"[UPLOAD] File saved. Size: {file_size} bytes")

    if file_size == 0:
        os.remove(path)
        return jsonify({"error": "Uploaded file is empty"}), 422

    # ── Extract text ──
    content = ""
    if ext == "pdf":
        logger.warning(f"[UPLOAD] Extracting PDF text...")
        content = extract_text_from_pdf(path)
        logger.warning(f"[UPLOAD] Extracted {len(content)} chars from PDF")
    else:
        try:
            with open(path, "r", errors="ignore") as f:
                content = f.read()
            logger.warning(f"[UPLOAD] Read {len(content)} chars from text file")
        except Exception as e:
            logger.error(f"[UPLOAD] Text file read failed: {e}")

    if not content or len(content.strip()) < 10:
        logger.error(f"[UPLOAD] Content extraction failed. Content: '{content[:100] if content else 'EMPTY'}'")
        try:
            os.remove(path)
        except:
            pass
        return jsonify({"error": "Could not extract text from file"}), 422

    # ── Summarize + extract topics ──
    logger.warning(f"[UPLOAD] Summarizing {len(content)} chars...")
    try:
        summary = summarize_text(content)
    except Exception as e:
        logger.error(f"[UPLOAD] Summarization failed: {e}")
        summary = content[:500]

    try:
        topics = extract_key_topics(content)
    except Exception as e:
        logger.error(f"[UPLOAD] Topic extraction failed: {e}")
        topics = []

    logger.warning(f"[UPLOAD] Summary length: {len(summary)}, Topics: {topics}")

    doc = {
        "user_id":       user_id,
        "filename":      safe,
        "original_name": file.filename,
        "file_path":     path,
        "content_text":  content[:50000],
        "language":      request.form.get("language", "en"),
        "summary":       summary,
        "key_topics":    topics,
        "uploaded_at":   __import__("datetime").datetime.utcnow(),
    }

    db  = get_db()
    res = db.documents.insert_one(doc)
    doc["_id"] = str(res.inserted_id)
    doc.pop("file_path", None)
    doc.pop("content_text", None)

    logger.warning(f"[UPLOAD] Document saved to DB with id: {doc['_id']}")
    return jsonify({"message": "Document uploaded successfully", "document": doc}), 201


# ── List Documents ────────────────────────────────────────────────────────────
@learning_bp.route("/documents", methods=["GET"])
@jwt_required()
def list_documents():
    user_id = get_jwt_identity()
    db      = get_db()
    docs    = list(db.documents.find(
        {"user_id": user_id},
        {"content_text": 0, "file_path": 0}
    ))
    for d in docs:
        d["_id"] = str(d["_id"])
    return jsonify({"documents": docs}), 200


# ── Get Document ──────────────────────────────────────────────────────────────
@learning_bp.route("/document/<doc_id>", methods=["GET"])
@jwt_required()
def get_document(doc_id):
    user_id = get_jwt_identity()
    db      = get_db()
    doc     = db.documents.find_one(
        {"_id": ObjectId(doc_id), "user_id": user_id},
        {"content_text": 0, "file_path": 0}
    )
    if not doc:
        return jsonify({"error": "Document not found"}), 404
    doc["_id"] = str(doc["_id"])
    return jsonify(doc), 200


# ── Get Document Content ──────────────────────────────────────────────────────
@learning_bp.route("/document/<doc_id>/content", methods=["GET"])
@jwt_required()
def get_document_content(doc_id):
    user_id = get_jwt_identity()
    db      = get_db()
    doc     = db.documents.find_one(
        {"_id": ObjectId(doc_id), "user_id": user_id},
        {"content_text": 1, "original_name": 1}
    )
    if not doc:
        return jsonify({"error": "Document not found"}), 404
    return jsonify({
        "original_name": doc.get("original_name"),
        "content_text":  doc.get("content_text")
    }), 200


# ── Delete Document ───────────────────────────────────────────────────────────
@learning_bp.route("/document/<doc_id>", methods=["DELETE"])
@jwt_required()
def delete_document(doc_id):
    user_id = get_jwt_identity()
    db      = get_db()
    doc     = db.documents.find_one({"_id": ObjectId(doc_id), "user_id": user_id})
    if not doc:
        return jsonify({"error": "Document not found"}), 404
    try:
        if os.path.exists(doc.get("file_path", "")):
            os.remove(doc["file_path"])
    except Exception:
        pass
    db.documents.delete_one({"_id": ObjectId(doc_id)})
    return jsonify({"message": "Document deleted"}), 200


# ── Ask Question ──────────────────────────────────────────────────────────────
@learning_bp.route("/ask", methods=["POST"])
@jwt_required()
def ask_question():
    user_id  = get_jwt_identity()
    data     = request.get_json()
    doc_id   = data.get("document_id")
    question = data.get("question", "").strip()
    lang     = data.get("language", "en")

    if not doc_id or not question:
        return jsonify({"error": "document_id and question are required"}), 400

    db  = get_db()
    doc = db.documents.find_one({"_id": ObjectId(doc_id), "user_id": user_id})
    if not doc:
        return jsonify({"error": "Document not found"}), 404

    context = doc.get("content_text", "")
    result  = answer_question(question, context)

    if lang != "en" and result.get("answer"):
        result["answer"] = translate_text(result["answer"], target_lang=lang)

    return jsonify({
        "question":    question,
        "answer":      result.get("answer", ""),
        "confidence":  result.get("score", 0),
        "document_id": doc_id,
    }), 200


# ── Summarize ─────────────────────────────────────────────────────────────────
@learning_bp.route("/summarize/<doc_id>", methods=["POST"])
@jwt_required()
def summarize_document(doc_id):
    user_id = get_jwt_identity()
    db      = get_db()
    doc     = db.documents.find_one({"_id": ObjectId(doc_id), "user_id": user_id})
    if not doc:
        return jsonify({"error": "Document not found"}), 404

    lang    = request.get_json(silent=True, force=True) or {}
    lang    = lang.get("language", "en")
    text    = doc.get("content_text", "")
    summary = summarize_text_groq(text)

    if lang != "en" and summary:
        summary = translate_text(summary, target_lang=lang)

    db.documents.update_one({"_id": ObjectId(doc_id)}, {"$set": {"summary": summary}})
    return jsonify({"summary": summary, "document_id": doc_id}), 200


# ── Recommendations ───────────────────────────────────────────────────────────
@learning_bp.route("/recommendations", methods=["GET"])
@jwt_required()
def recommendations():
    user_id = get_jwt_identity()
    db      = get_db()
    recs    = generate_recommendations(user_id, db)
    return jsonify({"recommendations": recs}), 200


# ── Translation ───────────────────────────────────────────────────────────────
@learning_bp.route("/translate", methods=["POST"])
@jwt_required()
def translate():
    data   = request.get_json()
    text   = data.get("text", "")
    target = data.get("target_language", "en")
    source = data.get("source_language", "en")

    if not text:
        return jsonify({"error": "text is required"}), 400

    translated = translate_text(text, target_lang=target, source_lang=source)
    return jsonify({
        "original":         text,
        "translated":       translated,
        "target_language":  target,
    }), 200
