from flask import Flask
from flask_pymongo import PyMongo
import os

app = Flask(__name__)
# Try to find the DB name from app.py or env
app.config['MONGO_URI'] = 'mongodb://127.0.0.1:27017/ai_learning_assistant'
mongo = PyMongo(app)

with app.app_context():
    users = list(mongo.db.users.find({}, {"username": 1, "email": 1}))
    print("ALL USERS:")
    for u in users:
        print(f"Username: {u.get('username')}, Email: {u.get('email')}")
