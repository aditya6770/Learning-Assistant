"""
Database Setup Script
─────────────────────
Creates MongoDB indexes for optimal performance.
Run once before first launch:  python database/setup_db.py
"""
from pymongo import MongoClient, ASCENDING, DESCENDING, TEXT
import os

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/ai_learning_db")


def setup():
    client = MongoClient(MONGO_URI)
    db     = client.get_default_database()
    print(f"Connected to: {db.name}")

    # ── users ────────────────────────────────────────────────────────────────
    db.users.create_index([("email", ASCENDING)], unique=True)
    db.users.create_index([("username", ASCENDING)], unique=True)
    print("✓ users indexes")

    # ── documents ────────────────────────────────────────────────────────────
    db.documents.create_index([("user_id", ASCENDING)])
    db.documents.create_index([("uploaded_at", DESCENDING)])
    db.documents.create_index([("content_text", TEXT), ("original_name", TEXT)])
    print("✓ documents indexes")

    # ── quizzes ──────────────────────────────────────────────────────────────
    db.quizzes.create_index([("user_id", ASCENDING)])
    db.quizzes.create_index([("document_id", ASCENDING)])
    db.quizzes.create_index([("created_at", DESCENDING)])
    print("✓ quizzes indexes")

    # ── quiz_attempts ────────────────────────────────────────────────────────
    db.quiz_attempts.create_index([("user_id", ASCENDING)])
    db.quiz_attempts.create_index([("quiz_id", ASCENDING)])
    db.quiz_attempts.create_index([("completed_at", DESCENDING)])
    db.quiz_attempts.create_index([("user_id", ASCENDING), ("completed_at", DESCENDING)])
    print("✓ quiz_attempts indexes")

    # ── emotion_logs ─────────────────────────────────────────────────────────
    db.emotion_logs.create_index([("user_db_id", ASCENDING)])
    db.emotion_logs.create_index([("logged_at", DESCENDING)])
    print("✓ emotion_logs indexes")

    # ── recommendations ──────────────────────────────────────────────────────
    db.recommendations.create_index([("user_id", ASCENDING)])
    db.recommendations.create_index([("generated_at", DESCENDING)])
    print("✓ recommendations indexes")

    print("\n🎉 Database setup complete!")
    client.close()


if __name__ == "__main__":
    setup()
