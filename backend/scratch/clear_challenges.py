import os
from pymongo import MongoClient
from datetime import datetime

# Connect to local MongoDB - CORRECT DB NAME: ai_learning_db
client = MongoClient("mongodb://localhost:27017/")
db = client.ai_learning_db

# 1. Delete all daily challenges to force a fresh 20-question generation with the new 2-min expiry
db.daily_challenges.delete_many({})
print("Deleted all daily challenges from ai_learning_db.")

# 2. Delete challenge attempts so the user isn't marked as 'Completed'
db.challenge_attempts.delete_many({"type": "daily"})
print("Deleted all daily challenge attempts from ai_learning_db.")

# 3. Reset assessments for good measure
db.assessments.update_many({}, {"$set": {"is_active": False, "questions": []}})
print("Reset all assessments in ai_learning_db.")

print("Super Reset Complete. Refresh your browser to see the new 2-minute challenge cycle.")
