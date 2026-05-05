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
- **Framework:** TensorFlow + OpenC

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
