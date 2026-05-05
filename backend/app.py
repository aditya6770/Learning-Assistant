"""
Personalized Learning Assistant - Main Flask Application
"""
from flask import Flask, render_template
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_pymongo import PyMongo
from datetime import timedelta


import os, warnings, logging

# ── Terminal Cleanup ──────────────────────────────────────────────────────────
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'      # Suppress TensorFlow INFO/WARNING logs
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'     # Disable oneDNN custom operations noise
warnings.filterwarnings('ignore')             # Ignore Python/Package deprecation warnings
logging.getLogger('werkzeug').setLevel(logging.ERROR) # Minimize Flask dev server noise

from dotenv import load_dotenv
load_dotenv()

# Import routes
from routes.auth_routes import auth_bp
from routes.learning_routes import learning_bp
from routes.quiz_routes import quiz_bp
from routes.analytics_routes import analytics_bp
from routes.emotion_routes import emotion_bp
from routes.revision_routes import revision_bp

from routes.notes_routes import notes_bp
from routes.groq_routes import groq_bp
from routes.course_routes import course_bp
from routes.challenge_routes import challenge_bp

app = Flask(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # Disable static file caching during dev
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "mysecretkey123")
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "myjwtsecret456")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)
app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/ai_learning_db")
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB


os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ── Extensions ─────────────────────────────────────────────────────────────────
CORS(app, supports_credentials=True)
jwt = JWTManager(app)
@jwt.unauthorized_loader
def unauthorized_callback(callback):
    return {"error": "Missing or invalid token"}, 401

@jwt.invalid_token_loader
def invalid_token_callback(callback):
    return {"error": "Invalid token"}, 401
mongo = PyMongo(app)

# ── Register Blueprints ────────────────────────────────────────────────────────
app.register_blueprint(auth_bp,      url_prefix="/api/auth")
app.register_blueprint(learning_bp,  url_prefix="/api/learning")
app.register_blueprint(quiz_bp,      url_prefix="/api/quiz")
app.register_blueprint(analytics_bp, url_prefix="/api/analytics")
app.register_blueprint(emotion_bp,   url_prefix="/api/emotion")
app.register_blueprint(revision_bp,  url_prefix="/api/revision")

app.register_blueprint(notes_bp,     url_prefix="/api/notes")
app.register_blueprint(groq_bp, url_prefix="/api/groq")
app.register_blueprint(course_bp, url_prefix="/api/courses")
app.register_blueprint(challenge_bp, url_prefix="/api/challenge")

# ── Health check ───────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return {"status": "ok", "message": "AI Learning Assistant API running"}

# ── Serve Frontend ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.after_request
def add_no_cache_headers(response):
    """Prevent browser from caching static JS/CSS during development."""
    if response.content_type and ("javascript" in response.content_type or "css" in response.content_type):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response



if __name__ == "__main__":
    print("\n" + "═"*50)
    print(" 🚀  AI LEARNING ASSISTANT IS STARTING...")
    print(" 🌐  Local Access: http://127.0.0.1:5000")
    print("═"*50 + "\n")
    app.run(debug=True, host="0.0.0.0", port=5000)