"""
MongoDB Models / Schema Definitions
All documents live in MongoDB. This module provides helper
classes that wrap collection access and enforce schema shape.
"""
from datetime import datetime
from bson import ObjectId


class UserModel:
    """
    users collection
    {
        _id, username, email, password_hash,
        preferred_language, learning_style,
        created_at, last_login,
        profile: { avatar, bio, subjects: [] }
    }
    """
    COLLECTION = "users"

    @staticmethod
    def schema(username, email, password_hash, lang="en"):
        return {
            "username": username,
            "email": email,
            "password_hash": password_hash,
            "preferred_language": lang,
            "learning_style": "visual",          # visual | auditory | kinesthetic
            "profile": {"avatar": "", "bio": "", "subjects": []},
            "created_at": datetime.utcnow(),
            "last_login": datetime.utcnow(),
        }


class DocumentModel:
    """
    documents collection — uploaded PDFs / notes
    {
        _id, user_id, filename, original_name,
        file_path, content_text, language,
        summary, key_topics: [],
        uploaded_at
    }
    """
    COLLECTION = "documents"

    @staticmethod
    def schema(user_id, filename, original_name, file_path, content_text, lang="en"):
        return {
            "user_id": user_id,
            "filename": filename,
            "original_name": original_name,
            "file_path": file_path,
            "content_text": content_text,
            "language": lang,
            "summary": "",
            "key_topics": [],
            "uploaded_at": datetime.utcnow(),
        }


class QuizModel:
    """
    quizzes collection
    {
        _id, user_id, document_id, title,
        questions: [
          { id, type, question, options, correct_answer,
            explanation, difficulty }
        ],
        created_at
    }
    """
    COLLECTION = "quizzes"

    @staticmethod
    def schema(user_id, document_id, title, questions):
        return {
            "user_id": user_id,
            "document_id": document_id,
            "title": title,
            "questions": questions,
            "created_at": datetime.utcnow(),
        }


class QuizAttemptModel:
    """
    quiz_attempts collection
    {
        _id, user_id, quiz_id,
        answers: [{ question_id, user_answer, is_correct }],
        score, total_questions, time_taken_seconds,
        emotion_data: { avg_attention, avg_emotion },
        completed_at
    }
    """
    COLLECTION = "quiz_attempts"

    @staticmethod
    def schema(user_id, quiz_id, answers, score, total, time_taken, emotion_data=None):
        return {
            "user_id": user_id,
            "quiz_id": quiz_id,
            "answers": answers,
            "score": score,
            "total_questions": total,
            "percentage": round((score / total) * 100, 2) if total else 0,
            "time_taken_seconds": time_taken,
            "emotion_data": emotion_data or {},
            "completed_at": datetime.utcnow(),
        }


class EmotionLogModel:
    """
    emotion_logs collection — per-session snapshots
    {
        _id, user_id, session_id,
        snapshots: [
          { timestamp, emotion, attention_score, confidence }
        ],
        avg_attention, dominant_emotion,
        logged_at
    }
    """
    COLLECTION = "emotion_logs"

    @staticmethod
    def schema(user_id, session_id, snapshots, avg_attention, dominant_emotion):
        return {
            "user_id": user_id,
            "session_id": session_id,
            "snapshots": snapshots,
            "avg_attention": avg_attention,
            "dominant_emotion": dominant_emotion,
            "logged_at": datetime.utcnow(),
        }


class RecommendationModel:
    """
    recommendations collection
    {
        _id, user_id,
        recommendations: [
          { type, title, url, reason, difficulty }
        ],
        generated_at
    }
    """
    COLLECTION = "recommendations"

    @staticmethod
    def schema(user_id, recommendations):
        return {
            "user_id": user_id,
            "recommendations": recommendations,
            "generated_at": datetime.utcnow(),
        }


class NoteModel:
    """
    notes collection — user-created notes
    {
        _id, user_id, title, content, is_pinned,
        document_id, created_at, updated_at
    }
    """
    COLLECTION = "notes"

    @staticmethod
    def schema(user_id, title, content, document_id=None, is_pinned=False):
        now = datetime.utcnow()
        return {
            "user_id": user_id,
            "title": title,
            "content": content,
            "is_pinned": is_pinned,
            "document_id": document_id,
            "created_at": now,
            "updated_at": now,
        }

