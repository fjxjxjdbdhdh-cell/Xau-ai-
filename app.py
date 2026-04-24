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

# ========== ЛОГГЕР ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
logger = logging.getLogger("XAU_AI")

app = Flask(__name__)
_lock = threading.Lock()

# ========== JSON ==========
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

# ========== TELEGRAM ==========
def tg(text, chat=None, kb=None):
    try:
        p = {"chat_id": chat or CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
        if kb: p["reply_markup"] = json.dumps(kb)
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=p, timeout=10)
        logger.info(f"TG sent: {text[:80]}...")
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

# ========== OANDA ==========
def oanda_headers():
    return {"Authorization": f"Bearer {OANDA_KEY}", "Content-Type": "application/json"}

def fetch_price():
    try:
        r = requests.get(f"{OANDA_URL}/accounts/{OANDA_ACC}/pricing?instruments=XAU_USD", headers=oanda_headers(), timeout=10)
        return float(r.json()["prices"][0]["bids"][0]["price"])
    except Exception as e:
        logger.error(f"Price fetch error: {e}")
        return None

def open_order(signal, price, atr):
    units = 1 if signal == "BUY" else -1
    sl = round(price - atr * 0.8, 2) if signal == "BUY" else round(price + atr * 0.8, 2)
    tp = round(price + atr * 2.5, 2) if signal == "BUY" else round(price - atr * 2.5, 2)
    data = {"order": {"units": str(units), "instrument": "XAU_USD", "type": "MARKET", "stopLossOnFill": {"price": f"{sl:.2f}"}, "takeProfitOnFill": {"price": f"{tp:.2f}"}}}
    try:
        r = requests.post(f"{OANDA_URL}/accounts/{OANDA_ACC}/orders", headers=oanda_headers(), json=data, timeout=15)
        body = r.json()
        fill = body.get("orderFillTransaction", {})
        trade_id = fill.get("tradeOpened", {}).get("tradeID", "")
        logger.info(f"Order placed: {signal} @ {price} | SL:{sl} TP:{tp} | ID:{trade_id}")
        return {"ok": bool(trade_id), "id": trade_id, "sl": sl, "tp": tp}
    except Exception as e:
        logger.error(f"Order error: {e}")
        return {"ok": False, "error": str(e)}

# ========== ИНДИКАТОРЫ ==========
def sma(p, n):
    return sum(p[-n:]) / n if len(p) >= n else 0

def ema_calc(p, n):
    if len(p) < n: return sma(p, len(p))
    k = 2 / (n + 1)
    ema = sum(p[:n]) / n
    for v in p[n:]: ema = v * k + ema * (1 - k)
    return ema

def rsi_calc(p, period=14):
    if len(p) < period + 1: return 50
    gains, losses = 0, 0
    for i in range(-period, 0):
        diff = p[i] - p[i-1]
        if diff > 0: gains += diff
        else: losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0: return 100
    return round(100 - 100/(1 + avg_gain/avg_loss), 2)

def atr_calc(p):
    if len(p) < 15: return 1
    return round(sum(abs(p[i]-p[i-1]) for i in range(-14, 0)) / 14, 2)

# ========== AI ==========
def normalize_signal(s):
    return {"BUY": 1.0, "SELL": 0.0}.get(str(s).strip().upper(), 0.5)

def normalize_trend(t):
    return {"UP": 1.0, "DOWN": 0.0, "FLAT": 0.5}.get(str(t).strip().upper(), 0.5)

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
    preferred = rules.get("preferred_signal", "BUY")
    bias_strength = rules.get("bias_strength", 0.5)
    
    if signal == preferred:
        bonus = 0.10 * bias_strength
        conf = min(1, conf + bonus)
        reasons.append(f"Bias match ({preferred}): +{bonus:.3f}")
    elif signal in ("BUY", "SELL") and preferred in ("BUY", "SELL"):
        penalty = 0.07 * bias_strength
        conf = max(0, conf - penalty)
        reasons.append(f"Bias oppose ({preferred}): -{penalty:.3f}")
    
    if signal == "BUY" and rsi <= rules.get("rsi_oversold", 30):
        conf = min(1, conf + 0.05)
        reasons.append(f"RSI {rsi} oversold: +0.050")
    elif signal == "BUY" and rsi >= rules.get("rsi_overbought", 70):
        conf = max(0, conf - 0.07)
        reasons.append(f"RSI {rsi} overbought vs BUY: -0.070")
    
    if signal == "SELL" and rsi >= rules.get("rsi_overbought", 70):
        conf = min(1, conf + 0.05)
        reasons.append(f"RSI {rsi} overbought: +0.050")
    elif signal == "SELL" and rsi <= rules.get("rsi_oversold", 30):
        conf = max(0, conf - 0.07)
        reasons.append(f"RSI {rsi} oversold vs SELL: -0.070")
    
    if atr > rules.get("atr_caution_above", 50):
        penalty = min(0.15, (atr - rules["atr_caution_above"]) / 200)
        conf = max(0, conf - penalty)
        reasons.append(f"ATR {atr} high: -{penalty:.3f}")
    
    target = rules.get("price_target")
    if target and abs(float(rules.get("price", 0)) - target) / target < 0.02:
        conf = min(1, conf + 0.03)
        reasons.append(f"Near target {target}: +0.030")
    
    if rules.get("risk_mode") == "elevated":
        thr = min(0.95, thr + 0.05)
        reasons.append("Elevated risk: threshold +0.050")
    
    return round(max(0, min(1, conf)), 4), reasons, round(thr, 4)

# ========== ГЕНЕТИЧЕСКИЙ АЛГОРИТМ (СЛОЖНЫЙ) ==========
def fitness(weights, trades):
    scored = correct = 0
    for t in trades:
        if t.get("outcome") not in ("win", "loss"): continue
        conf = compute_confidence(t.get("signal","BUY"), float(t.get("rsi",50)), t.get("trend","UP"), float(t.get("atr",10)), weights)
        if (conf >= 0.7) == (t["outcome"] == "win"): correct += 1
        scored += 1
    return correct / scored if scored else 0

def random_weights():
    raw = {k: random.random() for k in DEFAULT_WEIGHTS}
    s = sum(raw.values())
    return {k: v/s for k, v in raw.items()}

def crossover(a, b):
    child = {k: (a[k] + b[k]) / 2 for k in a}
    s = sum(child.values())
    return {k: v/s for k, v in child.items()}

def mutate(w):
    out = {}
    for k, v in w.items():
        if random.random() < GA_MUTATION_RATE:
            out[k] = max(0.01, v + random.uniform(-0.15, 0.15))
        else:
            out[k] = v
    s = sum(out.values())
    return {k: v/s for k, v in out.items()}

def evolve_weights(current, trades):
    labeled = [t for t in trades if t.get("outcome") in ("win", "loss")]
    if len(labeled) < 2 or len(labeled) % GA_INTERVAL != 0: return current, None
    
    population = [current] + [random_weights() for _ in range(GA_POPULATION - 1)]
    best, best_fit = current, fitness(current, labeled)
    
    for gen in range(GA_GENERATIONS):
        scored = sorted([(fitness(w, labeled), w) for w in population], key=lambda x: x[0], reverse=True)
        if scored[0][0] > best_fit:
            best_fit, best = scored[0][0], scored[0][1]
            logger.info(f"GA gen {gen}: new best fitness {best_fit:.4f}")
        
        elites = [w for _, w in scored[:max(2, GA_POPULATION // 4)]]
        new_pop = list(elites)
        while len(new_pop) < GA_POPULATION:
            a, b = random.sample(elites, 2)
            new_pop.append(mutate(crossover(a, b)))
        population = new_pop
    
    sw(best)
    logger.info(f"GA complete. Best fitness: {best_fit:.4f}. Weights: {best}")
    return best, best_fit

# ========== ИНСАЙТЫ (ГЛУБОКИЕ) ==========
def search_and_learn():
    insights = li()
    queries = [
        "XAUUSD gold trading strategy 2026 technical analysis",
        "gold price forecast 2026 support resistance",
        "XAUUSD RSI MACD strategy scalp",
        "gold market news outlook 2026",
        "XAUUSD trading signals institutional"
    ]
    new_records = []
    
    for query in queries:
        try:
            r = requests.get("https://api.duckduckgo.com/", params={"q": query, "format": "json"}, timeout=15)
            text = r.text[:5000]
            
            record = {
                "query": query,
                "fetched_at": datetime.utcnow().isoformat(),
                "source": "DuckDuckGo",
                "characters": len(text),
                "analysis": {
                    "bullish": text.lower().count("bull") + text.lower().count("buy") + text.lower().count("long") + text.lower().count("upward"),
                    "bearish": text.lower().count("bear") + text.lower().count("sell") + text.lower().count("short") + text.lower().count("downward"),
                    "risk_words": text.lower().count("risk") + text.lower().count("crash") + text.lower().count("drop") + text.lower().count("volatile"),
                    "rsi_mentions": text.lower().count("rsi"),
                    "ema_mentions": text.lower().count("ema") + text.lower().count("moving average"),
                    "price_mentions": sum(1 for w in text.split() if w.startswith("$") or w.startswith("4")),
                    "keywords": [w for w in ["breakout", "support", "resistance", "trend", "reversal", "consolidation"] if w in text.lower()],
                    "sample": text[:500]
                }
            }
            insights.append(record)
            new_records.append(record)
            logger.info(f"Insight gathered: {query} | Bull:{record['analysis']['bullish']} Bear:{record['analysis']['bearish']}")
        except Exception as e:
            logger.warning(f"Insight failed for '{query}': {e}")
    
    if len(insights) > 200: insights = insights[-200:]
    si(insights)
    
    # Анализ и обновление правил
    rules = lr()
    total_bull = sum(r["analysis"]["bullish"] for r in new_records if "analysis" in r)
    total_bear = sum(r["analysis"]["bearish"] for r in new_records if "analysis" in r)
    total_risk = sum(r["analysis"]["risk_words"] for r in new_records if "analysis" in r)
    all_keywords = sum((r["analysis"].get("keywords", []) for r in new_records if "analysis" in r), [])
    
    rules["market_bias"] = "bullish" if total_bull > total_bear else "bearish"
    rules["preferred_signal"] = "BUY" if total_bull > total_bear else "SELL"
    rules["bias_strength"] = min(1, (total_bull + total_bear) / max(total_bull + total_bear + total_risk, 1))
    rules["risk_mode"] = "elevated" if total_risk > (total_bull + total_bear) * 0.5 else "normal"
    
    if "reversal" in all_keywords: rules["confidence_threshold"] = min(0.85, rules.get("confidence_threshold", 0.7) + 0.05)
    if "breakout" in all_keywords: rules["confidence_threshold"] = max(0.6, rules.get("confidence_threshold", 0.7) - 0.03)
    
    rules["narrative"] = f"Search: {len(new_records)} queries | Bull:{total_bull} Bear:{total_bear} Risk:{total_risk} | Keywords: {', '.join(set(all_keywords)[:5])}"
    sr(rules)
    
    logger.info(f"Rules updated: {rules['narrative']}")
    return rules

# ========== АВТОТРЕЙДЕР ==========
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
            
            if len(prices) < 50:
                logger.info(f"Buffer filling: {len(prices)}/50 prices")
                continue
            
            e20 = ema_calc(prices, 20)
            e50 = ema_calc(prices, 50)
            r = rsi_calc(prices)
            a = atr_calc(prices)
            
            signal = None
            if e20 > e50 and r > 52: signal = "BUY"
            elif e20 < e50 and r < 48: signal = "SELL"
            
            if signal:
                trend = "UP" if signal == "BUY" else "DOWN"
                with _lock: w = lw(); rules = lr()
                
                conf = compute_confidence(signal, r, trend, a, w)
                conf, reasons, thr = apply_rules(conf, signal, r, a, rules)
                
                logger.info(f"Signal: {signal} | Price: {price} | RSI: {r} | ATR: {a} | Conf: {conf} | Thr: {thr} | {'EXECUTE' if conf >= thr else 'SKIP'}")
                
                if conf >= thr:
                    order = open_order(signal, price, a)
                    if order.get("ok"):
                        trade = {
                            "id": uuid.uuid4().hex[:10],
                            "time": datetime.utcnow().isoformat(),
                            "signal": signal, "price": price, "rsi": r, "trend": trend, "atr": a,
                            "confidence": conf, "decision": "execute", "reasons": reasons,
                            "oanda_trade_id": order["id"], "oanda_sl": order["sl"], "oanda_tp": order["tp"],
                            "outcome": None, "source": "auto"
                        }
                        t = lt(); t.append(trade); st(t)
                        
                        msg = f"🤖 *AUTO-TRADE*\n{signal} XAUUSD @ {price}\nRSI: {r} | ATR: {a}\nConfidence: {conf}\nSL: {order['sl']} | TP: {order['tp']}\n"
                        if reasons: msg += "Reasons:\n" + "\n".join(f"  - {r}" for r in reasons)
                        tg(msg)
                        
                        evolve_weights(w, t)
        except Exception as e:
            logger.error(f"Auto-trader error: {e}")

# ========== PROCESS SIGNAL ==========
def process_signal(signal, price, rsi, trend, atr, outcome=None):
    with _lock: w = lw(); rules = lr()
    
    conf = compute_confidence(signal, float(rsi), trend, float(atr), w)
    conf, reasons, thr = apply_rules(conf, signal, float(rsi), float(atr), rules)
    decision = "execute" if conf >= thr else "skip"
    
    trade = {
        "id": uuid.uuid4().hex[:10],
        "time": datetime.utcnow().isoformat(),
        "signal": signal, "price": price, "rsi": rsi, "trend": trend, "atr": atr,
        "confidence": conf, "decision": decision, "reasons": reasons,
        "outcome": outcome, "source": "manual"
    }
    
    t = lt(); t.append(trade); st(t)
    
    ga = None
    if outcome: 
        new_w, fit = evolve_weights(w, t)
        if new_w != w: ga = {"evolved": True, "fitness": fit}
    
    logger.info(f"Processed: {signal} @ {price} | Conf: {conf} | Dec: {decision} | Outcome: {outcome}")
    
    # РАСЧЁТ SL/TP
    price_val = float(price)
    atr_val = float(atr)
    sl_price = round(price_val - atr_val*0.8, 2) if signal == "BUY" else round(price_val + atr_val*0.8, 2)
    tp_price = round(price_val + atr_val*2.5, 2) if signal == "BUY" else round(price_val - atr_val*2.5, 2)
    sl_dollars = round(atr_val * 0.8 * 10, 0)
    tp_dollars = round(atr_val * 2.5 * 10, 0)
    
    msg = f"🤖 *AI Analysis*\n"
    msg += f"Signal: *{signal}* | Price: {price}\n"
    msg += f"RSI: {rsi} | Trend: {trend} | ATR: {atr}\n"
    msg += f"Confidence: *{conf}* | Decision: {'✅ EXECUTE' if decision == 'execute' else '⏸ SKIP'}\n"
    msg += f"━━━━━━━━━━━━━━\n"
    msg += f"🛑 Stop Loss: ${sl_dollars} (цена: {sl_price})\n"
    msg += f"🎯 Take Profit: ${tp_dollars} (цена: {tp_price})\n"
    msg += f"📊 Risk/Reward: 1:{round(tp_dollars/sl_dollars, 1)}\n"
    if reasons: msg += "\n" + "\n".join(f"  - {r}" for r in reasons)
    
    kb = {"inline_keyboard": [[
        {"text": "✅ Win", "callback_data": f"win:{trade['id']}"},
        {"text": "❌ Loss", "callback_data": f"loss:{trade['id']}"}
    ]]} if not outcome else None
    
    tg(msg, kb=kb)
    return trade, ga

# ========== ROUTES ==========
@app.route("/")
def home():
    t = lt(); r = lr()
    return f"<h1>🤖 XAU AI Trader</h1><p>Trades: {len(t)} | Bias: {r.get('market_bias')}</p><p><a href='/stats'>Stats</a> | <a href='/evolve'>Evolve</a> | <a href='/learn'>Learn</a></p>"

@app.route("/webhook", methods=["POST"])
def webhook():
    d = request.get_json(silent=True) or {}
    if any(d.get(k) is None for k in ["signal","price","rsi","trend","atr"]):
        return jsonify({"error": "Missing fields"}), 400
    trade, ga = process_signal(d["signal"], d["price"], d["rsi"], d["trend"], d["atr"], d.get("outcome"))
    return jsonify({"status": "ok", "decision": trade["decision"], "confidence": trade["confidence"]})

@app.route("/stats")
def stats():
    t = lt(); lab = [x for x in t if x.get("outcome") in ("win","loss")]
    wins = sum(1 for x in lab if x["outcome"] == "win")
    return jsonify({"total": len(t), "labeled": len(lab), "wins": wins, "winrate": round(wins/max(len(lab),1),2), "weights": lw()})

@app.route("/evolve")
def ev():
    r = search_and_learn()
    return jsonify({"ok": True, "bias": r.get("market_bias"), "rules": r})

@app.route("/learn")
def learn():
    ins = li()
    r = lr()
    return jsonify({"rules": r, "insights_count": len(ins), "latest": ins[-1] if ins else None})

@app.route("/telegram/webhook", methods=["POST"])
def tg_webhook():
    d = request.get_json(silent=True) or {}
    msg = d.get("message", {})
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat", {}).get("id")
    
    if text and chat:
        if text == "/start":
            tg("🤖 *XAU AI Trader*\n\n/buy ЦЕНА RSI ТРЕНД ATR\n/sell ЦЕНА RSI ТРЕНД ATR\n/status\n/report\n/learn", chat)
            return jsonify({"ok": True})
        if text == "/status":
            t = lt(); r = lr(); lab = [x for x in t if x.get("outcome") in ("win","loss")]
            wins = sum(1 for x in lab if x["outcome"] == "win")
            wr = round(wins/max(len(lab),1),2) if lab else 0
            tg(f"📊 *Status*\nTrades: {len(t)} | Wins: {wins} | Winrate: {wr}\nBias: {r.get('market_bias')}\nSignal: {r.get('preferred_signal')}\nRisk: {r.get('risk_mode')}", chat)
            return jsonify({"ok": True})
        if text == "/report":
            r = search_and_learn()
            t = lt(); lab = [x for x in t if x.get("outcome") in ("win","loss")]
            wins = sum(1 for x in lab if x["outcome"] == "win")
            tg(f"📊 *DAILY REPORT*\nTrades: {len(t)} | Wins: {wins}\nBias: {r.get('market_bias')}\nSignal: {r.get('preferred_signal')}\nRisk: {r.get('risk_mode')}\n{r.get('narrative')}", chat)
            return jsonify({"ok": True})
        if text == "/learn":
            ins = li()
            r = lr()
            latest = ins[-1] if ins else None
            tg(f"🧠 *Learned*\nRules: {json.dumps(r, indent=2)[:500]}\nInsights: {len(ins)} records\nLatest: {str(latest)[:300]}", chat)
            return jsonify({"ok": True})
        parts = text.split()
        if len(parts) >= 5 and parts[0] in ("/buy", "/sell"):
            signal = "BUY" if parts[0] == "/buy" else "SELL"
            process_signal(signal, parts[1], parts[2], parts[3], parts[4])
            return jsonify({"ok": True})
        tg("Команды: /buy /sell /status /report /learn", chat)
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
            logger.info(f"Trade {tid} marked as {action}")
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
            total = len(lab)
            wr = round(wins/max(total,1)*100, 1) if total else 0
            msg = f"🌅 *DAILY REPORT - {datetime.utcnow().strftime('%Y-%m-%d')}*\n\n"
            msg += f"Trades: {len(t)} | Labeled: {total} | Executed: {total}\n"
            msg += f"Winrate: {wr}% ({wins}/{total})\n\n"
            msg += f"Bias: *{r.get('market_bias')}* | Signal: *{r.get('preferred_signal')}*\n"
            msg += f"RSI: {r.get('rsi_oversold')}/{r.get('rsi_overbought')} | Risk: {r.get('risk_mode')}\n"
            msg += f"Target: ${r.get('price_target')}\n\n"
            msg += f"🧠 *Learned:*\n{r.get('narrative')}"
            tg(msg)
            logger.info("Daily report sent")
        except Exception as e:
            logger.error(f"Daily report error: {e}")

threading.Thread(target=auto_loop, daemon=True).start()
threading.Thread(target=daily_report, daemon=True).start()

logger.info("XAU AI Trader started")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
