from flask import Flask, request, jsonify
import json
import os
import uuid
import random
import threading
import requests
import time
import logging
from datetime import datetime, timedelta

# ========== НАСТРОЙКИ ==========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE = os.path.join(BASE_DIR, "trades.json")
WEIGHTS_FILE = os.path.join(BASE_DIR, "weights.json")
RULES_FILE = os.path.join(BASE_DIR, "rules.json")
INSIGHTS_FILE = os.path.join(BASE_DIR, "insights.json")
LOG_FILE = os.path.join(BASE_DIR, "ai_trader.log")
TELEGRAM_CFG = os.path.join(BASE_DIR, "telegram.json")
OANDA_STATE = os.path.join(BASE_DIR, "oanda.json")

TELEGRAM_TOKEN = "8788731785:AAFhOHviyVMkuDS1psfjnk8XvZxXviPmfcg"
CHAT_ID = "5246379098"
OANDA_KEY = "a93d6adf7854d010509bd48001989ff6-077c4d484c560a8a23083cbf699b0cf3"
OANDA_ACC = "101-001-39155902-001"
OANDA_URL = "https://api-fxpractice.oanda.com/v3"

GA_INTERVAL = 10
GA_POPULATION = 30
GA_GENERATIONS = 20
GA_MUTATION_RATE = 0.15

DEFAULT_WEIGHTS = {"signal": 0.30, "price": 0.10, "rsi": 0.25, "trend": 0.25, "atr": 0.10}
DEFAULT_RULES = {"preferred_signal": "BUY", "market_bias": "bullish", "bias_strength": 0.5, "rsi_oversold": 30, "rsi_overbought": 70, "atr_caution_above": 50, "risk_mode": "normal", "confidence_threshold": 0.70, "price_target": 4700, "narrative": "AI initialized."}

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
logger = logging.getLogger("XAU_AI")

app = Flask(__name__)
_lock = threading.Lock()

def rj(p, d):
    if not os.path.exists(p): return d
    try:
        with open(p) as f: return json.load(f)
    except: return d

def wj(p, d):
    with open(p + ".tmp", "w") as f: json.dump(d, f, indent=2)
    os.replace(p + ".tmp", p)

lw = lambda: rj(WEIGHTS_FILE, dict(DEFAULT_WEIGHTS))
sw = lambda w: wj(WEIGHTS_FILE, w)
lt = lambda: rj(TRADES_FILE, [])
st = lambda t: wj(TRADES_FILE, t)
lr = lambda: rj(RULES_FILE, dict(DEFAULT_RULES))
sr = lambda r: wj(RULES_FILE, r)
li = lambda: rj(INSIGHTS_FILE, [])
si = lambda i: wj(INSIGHTS_FILE, i)
lc = lambda: rj(TELEGRAM_CFG, {"chat_id": CHAT_ID})
sc = lambda c: wj(TELEGRAM_CFG, c)
lo = lambda: rj(OANDA_STATE, {"prices": [], "trades": []})
so = lambda s: wj(OANDA_STATE, s)

def tg(text, chat=None, kb=None):
    try:
        p = {"chat_id": chat or CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
        if kb: p["reply_markup"] = json.dumps(kb)
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=p, timeout=10)
        logger.info(f"TG: {text[:80]}...")
        return r.json()
    except Exception as e:
        logger.error(f"TG error: {e}")
        return {}

def tg_answer(cb_id, text=None):
    try:
        p = {"callback_query_id": cb_id}
        if text: p["text"] = text
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", json=p, timeout=10)
    except: pass

def oanda_headers():
    return {"Authorization": f"Bearer {OANDA_KEY}", "Content-Type": "application/json"}

def fetch_price():
    try:
        r = requests.get(f"{OANDA_URL}/accounts/{OANDA_ACC}/pricing?instruments=XAU_USD", headers=oanda_headers(), timeout=10)
        return float(r.json()["prices"][0]["bids"][0]["price"])
    except: return None

def open_order(signal, price, sl, tp):
    units = 1 if signal == "BUY" else -1
    data = {"order": {"units": str(units), "instrument": "XAU_USD", "type": "MARKET", "stopLossOnFill": {"price": f"{sl:.2f}"}, "takeProfitOnFill": {"price": f"{tp:.2f}"}}}
    try:
        r = requests.post(f"{OANDA_URL}/accounts/{OANDA_ACC}/orders", headers=oanda_headers(), json=data, timeout=15)
        body = r.json()
        fill = body.get("orderFillTransaction", {})
        trade_id = fill.get("tradeOpened", {}).get("tradeID", "")
        return {"ok": bool(trade_id), "id": trade_id, "sl": sl, "tp": tp}
    except: return {"ok": False}

def sma(p, n): return sum(p[-n:])/n if len(p) >= n else 0

def ema_calc(p, n):
    if len(p) < n: return sma(p, len(p))
    k = 2/(n+1)
    ema = sum(p[:n])/n
    for v in p[n:]: ema = v*k + ema*(1-k)
    return ema

def rsi_calc(p, period=14):
    if len(p) < period+1: return 50
    g = sum(max(0, p[i]-p[i-1]) for i in range(-period, 0))/period
    l = sum(max(0, p[i-1]-p[i]) for i in range(-period, 0))/period
    return round(100-100/(1+g/l), 2) if l else 100

def atr_calc(p):
    if len(p) < 15: return 1
    return round(sum(abs(p[i]-p[i-1]) for i in range(-14, 0))/14, 2)

def normalize_signal(s): return {"BUY": 1.0, "SELL": 0.0}.get(str(s).strip().upper(), 0.5)
def normalize_trend(t): return {"UP": 1.0, "DOWN": 0.0, "FLAT": 0.5}.get(str(t).strip().upper(), 0.5)

def compute_confidence(signal, rsi, trend, atr, weights):
    sig = normalize_signal(signal)
    tr = normalize_trend(trend)
    rsi_s = max(0, (50-rsi)/50) if sig > 0.5 else max(0, (rsi-50)/50)
    trend_s = tr if sig > 0.5 else 1-tr
    atr_s = max(0, 1-atr/100)
    feats = {"signal": sig, "price": 0.5, "rsi": rsi_s, "trend": trend_s, "atr": atr_s}
    total = sum(weights.values()) or 1
    return round(max(0, min(1, sum(feats[k]*weights[k] for k in weights)/total)), 4)

def apply_rules(conf, signal, rsi, atr, rules):
    reasons = []
    thr = rules.get("confidence_threshold", 0.7)
    pref = rules.get("preferred_signal", "BUY")
    bs = rules.get("bias_strength", 0.5)
    
    if signal == pref: conf = min(1, conf + 0.10*bs); reasons.append(f"Bias match (+{0.10*bs:.3f})")
    elif signal in ("BUY","SELL") and pref in ("BUY","SELL"): conf = max(0, conf - 0.07*bs); reasons.append(f"Bias oppose (-{0.07*bs:.3f})")
    
    if signal == "BUY" and rsi <= rules.get("rsi_oversold", 30): conf = min(1, conf + 0.05); reasons.append(f"RSI {rsi} oversold (+0.05)")
    if signal == "SELL" and rsi >= rules.get("rsi_overbought", 70): conf = min(1, conf + 0.05); reasons.append(f"RSI {rsi} overbought (+0.05)")
    if signal == "BUY" and rsi >= rules.get("rsi_overbought", 70): conf = max(0, conf - 0.07); reasons.append(f"RSI {rsi} overbought vs BUY (-0.07)")
    if signal == "SELL" and rsi <= rules.get("rsi_oversold", 30): conf = max(0, conf - 0.07); reasons.append(f"RSI {rsi} oversold vs SELL (-0.07)")
    
    if atr > rules.get("atr_caution_above", 50): conf = max(0, conf - 0.05); reasons.append(f"ATR high (-0.05)")
    if rules.get("risk_mode") == "elevated": thr = min(0.95, thr + 0.05); reasons.append("Risk elevated (+0.05 thr)")
    
    return round(max(0, min(1, conf)), 4), reasons, round(thr, 4)

def fitness(weights, trades):
    scored = correct = 0
    for t in trades:
        if t.get("outcome") not in ("win","loss"): continue
        conf = compute_confidence(t.get("signal","BUY"), float(t.get("rsi",50)), t.get("trend","UP"), float(t.get("atr",10)), weights)
        if (conf >= 0.7) == (t["outcome"] == "win"): correct += 1
        scored += 1
    return correct/scored if scored else 0

def random_weights():
    raw = {k: random.random() for k in DEFAULT_WEIGHTS}
    s = sum(raw.values())
    return {k: v/s for k, v in raw.items()}

def crossover(a, b):
    child = {k: (a[k]+b[k])/2 for k in a}
    s = sum(child.values())
    return {k: v/s for k, v in child.items()}

def mutate(w):
    out = {}
    for k, v in w.items():
        if random.random() < GA_MUTATION_RATE: out[k] = max(0.01, v + random.uniform(-0.15, 0.15))
        else: out[k] = v
    s = sum(out.values())
    return {k: v/s for k, v in out.items()}

def evolve_weights(current, trades):
    labeled = [t for t in trades if t.get("outcome") in ("win","loss")]
    if len(labeled) < 2 or len(labeled) % GA_INTERVAL != 0: return current, None
    
    pop = [current] + [random_weights() for _ in range(GA_POPULATION-1)]
    best, best_fit = current, fitness(current, labeled)
    
    for gen in range(GA_GENERATIONS):
        scored = sorted([(fitness(w, labeled), w) for w in pop], key=lambda x: x[0], reverse=True)
        if scored[0][0] > best_fit: best_fit, best = scored[0][0], scored[0][1]
        elites = [w for _, w in scored[:max(2, GA_POPULATION//4)]]
        new_pop = list(elites)
        while len(new_pop) < GA_POPULATION:
            a, b = random.sample(elites, 2)
            new_pop.append(mutate(crossover(a, b)))
        pop = new_pop
    
    sw(best)
    logger.info(f"GA done. Fitness: {best_fit:.4f}")
    return best, best_fit

def search_and_learn():
    insights = li()
    qs = ["XAUUSD gold trading strategy 2026", "gold price forecast", "XAUUSD RSI MACD", "gold market news", "XAUUSD signals"]
    new_records = []
    
    for q in qs:
        try:
            r = requests.get("https://api.duckduckgo.com/", params={"q": q, "format": "json"}, timeout=15)
            text = r.text[:5000]
            rec = {"query": q, "fetched_at": datetime.utcnow().isoformat(), "source": "DDG",
                "analysis": {"bullish": text.lower().count("bull")+text.lower().count("buy"),
                "bearish": text.lower().count("bear")+text.lower().count("sell"),
                "risk": text.lower().count("risk")+text.lower().count("crash"),
                "keywords": [w for w in ["breakout","support","resistance","trend","reversal"] if w in text.lower()],
                "sample": text[:300]}}
            insights.append(rec); new_records.append(rec)
        except: pass
    
    if len(insights) > 200: insights = insights[-200:]
    si(insights)
    
    rules = lr()
    total_bull = sum(r["analysis"]["bullish"] for r in new_records if "analysis" in r)
    total_bear = sum(r["analysis"]["bearish"] for r in new_records if "analysis" in r)
    total_risk = sum(r["analysis"]["risk"] for r in new_records if "analysis" in r)
    all_kw = sum((r["analysis"].get("keywords", []) for r in new_records if "analysis" in r), [])
    
    rules["market_bias"] = "bullish" if total_bull > total_bear else "bearish"
    rules["preferred_signal"] = "BUY" if total_bull > total_bear else "SELL"
    rules["bias_strength"] = min(1, (total_bull+total_bear)/max(total_bull+total_bear+total_risk, 1))
    rules["risk_mode"] = "elevated" if total_risk > (total_bull+total_bear)*0.5 else "normal"
    rules["narrative"] = f"Search: Bull={total_bull} Bear={total_bear} Risk={total_risk} | KW: {', '.join(set(all_kw)[:5])}"
    sr(rules)
    return rules

def auto_loop():
    prices = []
    logger.info("Auto-trader started")
    while True:
        time.sleep(300)
        try:
            price = fetch_price()
            if not price: continue
            prices.append(price)
            if len(prices) > 150: prices = prices[-150:]
            so({"prices": prices})
            if len(prices) < 50: continue
            
            e20 = ema_calc(prices, 20); e50 = ema_calc(prices, 50)
            r = rsi_calc(prices); a = atr_calc(prices)
            
            signal = None
            if e20 > e50 and r > 52: signal = "BUY"
            elif e20 < e50 and r < 48: signal = "SELL"
            
            if signal:
                trend = "UP" if signal == "BUY" else "DOWN"
                with _lock: w = lw(); rules = lr()
                conf = compute_confidence(signal, r, trend, a, w)
                conf, reasons, thr = apply_rules(conf, signal, r, a, rules)
                
                if conf >= thr:
                    sl = round(price - a*0.8, 2) if signal == "BUY" else round(price + a*0.8, 2)
                    tp = round(price + a*2.5, 2) if signal == "BUY" else round(price - a*2.5, 2)
                    order = open_order(signal, price, sl, tp)
                    if order.get("ok"):
                        trade = {"id": uuid.uuid4().hex[:10], "time": datetime.utcnow().isoformat(),
                            "signal": signal, "price": price, "rsi": r, "trend": trend, "atr": a,
                            "confidence": conf, "decision": "execute", "oanda_id": order["id"],
                            "sl": sl, "tp": tp, "outcome": None}
                        t = lt(); t.append(trade); st(t)
                        tg(f"🤖 *AUTO-TRADE*\n{signal} @ {price}\nRSI: {r} | ATR: {a}\nConf: {conf}\nSL: {sl} | TP: {tp}")
                        evolve_weights(w, t)
        except Exception as e: logger.error(f"Auto error: {e}")

# ========== PROCESS SIGNAL (SL/TP В ДОЛЛАРАХ) ==========
def process_signal(signal, price, rsi, trend, atr, sl_input=None, tp_input=None, outcome=None):
    with _lock: w = lw(); rules = lr()
    
    conf = compute_confidence(signal, float(rsi), trend, float(atr), w)
    conf, reasons, thr = apply_rules(conf, signal, float(rsi), float(atr), rules)
    decision = "execute" if conf >= thr else "skip"
    
    price_val = float(price)
    atr_val = float(atr)
    
    # SL: если оканчивается на $ → доллары, иначе цена
    sl_price = None
    if sl_input is not None:
        sl_str = str(sl_input)
        if sl_str.endswith("$"):
            sl_dollars_val = float(sl_str.replace("$", ""))
            sl_points = sl_dollars_val / 10  # $1 = 10 пунктов для 0.01 лота
            sl_price = round(price_val - sl_points, 2) if signal == "BUY" else round(price_val + sl_points, 2)
        else:
            sl_price = round(float(sl_str), 2)
    else:
        sl_price = round(price_val - atr_val*0.8, 2) if signal == "BUY" else round(price_val + atr_val*0.8, 2)
    
    # TP: если оканчивается на $ → доллары, иначе цена
    tp_price = None
    if tp_input is not None:
        tp_str = str(tp_input)
        if tp_str.endswith("$"):
            tp_dollars_val = float(tp_str.replace("$", ""))
            tp_points = tp_dollars_val / 10  # $1 = 10 пунктов для 0.01 лота
            tp_price = round(price_val + tp_points, 2) if signal == "BUY" else round(price_val - tp_points, 2)
        else:
            tp_price = round(float(tp_str), 2)
    else:
        tp_price = round(price_val + atr_val*2.5, 2) if signal == "BUY" else round(price_val - atr_val*2.5, 2)
    
    # Посчитать доллары для отображения
    sl_dollars = round(abs(price_val - sl_price) * 10, 0)
    tp_dollars = round(abs(tp_price - price_val) * 10, 0)
    
    trade = {
        "id": uuid.uuid4().hex[:10],
        "time": datetime.utcnow().isoformat(),
        "signal": signal, "price": price, "rsi": rsi, "trend": trend, "atr": atr,
        "confidence": conf, "decision": decision, "reasons": reasons,
        "sl": sl_price, "tp": tp_price, "sl_dollars": sl_dollars, "tp_dollars": tp_dollars,
        "outcome": outcome, "source": "manual"
    }
    
    t = lt(); t.append(trade); st(t)
    
    if outcome:
        new_w, fit = evolve_weights(w, t)
        if new_w != w: logger.info(f"GA evolved: fitness {fit}")
    
    logger.info(f"Trade: {signal} @ {price} | SL:${sl_dollars}({sl_price}) TP:${tp_dollars}({tp_price}) | Conf:{conf} | {decision}")
    
    msg = f"🤖 *AI Analysis*\n"
    msg += f"Signal: *{signal}* | Price: {price}\n"
    msg += f"RSI: {rsi} | Trend: {trend} | ATR: {atr}\n"
    msg += f"Confidence: *{conf}* | Decision: {'✅ EXECUTE' if decision == 'execute' else '⏸ SKIP'}\n"
    msg += f"━━━━━━━━━━━━━━\n"
    msg += f"🛑 Stop Loss: *${sl_dollars}* (цена: {sl_price})\n"
    msg += f"🎯 Take Profit: *${tp_dollars}* (цена: {tp_price})\n"
    msg += f"📊 Risk/Reward: 1:{round(tp_dollars/max(sl_dollars,1), 1)}\n"
    if reasons: msg += "\n" + "\n".join(f"  - {r}" for r in reasons)
    
    kb = {"inline_keyboard": [[
        {"text": "✅ Win", "callback_data": f"win:{trade['id']}"},
        {"text": "❌ Loss", "callback_data": f"loss:{trade['id']}"}
    ]]} if not outcome else None
    
    tg(msg, kb=kb)
    return trade

# ========== ROUTES ==========
@app.route("/")
def home():
    t = lt(); r = lr()
    return f"<h1>🤖 XAU AI Trader</h1><p>Trades: {len(t)} | Bias: {r.get('market_bias')}</p><p><a href='/stats'>Stats</a> | <a href='/evolve'>Evolve</a> | <a href='/learn'>Learn</a></p>"

@app.route("/webhook", methods=["POST"])
def webhook():
    d = request.get_json(silent=True) or {}
    if any(d.get(k) is None for k in ["signal","price","rsi","trend","atr"]): return jsonify({"error": "Missing fields"}), 400
    trade, _ = process_signal(d["signal"], d["price"], d["rsi"], d["trend"], d["atr"])
    return jsonify({"status": "ok", "decision": trade["decision"]})

@app.route("/stats")
def stats():
    t = lt(); lab = [x for x in t if x.get("outcome") in ("win","loss")]
    wins = sum(1 for x in lab if x["outcome"] == "win")
    return jsonify({"total": len(t), "wins": wins, "winrate": round(wins/max(len(lab),1),2), "weights": lw()})

@app.route("/evolve")
def ev(): return jsonify({"ok": True, "bias": search_and_learn().get("market_bias")})

@app.route("/learn")
def learn():
    ins = li(); r = lr()
    return jsonify({"rules": r, "insights": len(ins), "latest": ins[-1] if ins else None})

@app.route("/telegram/webhook", methods=["POST"])
def tg_webhook():
    d = request.get_json(silent=True) or {}
    msg = d.get("message", {})
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat", {}).get("id")
    
    if text and chat:
        if text == "/start":
            tg("🤖 *XAU AI Trader*\n\n*Команды:*\n/buy ЦЕНА RSI ТРЕНД ATR [SL] [TP]\n/sell ЦЕНА RSI ТРЕНД ATR [SL] [TP]\n/status\n/report\n/learn\n\n*SL/TP можно в долларах!*\n/buy 4695 54 UP 10 8$ 25$\n( SL=$8, TP=$25 )\n\n*Или в цене:*\n/buy 4695 54 UP 10 4687 4720", chat)
            return jsonify({"ok": True})
        if text == "/status":
            t = lt(); r = lr(); lab = [x for x in t if x.get("outcome") in ("win","loss")]
            wins = sum(1 for x in lab if x["outcome"] == "win")
            tg(f"📊 Trades: {len(t)} | Wins: {wins} | Bias: {r.get('market_bias')}", chat)
            return jsonify({"ok": True})
        if text == "/report":
            r = search_and_learn()
            t = lt(); lab = [x for x in t if x.get("outcome") in ("win","loss")]
            wins = sum(1 for x in lab if x["outcome"] == "win")
            tg(f"📊 *REPORT*\nTrades: {len(t)} | Wins: {wins}\n{r.get('narrative')}", chat)
            return jsonify({"ok": True})
        if text == "/learn":
            ins = li(); r = lr()
            tg(f"🧠 Insights: {len(ins)} records\n{r.get('narrative')}", chat)
            return jsonify({"ok": 

             parts = text.split()
        if len(parts) >= 5 and parts[0] in ("/buy", "/sell"):
            try:
                signal = "BUY" if parts[0] == "/buy" else "SELL"
                price = parts[1]
                rsi_val = parts[2]
                trend = parts[3]
                atr_val = parts[4]
                sl_val = parts[5] if len(parts) >= 6 else None
                tp_val = parts[6] if len(parts) >= 7 else None
                float(price)
                float(rsi_val)
                float(atr_val)
                process_signal(signal, price, rsi_val, trend, atr_val, sl_val, tp_val)
            except ValueError:
                tg("❌ Используй цифры!\nПример: /buy 4695 54 UP 10 8$ 25$", chat)
            return jsonify({"ok": True})               
    cb = d.get("callback_query", {})
    ds = cb.get("data", "")
    if ":" in ds:
        action, tid = ds.split(":", 1)
        if action in ("win", "loss"):
            with _lock:
                t = lt()
                for x in t:
                    if x.get("id") == tid: x["outcome"] = action
                st(t)
                evolve_weights(lw(), t)
            tg_answer(cb.get("id"), f"Marked {action.upper()}")
    return jsonify({"ok": True})

def daily_report():
    while True:
        now = datetime.utcnow()
        target = now.replace(hour=8, minute=0, second=0)
        if now >= target: target += timedelta(days=1)
        time.sleep((target - now).total_seconds())
        try:
            r = search_and_learn()
            t = lt(); lab = [x for x in t if x.get("outcome") in ("win","loss")]
            wins = sum(1 for x in lab if x["outcome"] == "win")
            tg(f"📊 *DAILY REPORT*\nTrades: {len(t)} | Wins: {wins}\n{r.get('narrative')}")
        except: pass

threading.Thread(target=auto_loop, daemon=True).start()
threading.Thread(target=daily_report, daemon=True).start()
logger.info("XAU AI Trader started")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
