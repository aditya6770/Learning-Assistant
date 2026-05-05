"""
Authentication Routes — /api/auth
  POST /register
  POST /login
  POST /logout
  GET  /profile
  PUT  /profile
"""
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, jwt_required,
    get_jwt_identity, get_jwt
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from bson import ObjectId
import re

auth_bp = Blueprint("auth", __name__)

# ── helpers ────────────────────────────────────────────────────────────────────
def get_db():
    from flask_pymongo import PyMongo
    from app import mongo
    return mongo.db


def user_to_dict(user):
    user["_id"] = str(user["_id"])
    user.pop("password_hash", None)
    # Ensure profile fields exist
    if "profile" not in user:
        user["profile"] = {"avatar": "", "bio": "", "links": {}, "skills": []}
    return user


# ── Register ───────────────────────────────────────────────────────────────────
@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    username  = data.get("username", "").strip()
    email     = data.get("email", "").strip().lower()
    password  = data.get("password", "")
    lang      = data.get("preferred_language", "en")

    # Validation
    if not username or not email or not password:
        return jsonify({"error": "username, email and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"error": "Invalid email address"}), 400

    db = get_db()
    if db.users.find_one({"email": email}):
        return jsonify({"error": "Email already registered"}), 409
    if db.users.find_one({"username": username}):
        return jsonify({"error": "Username already taken"}), 409

    user_doc = {
        "username": username,
        "email": email,
        "password_hash": generate_password_hash(password),
        "preferred_language": lang,
        "learning_style": "visual",
        "profile": {
            "avatar": "", 
            "bio": "I'm a passionate learner using AI to master new skills.", 
            "links": {"linkedin": "", "github": "", "leetcode": "", "portfolio": ""},
            "skills": []
        },
        "created_at": datetime.utcnow(),
        "last_login": datetime.utcnow(),
    }
    result = db.users.insert_one(user_doc)
    user_doc["_id"] = str(result.inserted_id)
    user_doc.pop("password_hash")

    token = create_access_token(identity=str(result.inserted_id))
    return jsonify({"message": "Registration successful", "token": token, "user": user_doc}), 201


# ── Login ──────────────────────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["POST"])
def login():
    data     = request.get_json()
    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    db   = get_db()
    user = db.users.find_one({"email": email})

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid credentials"}), 401

    db.users.update_one({"_id": user["_id"]}, {"$set": {"last_login": datetime.utcnow()}})

    token = create_access_token(identity=str(user["_id"]))
    return jsonify({
        "message": "Login successful",
        "token": token,
        "user": user_to_dict(user)
    }), 200


# ── Profile GET / PUT ──────────────────────────────────────────────────────────
@auth_bp.route("/profile", methods=["GET"])
@jwt_required()
def get_profile():
    user_id = get_jwt_identity()
    db      = get_db()
    user    = db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify(user_to_dict(user)), 200


@auth_bp.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    user_id = get_jwt_identity()
    data    = request.get_json()

    update  = {}
    # Top level fields
    if "username" in data: update["username"] = data["username"]
    
    # Profile sub-fields
    if "profile" in data:
        p = data["profile"]
        if "bio" in p: update["profile.bio"] = p["bio"]
        if "avatar" in p: update["profile.avatar"] = p["avatar"]
        if "skills" in p: update["profile.skills"] = p["skills"]
        if "links" in p:
            for link_key in ["linkedin", "github", "leetcode", "portfolio"]:
                if link_key in p["links"]:
                    update[f"profile.links.{link_key}"] = p["links"][link_key]

    if not update:
        return jsonify({"error": "No valid fields to update"}), 400

    db = get_db()
    db.users.update_one({"_id": ObjectId(user_id)}, {"$set": update})
    user = db.users.find_one({"_id": ObjectId(user_id)})
    return jsonify(user_to_dict(user)), 200
