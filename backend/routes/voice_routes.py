from flask import Blueprint, request, jsonify

voice_bp = Blueprint("voice", __name__)

@voice_bp.route("/health", methods=["GET"])
def voice_health():
    return jsonify({"message": "Voice routes working"})
