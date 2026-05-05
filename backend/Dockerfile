FROM python:3.11-slim

# System deps (OpenCV + audio + PDF tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 \
    libgomp1 ffmpeg portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download NLTK data
RUN python -c "import nltk; nltk.download('wordnet'); nltk.download('punkt')"

COPY . .
RUN mkdir -p uploads

EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:app"]
