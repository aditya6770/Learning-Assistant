# 🎓 Personalized Learning Assistant Using Artificial Intelligence
### B.Tech Final Year Project — Complete Implementation Guide

---

## 📋 Project Overview

A full-stack AI-powered personalized learning assistant that adapts to each student's performance, emotions, and learning style. The system combines NLP, computer vision, and adaptive algorithms to deliver a tailored educational experience.

### Core Features

| Feature | Technology Used |
|--------|----------------|
| User Auth & Profiles | JWT, Flask, MongoDB |
| Emotion & Attention Detection | OpenCV, FER (CNN), TensorFlow |
| NLP Question Answering | HuggingFace Transformers (RoBERTa) |
| Document Summarization | Facebook BART-large-CNN |
| Quiz Generation (MCQ, FIB, Desc.) | T5-QG, YAKE, NLTK WordNet |
| Adaptive Recommendations | YouTube API, MIT OCW, Rule-based engine |
| Voice Interaction | SpeechRecognition, gTTS, Whisper (STT/TTS) |
| Analytics Dashboard | Custom charting, MongoDB aggregation |
| Multi-Language Support | Helsinki-NLP MarianMT, googletrans |
| PDF/Notes Processing | PyMuPDF, pdfplumber |

---

## 🗂️ Project Structure

```
ai_learning_assistant/
│
├── backend/                    # Flask REST API
│   ├── app.py                  # Main application entry point
│   ├── requirements.txt        # Python dependencies
│   ├── Dockerfile              # Backend container config
│   ├── .env.example            # Environment variable template
│   ├── uploads/                # Uploaded document storage
│   │
│   ├── routes/
│   │   ├── auth_routes.py      # POST /register, /login, /profile
│   │   ├── learning_routes.py  # /upload, /ask, /summarize, /translate
│   │   ├── quiz_routes.py      # /generate, /submit, /attempts
│   │   ├── analytics_routes.py # /dashboard, /progress, /topics
│   │   ├── emotion_routes.py   # /analyze (frame), /session/end
│   │   └── voice_routes.py     # /stt, /tts
│   │
│   ├── ml_models/
│   │   ├── nlp_engine.py         # PDF extraction, QA, summarization, translation
│   │   ├── quiz_generator.py     # MCQ + FIB + descriptive question generation
│   │   ├── emotion_detector.py   # Real-time emotion/attention via webcam
│   │   └── recommendation_engine.py  # Adaptive learning resource recommendations
│   │
│   └── models/
│       └── db_models.py          # MongoDB document schemas
│
├── frontend/
│   └── templates/
│       └── index.html            # Complete Single Page Application (SPA)
│
├── database/
│   └── setup_db.py               # MongoDB index creation script
│
├── docker-compose.yml            # Full stack container orchestration
├── nginx.conf                    # Reverse proxy config
└── README.md
```

---

## ⚙️ Setup Instructions

### Prerequisites

- Python 3.10 or 3.11
- MongoDB 6.0+ (local) or MongoDB Atlas (cloud)
- Node.js (not required — frontend is pure HTML/JS)
- ffmpeg (required by Whisper for audio processing)
- Webcam (for emotion detection feature)
- Microphone (for voice features)

---

### Option A — Local Development Setup

#### Step 1: Clone & Navigate

```bash
git clone <your-repo-url>
cd ai_learning_assistant
```

#### Step 2: Create Python Virtual Environment

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

#### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

> **Note on PyTorch:** The above installs CPU-only PyTorch.
> For GPU support (NVIDIA), replace with:
> ```bash
> pip install torch --index-url https://download.pytorch.org/whl/cu118
> ```

#### Step 4: Install System Dependencies

**Ubuntu/Debian:**
```bash
sudo apt-get install -y libgl1 libglib2.0-0 ffmpeg portaudio19-dev
```

**macOS:**
```bash
brew install ffmpeg portaudio
```

**Windows:**
- Download ffmpeg from https://ffmpeg.org/download.html and add to PATH
- Install PortAudio from https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio

#### Step 5: Configure Environment Variables

```bash
cp .env.example .env
# Edit .env and set your values:
# - MONGO_URI (local: mongodb://localhost:27017/ai_learning_db)
# - SECRET_KEY (any random string)
# - JWT_SECRET_KEY (any different random string)
# - YOUTUBE_API_KEY (optional, from Google Cloud Console)
```

#### Step 6: Set Up MongoDB

Start MongoDB locally:
```bash
# Ubuntu / macOS
mongod --dbpath /data/db

# Or using systemd
sudo systemctl start mongod
```

Then create indexes:
```bash
python database/setup_db.py
```

#### Step 7: Download NLTK Data

```python
python -c "import nltk; nltk.download('wordnet'); nltk.download('punkt')"
```

#### Step 8: Run the Backend

```bash
cd backend
python app.py
```

Backend will start at: **http://localhost:5000**

#### Step 9: Serve the Frontend

The frontend is a single HTML file. You can open it directly in a browser or serve it:

```bash
# Simple Python server from the frontend/templates directory
cd frontend/templates
python -m http.server 8080
```

Frontend will be at: **http://localhost:8080**

> **Important:** The frontend's API calls assume the backend runs at the same origin or you must update the `API` constant in `index.html` to point to `http://localhost:5000`.

---

### Option B — Docker Compose (Recommended for Demo)

```bash
# From the project root
cp backend/.env.example backend/.env
# Edit backend/.env as needed

docker-compose up --build
```

Access at: **http://localhost** (frontend via Nginx + proxy to Flask)

---

## 🔌 API Reference

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Create new account |
| POST | `/api/auth/login` | Login, returns JWT token |
| GET | `/api/auth/profile` | Get profile (requires JWT) |
| PUT | `/api/auth/profile` | Update profile (requires JWT) |

### Learning

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/learning/upload` | Upload PDF/TXT/MD |
| GET | `/api/learning/documents` | List user documents |
| DELETE | `/api/learning/document/<id>` | Delete document |
| POST | `/api/learning/ask` | Ask question about a document |
| POST | `/api/learning/summarize/<id>` | Get document summary |
| GET | `/api/learning/recommendations` | Personalized recommendations |
| POST | `/api/learning/translate` | Translate text |

### Quiz

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/quiz/generate/<doc_id>` | Generate quiz from document |
| GET | `/api/quiz/list` | List user's quizzes |
| GET | `/api/quiz/<id>` | Get quiz questions |
| POST | `/api/quiz/submit` | Submit answers |
| GET | `/api/quiz/attempts` | List past attempts |
| GET | `/api/quiz/attempt/<id>` | Get attempt detail + grading |

### Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/analytics/dashboard` | Overall stats |
| GET | `/api/analytics/progress?days=30` | Score trend |
| GET | `/api/analytics/topics` | Per-topic mastery |
| GET | `/api/analytics/engagement?days=14` | Emotion/attention trends |

### Emotion & Voice

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/emotion/analyze` | Analyze webcam frame |
| POST | `/api/emotion/session/end` | Save session emotion log |
| POST | `/api/voice/stt` | Speech-to-text |
| POST | `/api/voice/tts` | Text-to-speech |

---

## 🧠 AI Models Used

### 1. Question Answering
- **Model:** `deepset/roberta-base-squad2`
- **Task:** Extractive QA from uploaded documents
- **Framework:** HuggingFace Transformers

### 2. Summarization
- **Model:** `facebook/bart-large-cnn`
- **Task:** Document summarization
- **Framework:** HuggingFace Transformers

### 3. Quiz Generation
- **Model:** `valhalla/t5-small-qg-hl`
- **Task:** Question generation from highlighted text
- **Fallback:** Rule-based pattern matching

### 4. Emotion Detection
- **Library:** `fer` (Facial Expression Recognition)
- **Underlying Model:** CNN trained on FER2013 dataset
- **Framework:** TensorFlow + OpenCV

### 5. Translation
- **Model:** `Helsinki-NLP/opus-mt-{src}-{tgt}`
- **Task:** Text translation between 50+ language pairs
- **Fallback:** googletrans (Google Translate API)

### 6. Speech-to-Text
- **Primary:** Google Web Speech API (via SpeechRecognition library)
- **Fallback:** OpenAI Whisper (base model, runs locally)

### 7. Text-to-Speech
- **Library:** gTTS (Google Text-to-Speech)
- **Languages:** 50+ supported

---

## 🗄️ Database Schema (MongoDB)

### users
```json
{
  "_id": "ObjectId",
  "username": "string",
  "email": "string",
  "password_hash": "string",
  "preferred_language": "en",
  "learning_style": "visual",
  "profile": { "bio": "", "subjects": [], "avatar": "" },
  "created_at": "datetime",
  "last_login": "datetime"
}
```

### documents
```json
{
  "_id": "ObjectId",
  "user_id": "string",
  "filename": "uuid.pdf",
  "original_name": "lecture_notes.pdf",
  "content_text": "extracted text…",
  "language": "en",
  "summary": "AI generated summary…",
  "key_topics": ["machine learning", "neural networks"],
  "uploaded_at": "datetime"
}
```

### quizzes
```json
{
  "_id": "ObjectId",
  "user_id": "string",
  "document_id": "string",
  "title": "Quiz: lecture_notes.pdf",
  "difficulty": "medium",
  "questions": [
    {
      "id": 1,
      "type": "mcq",
      "question": "What is backpropagation?",
      "options": ["Option A", "Option B", "Option C", "Correct"],
      "correct_answer": "Correct",
      "explanation": "Found in sentence: …",
      "difficulty": "medium"
    }
  ],
  "created_at": "datetime"
}
```

### quiz_attempts
```json
{
  "_id": "ObjectId",
  "user_id": "string",
  "quiz_id": "ObjectId",
  "answers": [{ "question_id": 1, "user_answer": "A", "correct_answer": "B", "is_correct": false }],
  "score": 3,
  "total_questions": 5,
  "percentage": 60.0,
  "time_taken_seconds": 120,
  "emotion_data": { "avg_attention": 0.72, "dominant_emotion": "neutral" },
  "completed_at": "datetime"
}
```

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: fitz` | `pip install PyMuPDF` |
| `ModuleNotFoundError: fer` | `pip install fer tensorflow` |
| Camera not working | Check browser permissions; use HTTPS in production |
| Slow model loading | Models download on first use (~1-2 GB); be patient |
| MongoDB connection error | Ensure MongoDB is running: `mongod` |
| `portaudio` error on Windows | Install PyAudio wheel from https://www.lfd.uci.edu/~gohlke/ |
| CORS errors | Ensure Flask-CORS is installed and frontend uses correct API URL |
| TTS fails | `pip install gTTS`; check internet connectivity |

---

## 🚀 Production Deployment

1. Set `FLASK_ENV=production` in `.env`
2. Use strong random values for `SECRET_KEY` and `JWT_SECRET_KEY`
3. Use MongoDB Atlas for managed cloud database
4. Deploy to AWS EC2, Google Cloud Run, or Railway
5. Use Gunicorn (included in requirements) behind Nginx
6. Enable HTTPS (Let's Encrypt / Cloudflare)
7. Store uploads in S3 / Google Cloud Storage (not local filesystem)

---

## 📄 Tech Stack Summary

- **Backend:** Python 3.11, Flask 3, Flask-JWT-Extended, Flask-PyMongo, Flask-CORS
- **Database:** MongoDB 7 (with proper indexes)
- **ML Framework:** PyTorch, TensorFlow (via `fer`)
- **NLP:** HuggingFace Transformers (BART, RoBERTa, T5, MarianMT)
- **CV:** OpenCV, FER library
- **Voice:** SpeechRecognition, gTTS, OpenAI Whisper
- **PDF:** PyMuPDF (fitz), pdfplumber
- **Frontend:** Vanilla HTML5/CSS3/JavaScript (ES2020) — no build step required
- **DevOps:** Docker, Docker Compose, Nginx, Gunicorn
