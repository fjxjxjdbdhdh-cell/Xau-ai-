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
TELEGRAM_CONFIG = os.path.join(BASE_DIR, "telegram.json")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
DEFAULT_CHAT_ID = os.environ.get("CHAT_ID", "5246379098")
METAAPI_TOKEN = "eyJhbGciOiJSUzUxMiIsInR5cCI6IkpXVCJ9.eyJfaWQiOiJlZjk5Yzk1YmY0NDRmODNjMzAzODdjMWJlOWFjNGNiZCIsImFjY2Vzc1J1bGVzIjpbeyJpZCI6InRyYWRpbmctYWNjb3VudC1tYW5hZ2VtZW50LWFwaSIsIm1ldGhvZHMiOlsidHJhZGluZy1hY2NvdW50LW1hbmFnZW1lbnQtYXBpOnJlc3Q6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6Im1ldGFhcGktcmVzdC1hcGkiLCJtZXRob2RzIjpbIm1ldGFhcGktYXBpOnJlc3Q6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6Im1ldGFhcGktcnBjLWFwaSIsIm1ldGhvZHMiOlsibWV0YWFwaS1hcGk6d3M6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6Im1ldGFhcGktcmVhbC10aW1lLXN0cmVhbWluZy1hcGkiLCJtZXRob2RzIjpbIm1ldGFhcGktYXBpOndzOnB1YmxpYzoqOioiXSwicm9sZXMiOlsicmVhZGVyIiwid3JpdGVyIl0sInJlc291cmNlcyI6WyIqOiRVU0VSX0lEJDoqIl19LHsiaWQiOiJtZXRhc3RhdHMtYXBpIiwibWV0aG9kcyI6WyJtZXRhc3RhdHMtYXBpOnJlc3Q6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6InJpc2stbWFuYWdlbWVudC1hcGkiLCJtZXRob2RzIjpbInJpc2stbWFuYWdlbWVudC1hcGk6cmVzdDpwdWJsaWM6KjoqIl0sInJvbGVzIjpbInJlYWRlciIsIndyaXRlciJdLCJyZXNvdXJjZXMiOlsiKjokVVNFUl9JRCQ6KiJdfSx7ImlkIjoiY29weWZhY3RvcnktYXBpIiwibWV0aG9kcyI6WyJjb3B5ZmFjdG9yeS1hcGk6cmVzdDpwdWJsaWM6KjoqIl0sInJvbGVzIjpbInJlYWRlciIsIndyaXRlciJdLCJyZXNvdXJjZXMiOlsiKjokVVNFUl9JRCQ6KiJdfSx7ImlkIjoibXQtbWFuYWdlci1hcGkiLCJtZXRob2RzIjpbIm10LW1hbmFnZXItYXBpOnJlc3Q6ZGVhbGluZzoqOioiLCJtdC1tYW5hZ2VyLWFwaTpyZXN0OnB1YmxpYzoqOioiXSwicm9sZXMiOlsicmVhZGVyIiwid3JpdGVyIl0sInJlc291cmNlcyI6WyIqOiRVU0VSX0lEJDoqIl19LHsiaWQiOiJiaWxsaW5nLWFwaSIsIm1ldGhvZHMiOlsiYmlsbGluZy1hcGk6cmVzdDpwdWJsaWM6KjoqIl0sInJvbGVzIjpbInJlYWRlciJdLCJyZXNvdXJjZXMiOlsiKjokVVNFUl9JRCQ6KiJdfV0sImlnbm9yZVJhdGVMaW1pdHMiOmZhbHNlLCJ0b2tlbklkIjoiMjAyMTAyMTMiLCJpbXBlcnNvbmF0ZWQiOmZhbHNlLCJyZWFsVXNlcklkIjoiZWY5OWM5NWJmNDQ0ZjgzYzMwMzg3YzFiZTlhYzRjYmQiLCJpYXQiOjE3NzY5OTk3MzYsImV4cCI6MTc4NDc3NTczNn0.fhpR_e2x_5xwW3QbppHrwtZjv0TY5-ObgPJMFkKw_vDCldt3zj8wQGHevYYgp0wLrMFZvgWYVeC2SU-35RdECWacI3_BSOYo-I6nePtZ4bEalLFSPd2anPuMlQ7W7lQKry--DpWT4UwSx3oReWdOz6geVDpcV2zqNFQD79dPdcZT90NvZ6PQQSahBD5gC89_bvo6w2YRmAplNCOsdcMq5kg2egSxZm6lKRflpo9HzTz1Tdb3at16Q0Gryay7LLBlravVfZGFOgguc3nEMYfthkYZTyt-2oJNnmQ--KqP44RTOWP-zExHRyjk5dNBbTNSRpK5Cvvtl5DspP5nZy6Gf0vJQcRf4Fit6G_xW1BB5-tqTbWfbrgdtwc-mgG-0462QuzaNk9rvTg8CWdDjfP-hddg7elGgp_KmZCTzozXi9HLnK6ojYa7hZ9H2O97pmmy_s1MMnhmpmvmWUe-_i_jbKHgnYLDVSczSIgqP46muc7JcBcojYXNogZywBHCIOgn-xRSTVh24jZeKlsNdcxqRUZj8TY9DlCIpb3pmBOVHpzdwXGFfqzrMewiEU0pCywTuBbYl1O7cZkYr6uNWYHJx2fKGFNdyQTcbyoDAkjeZNxDetKjAvF1-5yWsBFuoatzFYXuveqbdZgCA5820LLjDorAx7Uub9mIXuHcdOYEprI"
METAAPI_ACCOUNT_ID = "abd0c175-fc27-4fba-a708-485d2c1f1279"

GA_INTERVAL = 10

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

def send_telegram(text, chat_id=None, reply_markup=None):
    if not TELEGRAM_TOKEN: return {"ok": False}
    if not chat_id: chat_id = DEFAULT_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(url, json=payload, timeout=15)
        return {"ok": True, "response": r.json()}
    except Exception as e: return {"ok": False, "error": str(e)}

def get_xau_price():
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
        return float(r.json()[0]["price"])
    except:
        try:
            r = requests.get("https://api.gold-api.com/price/XAU", timeout=10)
            return float(r.json()["price"])
        except:
            return None

def ema(values, period):
    if len(values) < period: return sum(values) / len(values)
    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    for v in values[period:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val

def rsi_calc(prices, period=14):
    if len(prices) < period + 1: return 50
    gains = 0
    losses = 0
    for i in range(1, period + 1):
        diff = prices[i] - prices[i-1]
        if diff > 0: gains += diff
        else: losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr_calc(highs, lows, closes, period=14):
    if len(closes) < period + 1: return 1
    trs = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        c_prev = closes[i-1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        trs.append(tr)
    return sum(trs[-period:]) / period

def mt5_open_trade(signal, price, sl, tp):
    if not METAAPI_TOKEN:
        return {"error": "MetaApi not configured"}
    headers = {
        "Authorization": f"Bearer {METAAPI_TOKEN}",
        "Content-Type": "application/json"
    }
    url = f"https://mt-client-api-v1.agiliumtrade.agiliumtrade.ai/users/current/accounts/{METAAPI_ACCOUNT_ID}/trade"
    data = {
        "actionType": "ORDER_TYPE_BUY" if signal == "BUY" else "ORDER_TYPE_SELL",
        "symbol": "XAUUSD",
        "volume": 0.01,
        "stopLoss": round(sl, 2),
        "takeProfit": round(tp, 2)
    }
    try:
        r = requests.post(url, json=data, headers=headers, timeout=15)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def auto_trader_loop():
    price_history = []
    high_history = []
    low_history = []
    
    while True:
        time.sleep(300)
        try:
            price = get_xau_price()
            if not price: continue
            
            price_history.append(price)
            high_history.append(price + 2)
            low_history.append(price - 2)
            
            if len(price_history) > 100:
                price_history = price_history[-100:]
                high_history = high_history[-100:]
                low_history = low_history[-100:]
            
            if len(price_history) < 30: continue
            
            e20 = ema(price_history, 20)
            e50 = ema(price_history, 50)
            rsi = rsi_calc(price_history)
            atr = atr_calc(high_history, low_history, price_history)
            
            trend_up = e20 > e50
            
            signal = None
            if trend_up and rsi > 52: signal = "BUY"
            elif not trend_up and rsi < 48: signal = "SELL"
            
            if signal:
                with _lock:
                    weights = load_weights()
                    rules = load_rules()
                
                conf = compute_confidence(signal, price, rsi, "UP" if signal == "BUY" else "DOWN", atr, weights)
                conf, reasons, threshold = apply_rules(conf, signal, price, rsi, atr, rules)
                
                if conf >= threshold:
                    sl = price - atr * 0.8 if signal == "BUY" else price + atr * 0.8
                    tp = price + atr * 2.5 if signal == "BUY" else price - atr * 2.5
                    
                    result = mt5_open_trade(signal, price, round(sl, 2), round(tp, 2))
                    
                    msg = f"🤖 *AI открыл сделку!*\n"
                    msg += f"Сигнал: *{signal} XAUUSD*\n"
                    msg += f"Цена: {price} | RSI: {rsi} | ATR: {atr}\n"
                    msg += f"Уверенность: {conf}\n"
                    msg += f"SL: {sl:.2f} | TP: {tp:.2f}\n"
                    msg += f"Ответ MT5: {json.dumps(result)}"
                    
                    send_telegram(msg)
                    print(f"AUTO-TRADE: {signal} @ {price} | Result: {result}")
                
        except Exception as e:
            print(f"Auto-trader error: {e}")

def normalize_signal(s):
    s = str(s).strip().upper()
    return {"BUY": 1.0, "LONG": 1.0, "SELL": 0.0, "SHORT": 0.0}.get(s, 0.5)

def normalize_trend(t):
    t = str(t).strip().upper()
    return {"UP": 1.0, "BULL": 1.0, "DOWN": 0.0, "BEAR": 0.0, "FLAT": 0.5}.get(t, 0.5)

def compute_confidence(signal, price, rsi, trend, atr, weights):
    sig = normalize_signal(signal)
    tr = normalize_trend(trend)
    rsi_v = float(rsi)
    atr_v = float(atr)
    rsi_score = max(0, (50 - rsi_v) / 50) if sig >= 0.5 else max(0, (rsi_v - 50) / 50)
    trend_score = tr if sig >= 0.5 else 1 - tr
    atr_score = max(0, 1 - atr_v / 100)
    feats = {"signal": sig, "price": 0.5, "rsi": rsi_score, "trend": trend_score, "atr": atr_score}
    total = sum(weights.values()) or 1.0
    return round(max(0, min(1, sum(feats[k] * weights[k] for k in weights) / total)), 4)

def apply_rules(conf, signal, price, rsi, atr, rules):
    reasons = []
    threshold = rules.get("confidence_threshold", 0.70)
    signal_str = str(signal).strip().upper()
    preferred = rules.get("preferred_signal", "BUY")
    bias_strength = rules.get("bias_strength", 0.0)
    
    if signal_str == preferred:
        bonus = 0.10 * bias_strength
        conf = min(1.0, conf + bonus)
        reasons.append(f"Signal aligns with {preferred} bias (+{bonus:.3f})")
    
    try:
        rsi_v = float(rsi)
        if signal_str == "BUY" and rsi_v <= rules.get("rsi_oversold", 30):
            conf = min(1.0, conf + 0.05)
            reasons.append(f"RSI {rsi_v} oversold (+0.050)")
        elif signal_str == "SELL" and rsi_v >= rules.get("rsi_overbought", 70):
            conf = min(1.0, conf + 0.05)
            reasons.append(f"RSI {rsi_v} overbought (+0.050)")
    except: pass
    
    try:
        atr_v = float(atr)
        if atr_v > rules.get("atr_caution_above", 50):
            conf = max(0.0, conf - 0.05)
            reasons.append(f"ATR {atr_v} high (-0.050)")
    except: pass
    
    if rules.get("risk_mode") == "elevated":
        threshold = min(0.95, threshold + 0.05)
        reasons.append("Elevated risk mode (+0.050 threshold)")
    
    return round(max(0.0, min(1.0, conf)), 4), reasons, round(threshold, 4)

def genetic_evolve(weights, trades):
    labeled = [t for t in trades if t.get("outcome") in ("win", "loss")]
    if len(labeled) < GA_INTERVAL or len(labeled) % GA_INTERVAL != 0:
        return weights, None
    
    best = weights
    best_fit = 0
    for _ in range(50):
        new_w = {k: max(0.01, v + random.uniform(-0.1, 0.1)) for k, v in weights.items()}
        s = sum(new_w.values())
        new_w = {k: v/s for k, v in new_w.items()}
        correct = sum(1 for t in labeled if (compute_confidence(
            t["signal"], t["price"], t["rsi"], t["trend"], t["atr"], new_w) >= 0.70) == (t["outcome"] == "win"))
        fit = correct / len(labeled)
        if fit > best_fit:
            best_fit = fit
            best = new_w
    save_weights(best)
    return best, best_fit

def search_internet():
    insights = load_insights()
    queries = [
        "XAUUSD gold trading strategy 2026",
        "gold price forecast technical analysis",
        "XAUUSD support resistance levels today",
        "gold market news today",
        "XAUUSD RSI MACD strategy"
    ]
    new_records = []
    
    for query in queries:
        try:
            r = requests.get("https://api.duckduckgo.com/", 
                params={"q": query, "format": "json", "no_html": 1}, timeout=15)
            text = r.text[:3000]
            
            record = {
                "query": query,
                "fetched_at": datetime.utcnow().isoformat(),
                "source": "duckduckgo",
                "analysis": {
                    "bullish_hits": text.lower().count("bull") + text.lower().count("buy") + text.lower().count("long"),
                    "bearish_hits": text.lower().count("bear") + text.lower().count("sell") + text.lower().count("short"),
                    "risk_hits": text.lower().count("risk") + text.lower().count("crash") + text.lower().count("drop"),
                    "rsi_mentions": text.lower().count("rsi"),
                    "price_mentions": text.lower().count("$"),
                    "sample": text[:300]
                }
            }
            insights.append(record)
            new_records.append(record)
        except Exception as e:
            new_records.append({"query": query, "error": str(e)})
    
    if len(insights) > 100: insights = insights[-100:]
    save_insights(insights)
    
    rules = load_rules()
    total_bull = sum(r["analysis"]["bullish_hits"] for r in new_records if "analysis" in r)
    total_bear = sum(r["analysis"]["bearish_hits"] for r in new_records if "analysis" in r)
    total_risk = sum(r["analysis"]["risk_hits"] for r in new_records if "analysis" in r)
    
    if total_bull > total_bear:
        rules["preferred_signal"] = "BUY"
        rules["market_bias"] = "bullish"
    else:
        rules["preferred_signal"] = "SELL"
        rules["market_bias"] = "bearish"
    
    rules["bias_strength"] = min(1.0, (total_bull + total_bear) / max(total_bull + total_bear + total_risk, 1))
    rules["risk_mode"] = "elevated" if total_risk > total_bull + total_bear else "normal"
    rules["narrative"] = f"Search: {len(new_records)} queries. Bull={total_bull} Bear={total_bear} Risk={total_risk}. Mode: {rules['risk_mode']}"
    save_rules(rules)
    
    return {"new_records": new_records, "rules": rules}

def format_signal(trade, reasons):
    emoji = "🟢" if trade.get("decision") == "execute" else "⚪"
    msg = f"{emoji} *Trade Signal*\n"
    msg += f"Signal: *{trade.get('signal', '?')}*\n"
    msg += f"Price: {trade.get('price', '?')}\n"
    msg += f"RSI: {trade.get('rsi', '?')} | Trend: {trade.get('trend', '?')} | ATR: {trade.get('atr', '?')}\n"
    msg += f"Confidence: *{trade.get('confidence', 0)}*\n"
    msg += f"Decision: *{trade.get('decision', 'skip').upper()}*\n"
    if reasons:
        msg += "Reasons:\n"
        for r in reasons: msg += f"  - {r}\n"
    return msg

def format_daily_report(stats, rules, learn_summary):
    msg = "📊 *DAILY REPORT - XAU AI*\n\n"
    msg += f"Trades: {stats.get('total', 0)} | Labeled: {stats.get('labeled', 0)} | Executed: {stats.get('executed', 0)}\n"
    wr = stats.get('winrate')
    msg += f"Winrate: {int(wr*100)}%\n" if wr else "Winrate: N/A\n"
    msg += f"Avg confidence: {stats.get('avg_conf', 0)}\n\n"
    msg += f"🧠 *Learned:*\n{learn_summary}\n\n"
    msg += f"Bias: {rules.get('market_bias')} | Signal: {rules.get('preferred_signal')}\n"
    msg += f"RSI: {rules.get('rsi_oversold')}/{rules.get('rsi_overbought')}\n"
    msg += f"Risk: {rules.get('risk_mode')} | Target: ${rules.get('price_target')}\n"
    return msg

@app.route("/")
def home():
    trades = load_trades()
    rules = load_rules()
    return f"""
    <h1>🤖 XAU AI Trader</h1>
    <p>Trades: {len(trades)} | Bias: {rules.get('market_bias', 'N/A')} | Risk: {rules.get('risk_mode', 'N/A')}</p>
    <p><a href='/stats'>Stats</a> | <a href='/learn'>Learn</a> | <a href='/evolve'>Evolve Now</a> | <a href='/report'>Daily Report</a></p>
    """

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    signal = data.get("signal", "BUY")
    price = data.get("price", 4700)
    rsi = data.get("rsi", 50)
    trend = data.get("trend", "UP")
    atr = data.get("atr", 10)
    outcome = data.get("outcome")
    
    with _lock:
        weights = load_weights()
        rules = load_rules()
        trades = load_trades()
        
        base_conf = compute_confidence(signal, price, rsi, trend, atr, weights)
        confidence, reasons, threshold = apply_rules(base_conf, signal, price, rsi, atr, rules)
        decision = "execute" if confidence >= threshold else "skip"
        
        trade = {
            "id": uuid.uuid4().hex[:8],
            "time": datetime.utcnow().isoformat(),
            "signal": signal, "price": price, "rsi": rsi, "trend": trend, "atr": atr,
            "base_confidence": base_conf, "confidence": confidence,
            "threshold": threshold, "decision": decision, "reasons": reasons, "outcome": outcome,
        }
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
    
    return jsonify({"status": "ok", "decision": decision, "confidence": confidence, "reasons": reasons})

@app.route("/stats")
def stats():
    trades = load_trades()
    labeled = [t for t in trades if t.get("outcome") in ("win", "loss")]
    executed = [t for t in labeled if t.get("decision") == "execute"]
    wins = sum(1 for t in labeled if t["outcome"] == "win")
    return jsonify({
        "total": len(trades), "labeled": len(labeled), "executed": len(executed),
        "wins": wins, "winrate": round(wins / max(len(labeled), 1), 2),
        "weights": load_weights()
    })

@app.route("/evolve", methods=["POST", "GET"])
def evolve_now():
    result = search_internet()
    return jsonify({"status": "ok", "queries": len(result["new_records"]), "rules": result["rules"]})

@app.route("/learn")
def learn():
    rules = load_rules()
    insights = load_insights()
    return jsonify({"rules": rules, "insights_count": len(insights), "latest": insights[-1] if insights else None})

@app.route("/telegram/webhook", methods=["POST"])
def telegram_callback():
    update = request.get_json(silent=True) or {}
    cb = update.get("callback_query", {})
    data_str = cb.get("data", "")
    
    if ":" not in data_str: return jsonify({"ok": True})
    action, trade_id = data_str.split(":", 1)
    if action not in ("win", "loss"): return jsonify({"ok": True})
    
    with _lock:
        trades = load_trades()
        for t in trades:
            if t.get("id") == trade_id:
                t["outcome"] = action
                break
        save_trades(trades)
        genetic_evolve(load_weights(), trades)
    
    return jsonify({"ok": True, "outcome": action})

@app.route("/report", methods=["POST", "GET"])
def report():
    trades = load_trades()
    rules = load_rules()
    labeled = [t for t in trades if t.get("outcome") in ("win", "loss")]
    executed = [t for t in labeled if t.get("decision") == "execute"]
    wins = sum(1 for t in labeled if t["outcome"] == "win")
    
    stats = {
        "total": len(trades), "labeled": len(labeled), "executed": len(executed),
        "winrate": round(wins / max(len(labeled), 1), 2),
        "avg_conf": round(sum(t.get("confidence", 0) for t in trades) / max(len(trades), 1), 2)
    }
    
    try:
        result = search_internet()
        learn_summary = "\n".join([f"{r['query']}: B={r['analysis']['bullish_hits']} S={r['analysis']['bearish_hits']}" 
            for r in result["new_records"][:3] if "analysis" in r])
    except: learn_summary = "Search offline"
    
    msg = format_daily_report(stats, rules, learn_summary)
    send_telegram(msg)
    return jsonify({"status": "ok", "stats": stats})

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
            executed = [t for t in labeled if t.get("decision") == "execute"]
            wins = sum(1 for t in labeled if t["outcome"] == "win")
            stats = {
                "total": len(trades), "labeled": len(labeled), "executed": len(executed),
                "winrate": round(wins / max(len(labeled), 1), 2),
                "avg_conf": round(sum(t.get("confidence", 0) for t in trades) / max(len(trades), 1), 2)
            }
            msg = format_daily_report(stats, load_rules(), "Daily internet search completed")
            send_telegram(msg)
        except Exception as e: print(f"Report error: {e}")
        time.sleep(60)

threading.Thread(target=daily_scheduler, daemon=True).start()
threading.Thread(target=auto_trader_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
