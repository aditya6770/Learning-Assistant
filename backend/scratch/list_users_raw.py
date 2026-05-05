import pymongo
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["ai_learning_db"]
users = list(db.users.find({}, {"username": 1, "email": 1}))
print("ALL USERS:")
for u in users:
    print(f"Username: {u.get('username')}, Email: {u.get('email')}")
