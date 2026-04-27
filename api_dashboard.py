from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import User, Trade, DailyStats
from datetime import datetime, timezone

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")

@bp.route("/stats", methods=["GET"])
@jwt_required()
def stats():
    u = User.query.filter_by(username=get_jwt_identity()).first()
    if not u:
        return jsonify({"error": "Не найден"}), 404
    today = datetime.now(timezone.utc).date()
    ds = DailyStats.query.filter_by(user_id=u.id, date=today).first()
    return jsonify({
        "trades_today": ds.trades_count if ds else 0,
        "pnl_today": float(ds.pnl) if ds else 0.0,
        "tier": u.tier
    })
