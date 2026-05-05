from pymongo import MongoClient
from bson import ObjectId

client = MongoClient("mongodb://localhost:27017/")
db = client.ai_learning_db

print("--- USERS ---")
users = list(db.users.find({}, {"username": 1, "email": 1}))
for u in users:
    print(f"ID: {u['_id']}, Name: {u.get('username')}, Email: {u.get('email')}")

print("\n--- ATTEMPTS ---")
attempts = list(db.challenge_attempts.find().sort("submitted_at", -1).limit(20))
for a in attempts:
    print(f"User: {a['user_id']}, Type: {a['type']}, Score: {a['score']}/{a['total']}, Date: {a['submitted_at']}")
