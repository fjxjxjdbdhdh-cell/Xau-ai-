from flask import Flask, request, jsonify, render_template_string
import json
import os
import uuid
import random
import threading
import requests
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "webhook.log")
TRADES_FILE = os.path.join(BASE_DIR, "trades.json")
WEIGHTS_FILE = os.path.join(BASE_DIR, "weights.json")
RULES_FILE = os.path.join(BASE_DIR, "rules.json")
INSIGHTS_FILE = os.path.join(BASE_DIR, "insights.json")
TELEGRAM_CFG = os.path.join(BASE_DIR, "telegram.json")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
DEFAULT_CHAT_ID = os.environ.get("CHAT_ID", "5246379098")

CONFIDENCE_THRESHOLD = 0.5
GA_INTERVAL = 10
GA_POPULATION = 20
GA_GENERATIONS = 15
GA_MUTATION_RATE = 0.2

DEFAULT_WEIGHTS = {"signal": 0.30, "price": 0.10, "rsi": 0.25, "trend": 0.25, "atr": 0.10}
DEFAULT_RULES = {
    "preferred_signal": "BUY", "market_bias": "bullish", "bias_strength": 0.5,
    "rsi_oversold": 30, "rsi_overbought": 70, "atr_caution_above": 50,
    "risk_mode": "normal", "confidence_threshold": 0.70,
    "price_target": 4700, "price_range": [4650, 4750],
    "narrative": "AI initialized."
}

app = Flask(__name__)
_lock = threading.Lock()

def _read_json(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path, "r") as f: return json.load(f)
    except: return default

def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(data, f, indent=2)
    os.replace(tmp, path)

def load_weights(): return _read_json(WEIGHTS_FILE, DEFAULT_WEIGHTS)
def save_weights(w): _write_json(WEIGHTS_FILE, w)
def load_trades(): return _read_json(TRADES_FILE, [])
def save_trades(t): _write_json(TRADES_FILE, t)
def load_rules(): return _read_json(RULES_FILE, DEFAULT_RULES)
def save_rules(r): _write_json(RULES_FILE, r)
def load_insights(): return _read_json(INSIGHTS_FILE, [])
def save_insights(i): _write_json(INSIGHTS_FILE, i)
def load_telegram_cfg(): return _read_json(TELEGRAM_CFG, {"chat_id": DEFAULT_CHAT_ID})
def save_telegram_cfg(c): _write_json(TELEGRAM_CFG, c)

def send_telegram(text, chat_id=None, reply_markup=None):
    if not TELEGRAM_TOKEN: return {"ok": False}
    if not chat_id: chat_id = load_telegram_cfg().get("chat_id", DEFAULT_CHAT_ID)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(url, json=payload, timeout=15)
        return {"ok": True, "response": r.json()}
    except Exception as e: return {"ok": False, "error": str(e)}

def answer_callback(cb_id, text):
    if not TELEGRAM_TOKEN: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": cb_id, "text": text}, timeout=10)
    except: pass

def edit_message(chat_id, msg_id, text):
    if not TELEGRAM_TOKEN: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
            json={"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "Markdown",
            "reply_markup": json.dumps({"inline_keyboard": []})}, timeout=10)
    except: pass

def normalize_signal(s):
    s = str(s).strip().upper()
    return {"BUY": 1.0, "LONG": 1.0, "SELL": 0.0, "SHORT": 0.0}.get(s, 0.5)

def normalize_trend(t):
    t = str(t).strip().upper()
    return {"UP": 1.0, "BULL": 1.0, "DOWN": 0.0, "BEAR": 0.0, "FLAT": 0.5}.get(t, 0.5)

def normalize_features(signal, price, rsi, trend, atr):
    sig = normalize_signal(signal)
    try: rsi_v = max(0, min(100, float(rsi)))
    except: rsi_v = 50
    try: atr_v = float(atr)
    except: atr_v = 0
    rsi_score = max(0, (50 - rsi_v) / 50) if sig >= 0.5 else max(0, (rsi_v - 50) / 50)
    tr = normalize_trend(trend)
    trend_score = tr if sig >= 0.5 else 1 - tr
    atr_score = max(0, 1 - atr_v / 100)
    return {"signal": sig, "price": 0.5, "rsi": rsi_score, "trend": trend_score, "atr": atr_score}

def compute_confidence(features, weights):
    total = sum(weights.values()) or 1.0
    return round(max(0, min(1, sum(features[k] * weights[k] for k in weights) / total)), 4)

def apply_rules(conf, raw_input, rules):
    reasons = []
    threshold = float(rules.get("confidence_threshold", 0.70))
    signal_str = str(raw_input.get("signal", "")).strip().upper()
    preferred = str(rules.get("preferred_signal", "HOLD")).upper()
    bias_strength = float(rules.get("bias_strength", 0.0))
    
    if signal_str == preferred:
        conf = min(1.0, conf + 0.10 * bias_strength)
        reasons.append(f"Signal aligns with {preferred} bias (+{0.10 * bias_strength:.3f})")
    elif signal_str in ("BUY", "SELL") and preferred in ("BUY", "SELL"):
        conf = max(0.0, conf - 0.10 * bias_strength)
        reasons.append(f"Signal opposes {preferred} bias (-{0.10 * bias_strength:.3f})")
    
    try:
        rsi_v = float(raw_input.get("rsi"))
        if signal_str == "BUY" and rsi_v <= rules.get("rsi_oversold", 30):
            conf = min(1.0, conf + 0.05)
            reasons.append(f"RSI {rsi_v} oversold (+0.050)")
        elif signal_str == "SELL" and rsi_v >= rules.get("rsi_overbought", 70):
            conf = min(1.0, conf + 0.05)
            reasons.append(f"RSI {rsi_v} overbought (+0.050)")
    except: pass
    
    try:
        atr_v = float(raw_input.get("atr"))
        if atr_v > rules.get("atr_caution_above", 50):
            conf = max(0.0, conf - 0.05)
            reasons.append(f"ATR {atr_v} high (-0.050)")
    except: pass
    
    if rules.get("risk_mode") == "elevated":
        threshold = min(0.95, threshold + 0.05)
        reasons.append("Elevated risk mode (+0.050)")
    
    return round(max(0.0, min(1.0, conf)), 4), reasons, round(threshold, 4)

def genetic_evolve(weights, trades):
    labeled = [t for t in trades if t.get("outcome") in ("win", "loss") and t.get("features")]
    if len(labeled) < 2 or len(labeled) % GA_INTERVAL != 0: return weights, None
    best, best_fit = weights, 0
    for _ in range(GA_GENERATIONS * 2):
        new_w = {k: max(0.01, v + random.uniform(-0.1, 0.1)) for k, v in weights.items()}
        s = sum(new_w.values())
        new_w = {k: v/s for k, v in new_w.items()}
        correct = sum(1 for t in labeled if (compute_confidence(t["features"], new_w) >= 0.70) == (t["outcome"] == "win"))
        fit = correct / len(labeled)
        if fit > best_fit: best_fit, best = fit, new_w
    save_weights(best)
    return best, best_fit

def search_internet():
    insights = load_insights()
    queries = ["XAUUSD gold trading strategy 2026", "gold price forecast", "XAUUSD RSI MACD strategy", "gold market news"]
    new_records = []
    for q in queries:
        try:
            r = requests.get("https://api.duckduckgo.com/", params={"q": q, "format": "json"}, timeout=15)
            text = r.text[:3000]
            record = {"query": q, "fetched_at": datetime.utcnow().isoformat(), "source": "ddg",
                "analysis": {"bullish_hits": text.lower().count("bull") + text.lower().count("buy"),
                "bearish_hits": text.lower().count("bear") + text.lower().count("sell"),
                "risk_hits": text.lower().count("risk"), "rsi_mentions": text.lower().count("rsi"),
                "sample": text[:300]}}
            insights.append(record)
            new_records.append(record)
        except: pass
    if len(insights) > 100: insights = insights[-100:]
    save_insights(insights)
    rules = load_rules()
    total_bull = sum(r["analysis"]["bullish_hits"] for r in new_records if "analysis" in r)
    total_bear = sum(r["analysis"]["bearish_hits"] for r in new_records if "analysis" in r)
    rules["preferred_signal"] = "BUY" if total_bull > total_bear else "SELL"
    rules["market_bias"] = "bullish" if total_bull > total_bear else "bearish"
    rules["bias_strength"] = min(1.0, (total_bull + total_bear) / max(total_bull + total_bear + 1, 1))
    rules["narrative"] = f"Search: Bull={total_bull} Bear={total_bear}"
    save_rules(rules)
    return {"new_records": new_records, "rules": rules}

def format_signal(trade, reasons):
    e = "✅" if trade.get("decision") == "execute" else "⏸"
    msg = f"*Trade Signal*\nSignal: *{trade.get('signal')}*\nPrice: {trade.get('price')}\nRSI: {trade.get('rsi')} | Trend: {trade.get('trend')} | ATR: {trade.get('atr')}\nConfidence: *{trade.get('confidence')}*\nDecision: {e} {trade.get('decision', 'skip').upper()}\n"
    if reasons: msg += "Reasons:\n" + "\n".join(f"  - {r}" for r in reasons)
    return msg

def format_daily_report(stats, rules, learn):
    msg = "📊 *DAILY REPORT - XAU AI*\n\n"
    msg += f"Trades: {stats.get('total', 0)} | Labeled: {stats.get('labeled', 0)} | Executed: {stats.get('executed', 0)}\n"
    wr = stats.get('winrate')
    msg += f"Winrate: {int(wr*100)}%\n" if wr else "Winrate: N/A\n"
    msg += f"Avg confidence: {stats.get('avg_conf', 0)}\n\n"
    msg += f"🧠 *Learned:*\n{learn}\n\n"
    msg += f"Bias: {rules.get('market_bias')} | Signal: {rules.get('preferred_signal')}\n"
    msg += f"RSI: {rules.get('rsi_oversold')}/{rules.get('rsi_overbought')} | Risk: {rules.get('risk_mode')}\n"
    return msg

def process_signal(signal, price, rsi, trend, atr, outcome=None):
    with _lock:
        weights = load_weights()
        rules = load_rules()
        raw = {"signal": signal, "price": price, "rsi": rsi, "trend": trend, "atr": atr}
        features = normalize_features(signal, price, rsi, trend, atr)
        base_conf = compute_confidence(features, weights)
        confidence, reasons, threshold = apply_rules(base_conf, raw, rules)
        decision = "execute" if confidence >= threshold else "skip"
        
        trade = {"id": uuid.uuid4().hex[:8], "time": datetime.utcnow().isoformat(),
            "signal": signal, "price": price, "rsi": rsi, "trend": trend, "atr": atr,
            "confidence": confidence, "decision": decision, "reasons": reasons, "outcome": outcome}
        trades = load_trades()
        trades.append(trade)
        save_trades(trades)
        
        ga_result = None
        if outcome in ("win", "loss"):
            new_w, fit = genetic_evolve(weights, trades)
            if new_w != weights: ga_result = {"evolved": True, "fitness": fit}
    
    msg = format_signal(trade, reasons)
    kb = {"inline_keyboard": [[
        {"text": "✅ Win", "callback_data": f"win:{trade['id']}"},
        {"text": "❌ Loss", "callback_data": f"loss:{trade['id']}"}
    ]]} if not outcome else None
    send_telegram(msg, reply_markup=kb)
    return trade, ga_result

@app.route("/")
def home():
    trades = load_trades()
    rules = load_rules()
    return f"<h1>🤖 XAU AI Trader</h1><p>Trades: {len(trades)} | Bias: {rules.get('market_bias', 'N/A')}</p><p><a href='/stats'>Stats</a> | <a href='/evolve'>Evolve</a></p>"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    required = ["signal", "price", "rsi", "trend", "atr"]
    if any(data.get(k) is None for k in required):
        return jsonify({"error": "Missing fields"}), 400
    trade, ga = process_signal(data["signal"], data["price"], data["rsi"], data["trend"], data["atr"], data.get("outcome"))
    return jsonify({"status": "ok", "decision": trade["decision"], "confidence": trade["confidence"]})

@app.route("/stats")
def stats():
    trades = load_trades()
    labeled = [t for t in trades if t.get("outcome") in ("win", "loss")]
    wins = sum(1 for t in labeled if t["outcome"] == "win")
    return jsonify({"total": len(trades), "labeled": len(labeled), "wins": wins,
        "winrate": round(wins / max(len(labeled), 1), 2), "weights": load_weights()})

@app.route("/evolve", methods=["GET"])
def evolve():
    result = search_internet()
    return jsonify({"status": "ok", "rules": result["rules"]})

@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json(silent=True) or {}
    msg = data.get("message", {})
    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat", {}).get("id")
    
    if text and chat_id:
        cfg = load_telegram_cfg()
        if not cfg.get("chat_id"): save_telegram_cfg({"chat_id": chat_id})
        
        if text == "/start":
            send_telegram("🤖 *XAU AI Trader*\n\n/buy ЦЕНА RSI ТРЕНД ATR\n/sell ЦЕНА RSI ТРЕНД ATR\n/status\n/report\n\nПример: /buy 4695 54 UP 10", chat_id)
            return jsonify({"ok": True})
        
        if text == "/status":
            trades = load_trades()
            rules = load_rules()
            labeled = [t for t in trades if t.get("outcome") in ("win", "loss")]
            wins = sum(1 for t in labeled if t["outcome"] == "win")
            wr = round(wins / max(len(labeled), 1), 2) if labeled else 0
            send_telegram(f"📊 *Status*\nTrades: {len(trades)}\nWins: {wins}\nWinrate: {wr}\nBias: {rules.get('market_bias')}\nSignal: {rules.get('preferred_signal')}", chat_id)
            return jsonify({"ok": True})
        
        if text == "/report":
            trades = load_trades()
            rules = load_rules()
            labeled = [t for t in trades if t.get("outcome") in ("win", "loss")]
            wins = sum(1 for t in labeled if t["outcome"] == "win")
            stats = {"total": len(trades), "labeled": len(labeled), "executed": len(labeled),
                "winrate": round(wins / max(len(labeled), 1), 2) if labeled else 0,
                "avg_conf": round(sum(t.get("confidence", 0) for t in trades) / max(len(trades), 1), 2)}
            try:
                result = search_internet()
                learn = "\n".join([f"{r['query']}: B={r['analysis']['bullish_hits']} S={r['analysis']['bearish_hits']}" for r in result["new_records"][:3] if "analysis" in r])
            except: learn = "N/A"
            send_telegram(format_daily_report(stats, rules, learn), chat_id)
            return jsonify({"ok": True})
        
        parts = text.split()
        if len(parts) >= 5 and parts[0] in ("/buy", "/sell"):
            signal = "BUY" if parts[0] == "/buy" else "SELL"
            trade, ga = process_signal(signal, parts[1], parts[2], parts[3], parts[4])
            return jsonify({"ok": True, "decision": trade["decision"]})
        
        send_telegram("Команды: /buy, /sell, /status, /report", chat_id)
        return jsonify({"ok": True})
    
    cb = data.get("callback_query", {})
    data_str = cb.get("data", "")
    if ":" in data_str:
        action, trade_id = data_str.split(":", 1)
        if action in ("win", "loss"):
            with _lock:
                trades = load_trades()
                for t in trades:
                    if t.get("id") == trade_id: t["outcome"] = action
                save_trades(trades)
                genetic_evolve(load_weights(), trades)
            answer_callback(cb.get("id"), f"Marked as {action.upper()}")
    return jsonify({"ok": True})

def daily_scheduler():
    while True:
        now = datetime.utcnow()
        target = now.replace(hour=8, minute=0, second=0)
        if now >= target: target = target.replace(day=now.day + 1)
        time.sleep((target - now).total_seconds())
        try:
            search_internet()
            trades = load_trades()
            labeled = [t for t in trades if t.get("outcome") in ("win", "loss")]
            wins = sum(1 for t in labeled if t["outcome"] == "win")
            stats = {"total": len(trades), "labeled": len(labeled), "executed": len(labeled),
                "winrate": round(wins / max(len(labeled), 1), 2) if labeled else 0,
                "avg_conf": round(sum(t.get("confidence", 0) for t in trades) / max(len(trades), 1), 2)}
            send_telegram(format_daily_report(stats, load_rules(), "Daily search completed"))
        except Exception as e: print(f"Error: {e}")
        time.sleep(60)

threading.Thread(target=daily_scheduler, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
