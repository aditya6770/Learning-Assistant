from pymongo import MongoClient
client = MongoClient("mongodb://localhost:27017/")
db = client.ai_learning_db
user = db.users.find_one({}, {"email": 1})
print(user)
