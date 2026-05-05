"""
Emotion & Attention Detection (Lightweight Mode)
────────────────────────────────────────────────
• Uses OpenCV Haar Cascades for face detection.
• Uses rule-based heuristics for emotion and attention.
• Designed for low-memory (512MB RAM) cloud environments.
"""
import base64, logging, cv2, numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)

_face_cascade = None

def _get_cascade():
    global _face_cascade
    if _face_cascade is None:
        try:
            # Try to load from cv2 data
            _face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
        except:
            logger.error("Could not load Haar Cascade")
    return _face_cascade

def analyze_frame(frame_b64: str) -> dict:
    """
    Lightweight analysis using OpenCV Haar Cascades.
    """
    try:
        img = _decode_frame(frame_b64)
        if img is None: return _empty_result()
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade = _get_cascade()
        
        if cascade is None or cascade.empty():
            return _empty_result(face_detected=False)

        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))

        if len(faces) == 0:
            return _empty_result(face_detected=False)

        # Basic Heuristic Analysis
        x, y, w, h = faces[0]
        roi = gray[y:y+h, x:x+w]
        brightness = float(np.mean(roi))

        # Heuristic mapping
        emotion = "neutral"
        confidence = 0.7
        
        if brightness > 150:
            emotion = "happy"
            confidence = 0.8
        elif brightness < 70:
            emotion = "sad"
            confidence = 0.6

        # Attention score based on face presence + size
        attention_score = min(1.0, (w * h) / (img.shape[0] * img.shape[1] * 0.2))

        return {
            "emotion": emotion,
            "confidence": confidence,
            "attention_score": float(attention_score),
            "face_detected": True,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Lightweight analysis error: {e}")
        return _empty_result(face_detected=False)

def _decode_frame(b64_str: str) -> np.ndarray:
    try:
        if "," in b64_str:
            b64_str = b64_str.split(",")[1]
        img_bytes = base64.b64decode(b64_str)
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return img
    except:
        return None

def _empty_result(face_detected: bool = False) -> dict:
    return {
        "emotion": "unknown",
        "confidence": 0.0,
        "attention_score": 0.0,
        "face_detected": face_detected,
        "timestamp": datetime.utcnow().isoformat(),
    }

def aggregate_session(snapshots: list) -> dict:
    if not snapshots:
        return {"avg_attention": 0.0, "dominant_emotion": "unknown", "engagement_level": "low"}

    attentions = [s.get("attention_score", 0) for s in snapshots]
    emotions = [s.get("emotion", "unknown") for s in snapshots if s.get("face_detected")]
    avg_attention = round(sum(attentions) / len(attentions), 3) if attentions else 0.0
    
    from collections import Counter
    dominant = Counter(emotions).most_common(1)[0][0] if emotions else "unknown"
    engagement = "high" if avg_attention >= 0.7 else ("medium" if avg_attention >= 0.4 else "low")

    return {
        "avg_attention": avg_attention,
        "dominant_emotion": dominant,
        "engagement_level": engagement,
    }
