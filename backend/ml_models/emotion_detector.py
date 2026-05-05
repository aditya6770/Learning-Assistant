"""
Emotion & Attention Detection
──────────────────────────────
• Uses OpenCV + a lightweight CNN (FER2013-trained) to detect:
    – Facial expression / emotion (happy, sad, neutral, surprised, angry, …)
    – Attention proxy: eye openness + face presence
• Runs on a single Base64-encoded JPEG frame sent from the browser.

Model: We use the `fer` library (wraps TF/Keras + OpenCV) which downloads
       a pretrained FER2013 model automatically.
Fallback: If `fer` is unavailable we use haar-cascade + a rule-based heuristic.
"""
import base64, logging, cv2, numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)


_face_cascade   = None





def _get_cascade():
    global _face_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    return _face_cascade


# ── Public API ────────────────────────────────────────────────────────────────
def analyze_frame(frame_b64: str) -> dict:
    """
    Accepts a Base64 JPEG string (no data-URL prefix).
    Returns:
        { emotion, attention_score (0-1), confidence, face_detected, timestamp }
    """
    try:
        img = _decode_frame(frame_b64)
    except Exception as e:
        logger.error(f"Frame decode error: {e}")
        return _empty_result()

    # 🔥 DeepFace detection (NEW)
    try:
        from deepface import DeepFace
        result = DeepFace.analyze(
        img,
        actions=['emotion'],
        enforce_detection=False
        )
        if isinstance(result, list):
            result = result[0]

        emotion_data = result.get('emotion', {})
        emotion_data = {k: float(v) for k, v in emotion_data.items()}
        dominant_emotion = result.get('dominant_emotion', 'neutral')

        confidence = float(max(emotion_data.values()) / 100)

        attention_map = {
        "happy": 0.9,
        "neutral": 0.7,
        "surprise": 0.75,
        "sad": 0.4,
        "angry": 0.3,
        "fear": 0.35,
        "disgust": 0.2
         }

        attention_score = float(attention_map.get(dominant_emotion, 0.5))

        print("DEEPFACE EMOTION:", dominant_emotion)
        print("ALL EMOTIONS:", emotion_data)

        return {
            "emotion": str(dominant_emotion),
            "confidence": float(confidence),
            "attention_score": float(attention_score),
            "face_detected": True,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
         print("DeepFace error:", e)
         return _empty_result(face_detected=False)
    

def _decode_frame(b64_str: str) -> np.ndarray:
    # Strip data-URL prefix if present
    if "," in b64_str:
        b64_str = b64_str.split(",")[1]
    img_bytes = base64.b64decode(b64_str)
    arr       = np.frombuffer(img_bytes, dtype=np.uint8)
    img       = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img





def _haar_analyze(img: np.ndarray) -> dict:
    """Fallback: haar cascade face detection, rule-based emotion."""
    gray   = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cascade = _get_cascade()
    faces  = cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))

    if len(faces) == 0:
        return _empty_result(face_detected=False)

    # Crop to first face region and compute simple brightness-based heuristic
    x, y, w, h = faces[0]
    roi        = gray[y:y+h, x:x+w]
    brightness = float(np.mean(roi))

    # Very rough heuristic
    emotion    = "neutral"
    confidence = 0.5
    if brightness > 140:
        emotion = "happy"; confidence = 0.6
    elif brightness < 80:
        emotion = "sad";   confidence = 0.55

    return {
        "emotion": emotion,
        "all_emotions": {emotion: confidence},
        "confidence": confidence,
        "attention_score": _compute_attention(emotion, confidence),
        "face_detected": True,
        "timestamp": datetime.utcnow().isoformat(),
    }


def _compute_attention(emotion: str, confidence: float) -> float:
    """
    Simple proxy for attention:
    - No face  → 0.0
    - Engaged emotions (focused, neutral, surprised) → high score
    - Disengaged (sad, angry, disgusted, fear) → lower score
    """
    base_map = {
        "neutral":   0.75,
        "happy":     0.85,
        "surprised": 0.80,
        "fear":      0.50,
        "sad":       0.40,
        "angry":     0.35,
        "disgusted": 0.30,
    }
    base = base_map.get(emotion, 0.60)
    # Weight by confidence
    return round(min(base * (0.7 + 0.3 * confidence), 1.0), 3)


def _empty_result(face_detected: bool = False) -> dict:
    return {
        "emotion": "unknown",
        "all_emotions": {},
        "confidence": 0.0,
        "attention_score": 0.0,
        "face_detected": face_detected,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Session Aggregation ───────────────────────────────────────────────────────
def aggregate_session(snapshots: list) -> dict:
    """
    Given a list of per-frame results, compute session-level stats.
    """
    if not snapshots:
        return {"avg_attention": 0.0, "dominant_emotion": "unknown", "engagement_level": "low"}

    attentions  = [s.get("attention_score", 0) for s in snapshots]
    emotions    = [s.get("emotion", "unknown") for s in snapshots if s.get("face_detected")]

    avg_attention = round(sum(attentions) / len(attentions), 3) if attentions else 0.0

    # Dominant emotion
    from collections import Counter
    dominant = Counter(emotions).most_common(1)[0][0] if emotions else "unknown"

    engagement = "high" if avg_attention >= 0.7 else ("medium" if avg_attention >= 0.45 else "low")

    return {
        "avg_attention": avg_attention,
        "dominant_emotion": dominant,
        "engagement_level": engagement,
    }
