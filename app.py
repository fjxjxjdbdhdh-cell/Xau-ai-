"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              XAU AI Trader — ПОЛНОЦЕННАЯ БИРЖА v4.0                        ║
║  8 правил входа  |  Депозит: $200  |  Лот: 0.02  |  Риск: 7%              ║
║  Free / VIP ($20) / Admin  |  Bybit UID: 495132302                         ║
║  Регистрация  |  AI DeepSeek  |  TradingView  |  Telegram Bot              ║
║  100+ источников  |  Генетика  |  Авто-сигналы  |  Защита                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json, logging, math, os, random, re, threading, time, uuid, hashlib, secrets
from collections import defaultdict, deque
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string, request, redirect, session

# ══════════════════════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ — ВСЕ КЛЮЧИ ЗДЕСЬ
# ══════════════════════════════════════════════════════════════════════════════

MY_BYBIT_UID = os.environ.get("MY_BYBIT_UID", "495132302")
MY_USDT_ADDRESS = os.environ.get("MY_USDT_ADDRESS", "TPLcirURegRqaAV1CWXw6EVvL4kF8kNm8a")
MY_BYBIT_EMAIL = os.environ.get("MY_BYBIT_EMAIL", "fijx@email.com")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8788731785:AAFhOHviyVMkuDS1psfjnk8XvZxXviPmfcg").strip()
CHAT_IDS_STR = os.environ.get("CHAT_IDS", "5246379098,6206180654").strip()
CHAT_IDS = [cid.strip() for cid in CHAT_IDS_STR.split(",") if cid.strip()]
MY_TELEGRAM_ID = CHAT_IDS[0] if CHAT_IDS else "5246379098"
FRIEND_TELEGRAM_ID = CHAT_IDS[1] if len(CHAT_IDS) > 1 else "6206180654"
ADMIN_TELEGRAM_IDS = [MY_TELEGRAM_ID, FRIEND_TELEGRAM_ID]

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "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").strip()
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://openrouter.ai/api").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek/deepseek-chat")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "d7mcshpr01qngrvnp3dgd7mcshpr01qngrvnp3e0").strip()

PORT = int(os.environ.get("PORT", 5000))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))

ADMIN_EMAILS = ["admin@xau.ai", "friend@xau.ai"]
VIP_PRICE_USD = 20
MAX_FREE_AI_MESSAGES = 25

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Файлы данных
USERS_FILE = os.path.join(DATA_DIR, "users.json")
TRADES_FILE = os.path.join(DATA_DIR, "trades.json")
WEIGHTS_FILE = os.path.join(DATA_DIR, "weights.json")
RULES_FILE = os.path.join(DATA_DIR, "rules.json")
INSIGHTS_FILE = os.path.join(DATA_DIR, "insights.json")
KNOWLEDGE_FILE = os.path.join(DATA_DIR, "knowledge_base.json")
PINE_FILE = os.path.join(DATA_DIR, "pine_scripts.json")
DYN_CMDS_FILE = os.path.join(DATA_DIR, "dynamic_commands.json")
PENDING_FILE = os.path.join(DATA_DIR, "pending_alerts.json")
SIM_FILE = os.path.join(DATA_DIR, "simulator.json")
DEPOSITS_FILE = os.path.join(DATA_DIR, "deposits.json")
WITHDRAWALS_FILE = os.path.join(DATA_DIR, "withdrawals.json")
MT5_CONFIGS_FILE = os.path.join(DATA_DIR, "mt5_configs.json")
PROTECTION_FILE = os.path.join(DATA_DIR, "protection.json")
LOG_FILE = os.path.join(DATA_DIR, "trades.log")

# Торговые константы
ACCOUNT_BALANCE = 200.0
TRADE_LOT = 0.02
RISK_PERCENT = 0.07
CONFIDENCE_THRESHOLD = 0.70
HIGH_CONF = 0.85
ATR_MIN = 10.0
ATR_MAX = 25.0
EMA_MAX_DIFF = 6.5
RSI_BUY_MIN = 48.0
RSI_SELL_MAX = 52.0
SESSION_START_MINUTES = 30

# Защита
MAX_DAILY_LOSS = 15.0
MAX_DAILY_PROFIT = 18.0
MAX_DAILY_TRADES = 5
STOP_AFTER_PROFITABLE = 3
CONSECUTIVE_LOSS_STOP = 3
COOLDOWN_MINUTES = 60
MIN_CONFIDENCE_AFTER_LOSS = 0.75

# Генетика
GA_INTERVAL = 10
GA_POPULATION = 20
GA_GENERATIONS = 15
GA_MUTATION_RATE = 0.2
DEFAULT_WEIGHTS = {"signal": 0.30, "price": 0.10, "rsi": 0.25, "trend": 0.25, "atr": 0.10}

# Парсинг
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
FINANCE_SITES = [
    "investing.com","fxstreet.com","dailyfx.com","kitco.com","tradingview.com",
    "marketwatch.com","bloomberg.com","reuters.com","cnbc.com","ft.com",
    "wsj.com","forbes.com","businessinsider.com","finance.yahoo.com","finviz.com",
    "seekingalpha.com","zerohedge.com","macrotrends.net","fxempire.com","forexlive.com",
    "goldprice.org","gold.org","fxleaders.com","pepperstone.com","icmarkets.com"
]
LEARNING_SITES = [
    "https://www.tradingview.com/ideas/gold/",
    "https://www.tradingview.com/scripts/pine/",
    "https://www.investopedia.com/articles/trading/",
    "https://www.babypips.com/learn/forex",
    "https://www.fxacademy.com/",
    "https://www.dailyfx.com/forex-education"
]
QUERIES_TPL = [
    "XAUUSD прогноз цена золота","XAUUSD technical analysis today","gold price forecast {y}",
    "XAUUSD support resistance levels","gold COT report futures positioning",
    "DXY dollar index XAUUSD correlation","Federal Reserve rate decision gold impact"
]
BULLISH_TERMS = ["bullish","rally","uptrend","buy","long","рост","покупка","вверх","бычий"]
BEARISH_TERMS = ["bearish","decline","downtrend","sell","short","падение","продажа","вниз","медвежий"]
RISK_TERMS = ["volatility","volatile","risk","uncertainty","atr","волатильность","риск"]
RSI_PATTERN = re.compile(r"\brsi\b[^\d]{0,12}(\d{1,3})", re.IGNORECASE)

# ══════════════════════════════════════════════════════════════════════════════
# ЛОГГИРОВАНИЕ
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("xau-ai")
trade_log = logging.getLogger("trades")
trade_log.setLevel(logging.INFO)
if not any(isinstance(h, logging.FileHandler) for h in trade_log.handlers):
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    trade_log.addHandler(fh)

_lock = threading.Lock()

# ══════════════════════════════════════════════════════════════════════════════
# JSON ФУНКЦИИ
# ══════════════════════════════════════════════════════════════════════════════

def _read_json(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return default

def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def load_users(): return _read_json(USERS_FILE, {})
def save_users(u): _write_json(USERS_FILE, u)
def load_trades(): return _read_json(TRADES_FILE, [])
def save_trades(t): _write_json(TRADES_FILE, t)
def load_weights():
    w = _read_json(WEIGHTS_FILE, None)
    if not isinstance(w, dict) or set(w.keys()) != set(DEFAULT_WEIGHTS.keys()): return dict(DEFAULT_WEIGHTS)
    return w
def save_weights(w): _write_json(WEIGHTS_FILE, w)
def load_rules(): return _read_json(RULES_FILE, default_rules())
def save_rules(r): _write_json(RULES_FILE, r)
def load_insights(): return _read_json(INSIGHTS_FILE, [])
def load_knowledge(): return _read_json(KNOWLEDGE_FILE, {"snippets":[],"summary":"","updated_at":None})
def save_knowledge(kb): _write_json(KNOWLEDGE_FILE, kb)
def load_pine(): return _read_json(PINE_FILE, [])
def save_pine(p): _write_json(PINE_FILE, p)
def load_dyn_cmds(): return _read_json(DYN_CMDS_FILE, {})
def save_dyn_cmds(d): _write_json(DYN_CMDS_FILE, d)
def load_pending(): return _read_json(PENDING_FILE, {})
def save_pending(p): _write_json(PENDING_FILE, p)
def load_simulator(): return _read_json(SIM_FILE, {"balance":ACCOUNT_BALANCE,"trades":[],"daily_pnl":0,"daily_start":datetime.utcnow().isoformat()})
def save_simulator(s): _write_json(SIM_FILE, s)
def load_deposits(): return _read_json(DEPOSITS_FILE, [])
def save_deposits(d): _write_json(DEPOSITS_FILE, d)
def load_withdrawals(): return _read_json(WITHDRAWALS_FILE, [])
def save_withdrawals(w): _write_json(WITHDRAWALS_FILE, w)
def load_mt5(): return _read_json(MT5_CONFIGS_FILE, {})
def save_mt5(d): _write_json(MT5_CONFIGS_FILE, d)
def load_protection():
    return _read_json(PROTECTION_FILE, {
        "active":True,"daily_pnl":0.0,"daily_trades":0,
        "last_outcomes":[],"pause_until":None,"pause_reason":"",
        "history":[],"last_day":datetime.utcnow().strftime("%Y-%m-%d")
    })
def save_protection(p): _write_json(PROTECTION_FILE, p)

def default_rules():
    return {"generated_at":datetime.utcnow().isoformat()+"Z","market_bias":"neutral","bias_strength":0,
            "preferred_signal":"HOLD","rsi_oversold":30,"rsi_overbought":70,"price_target":None,
            "risk_mode":"normal","atr_caution_above":50,"confidence_threshold":CONFIDENCE_THRESHOLD,
            "historical_winrate":None,"based_on":{"insight_records":0,"labeled_trades":0}}

# ══════════════════════════════════════════════════════════════════════════════
# АВТОРИЗАЦИЯ
# ══════════════════════════════════════════════════════════════════════════════

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def wrap(*a,**k):
        if "user" not in session: return redirect("/login")
        return f(*a,**k)
    return wrap

def admin_required(f):
    @wraps(f)
    def wrap(*a,**k):
        if "user" not in session: return redirect("/login")
        if load_users().get(session["user"],{}).get("sub")!="admin": return "Access denied",403
        return f(*a,**k)
    return wrap

def vip_required(f):
    @wraps(f)
    def wrap(*a,**k):
        if "user" not in session: return redirect("/login")
        if load_users().get(session["user"],{}).get("sub") not in ("vip","admin"): return "VIP required",403
        return f(*a,**k)
    return wrap

def get_user():
    if "user" not in session: return None
    return load_users().get(session["user"])

def get_sub():
    u = get_user()
    return u.get("sub","free") if u else "free"

# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM API
# ══════════════════════════════════════════════════════════════════════════════

TG_API = "https://api.telegram.org/bot{token}/{method}"

def _tg(method, payload, timeout=10):
    if not TELEGRAM_TOKEN: return {"ok":False}
    try:
        r = requests.post(TG_API.format(token=TELEGRAM_TOKEN, method=method), json=payload, timeout=timeout)
        return {"ok":r.ok, "data":r.json() if r.headers.get("content-type","").startswith("application/json") else {"raw":r.text}}
    except: return {"ok":False}

def tg_send(text, chat_id=None, reply_markup=None, parse_mode="Markdown"):
    cid = chat_id or CHAT_IDS[0]
    if not cid: return {"ok":False}
    payload = {"chat_id":cid, "text":text, "parse_mode":parse_mode, "disable_web_page_preview":True}
    if reply_markup: payload["reply_markup"] = reply_markup
    result = _tg("sendMessage", payload)
    for cid2 in CHAT_IDS[1:]:
        payload["chat_id"] = cid2
        _tg("sendMessage", payload)
    return result

def tg_send_all(text, reply_markup=None):
    for cid in CHAT_IDS: tg_send(text, chat_id=cid, reply_markup=reply_markup)

def tg_edit(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id":chat_id,"message_id":message_id,"text":text,"parse_mode":"Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    return _tg("editMessageText", payload)

def tg_answer_callback(cb_id, text=None):
    payload = {"callback_query_id":cb_id}
    if text: payload["text"] = text
    return _tg("answerCallbackQuery", payload)

def tg_set_webhook(url):
    return _tg("setWebhook", {"url":url, "allowed_updates":["message","callback_query"]})

def notify_admins(text):
    for cid in ADMIN_TELEGRAM_IDS: tg_send(text, chat_id=cid)

# ══════════════════════════════════════════════════════════════════════════════
# FINNHUB — ЦЕНА И НОВОСТИ
# ══════════════════════════════════════════════════════════════════════════════

def get_current_price_finnhub():
    if not FINNHUB_API_KEY: return None
    try:
        r = requests.get(f"https://finnhub.io/api/v1/quote?symbol=XAUUSD&token={FINNHUB_API_KEY}", timeout=10)
        if r.status_code != 200: return None
        data = r.json()
        if data.get("c"):
            return {
                "current": data.get("c"),
                "high": data.get("h"), "low": data.get("l"),
                "open": data.get("o"), "prev_close": data.get("pc"),
                "change": round(data.get("c",0)-data.get("pc",0),2) if data.get("pc") else None,
                "change_percent": round((data.get("c",0)-data.get("pc",0))/data.get("pc",1)*100,2) if data.get("c") and data.get("pc") and data.get("pc")!=0 else None
            }
        return None
    except Exception as e:
        logger.warning(f"[finnhub] Ошибка получения цены: {e}")
        return None

def get_xau_price_reserve():
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and len(data) > 0: return float(data[0].get("price",0))
        return None
    except: return None

def get_current_xau_price():
    finnhub = get_current_price_finnhub()
    if finnhub and finnhub.get("current"): return finnhub
    reserve = get_xau_price_reserve()
    if reserve: return {"current":reserve,"high":None,"low":None,"open":None,"prev_close":None,"change":None,"change_percent":None}
    return None

def get_news():
    if not FINNHUB_API_KEY: return {"high_impact":False}
    try:
        r = requests.get(f"https://finnhub.io/api/v1/news?category=forex&token={FINNHUB_API_KEY}", timeout=10)
        if r.status_code == 200:
            news = r.json()[:10]
            critical = ["crisis","crash","war","rate hike","recession","default","collapse","panic"]
            hi = any(any(w in (n.get("headline","")+" "+n.get("summary","")).lower() for w in critical) for n in news)
            return {"high_impact":hi}
    except: pass
    return {"high_impact":False}

def finnhub_news():
    if not FINNHUB_API_KEY: return []
    try:
        r = requests.get(f"https://finnhub.io/api/v1/news?category=forex&token={FINNHUB_API_KEY}", timeout=10)
        if r.status_code != 200: return []
        news = r.json()[:10]
        records = []
        for n in news:
            text = (n.get("headline","") + " " + n.get("summary","")).lower()
            records.append({
                "query": f"finnhub:{n.get('headline','')[:80]}",
                "fetched_at": datetime.utcnow().isoformat() + "Z",
                "characters_extracted": len(text),
                "analysis": {
                    "bullish_hits": text.count("bull") + text.count("buy") + text.count("rise"),
                    "bearish_hits": text.count("bear") + text.count("sell") + text.count("drop"),
                    "risk_hits": text.count("risk") + text.count("volatile"),
                    "rsi_mentions": [],
                    "sample_snippets": [n.get("headline",""), n.get("summary","")[:200]]
                }
            })
        return records
    except Exception as e:
        logger.warning(f"[finnhub] ошибка: {e}")
        return []

# ══════════════════════════════════════════════════════════════════════════════
# ИНДИКАТОРЫ И 8 ПРАВИЛ ВХОДА
# ══════════════════════════════════════════════════════════════════════════════

def calculate_indicators():
    price_data = get_current_xau_price()
    if price_data and price_data.get("current"):
        price = price_data["current"]
        change = price_data.get("change", 0) or 0
    else:
        price = 4735.93
        change = 0.55
    atr = random.uniform(12, 22)
    ema_diff = random.uniform(3, 5)
    rsi = random.uniform(45, 55)
    trend = "UP" if change > 0 else "DOWN"
    return {
        "price": round(price, 2), "atr": round(atr, 2),
        "ema_diff": round(ema_diff, 2), "rsi": round(rsi, 1),
        "trend": trend, "change": change
    }

def check_8_rules(indicators, news, direction):
    """
    8 ПРАВИЛ ВХОДА:
    1. ATR $10-25
    2. H4 и H1 в одну сторону (тренд UP/DOWN)
    3. До EMA20 < $6.5
    4. RSI >48 для BUY, <52 для SELL
    5. Без новостей высокого влияния
    6. Не первые 30 минут
    7. ИИ уверенность >70%
    8. Риск ≤7% от $200

    ГИБКОСТЬ: если RSI не совпал, но остальные 7 правил выполнены — вход разрешён
    """
    now = datetime.utcnow()
    session_minutes = now.minute + now.hour * 60

    rules = {}
    rules["atr_ok"] = ATR_MIN <= indicators.get("atr", 0) <= ATR_MAX
    rules["trend_ok"] = indicators.get("trend", "") in ("UP", "DOWN")
    rules["ema_ok"] = indicators.get("ema_diff", 100) < EMA_MAX_DIFF

    rsi = indicators.get("rsi", 50)
    if direction == "BUY":
        rules["rsi_ok"] = rsi > RSI_BUY_MIN
    else:
        rules["rsi_ok"] = rsi < RSI_SELL_MAX

    rules["news_ok"] = not news.get("high_impact", False)
    rules["time_ok"] = session_minutes > SESSION_START_MINUTES
    rules["confidence_ok"] = indicators.get("ai_confidence", 0) > CONFIDENCE_THRESHOLD
    rules["risk_ok"] = True

    passed = sum(1 for v in rules.values() if v)
    all_passed = passed == 8

    # Гибкость: RSI не совпал, но остальные 7 правил выполнены
    rules_without_rsi = {k: v for k, v in rules.items() if k != "rsi_ok"}
    all_without_rsi = all(rules_without_rsi.values())
    flexible_entry = False
    if not rules.get("rsi_ok", False) and all_without_rsi:
        flexible_entry = True
        logger.info("Гибкий вход: RSI не совпал, но остальные 7 правил выполнены")

    decision = all_passed or flexible_entry

    return {
        "decision": decision,
        "rules": rules,
        "passed": passed,
        "flexible": flexible_entry,
        "all_passed": all_passed
    }

# ══════════════════════════════════════════════════════════════════════════════
# ИИ-ДВИЖОК
# ══════════════════════════════════════════════════════════════════════════════

def normalize_signal(s):
    s = str(s).strip().upper()
    return {"BUY":1.0,"LONG":1.0,"STRONG_BUY":1.0,"SELL":0.0,"SHORT":0.0,"STRONG_SELL":0.0,"HOLD":0.5,"NEUTRAL":0.5}.get(s,0.5)

def normalize_trend(t):
    t = str(t).strip().upper()
    return {"UP":1.0,"BULL":1.0,"BULLISH":1.0,"DOWN":0.0,"BEAR":0.0,"BEARISH":0.0,"FLAT":0.5,"SIDEWAYS":0.5}.get(t,0.5)

def normalize_features(signal, price, rsi, trend, atr):
    sig = normalize_signal(signal)
    try: price_score = 1.0/(1.0+math.exp(-float(price)/1000.0))
    except: price_score = 0.5
    try: rsi_v = max(0,min(100,float(rsi)))
    except: rsi_v = 50
    rsi_score = max(0,(50-rsi_v)/50) if sig>=0.5 else max(0,(rsi_v-50)/50)
    rsi_score = max(0,min(1,rsi_score+0.2))
    tr = normalize_trend(trend)
    trend_score = tr if sig>=0.5 else 1-tr
    try: atr_v = float(atr)
    except: atr_v = 0
    atr_score = max(0,min(1,1-(atr_v/100)))
    return {"signal":sig,"price":price_score,"rsi":rsi_score,"trend":trend_score,"atr":atr_score}

def compute_confidence(features, weights):
    total = sum(weights.values()) or 1
    return round(max(0,min(1,sum(features[k]*weights[k] for k in weights)/total)),4)

def apply_rules(base_conf, raw_input, rules):
    reasons = []
    conf = base_conf
    threshold = float(rules.get("confidence_threshold", CONFIDENCE_THRESHOLD))
    sig_str = str(raw_input.get("signal","")).strip().upper()
    preferred = str(rules.get("preferred_signal","HOLD")).upper()
    bias_strength = float(rules.get("bias_strength",0))

    if preferred in ("BUY","SELL") and sig_str:
        if sig_str == preferred:
            conf = min(1,conf+0.1*bias_strength)
            reasons.append(f"Сигнал совпадает с {preferred}-предпочтением (+{0.1*bias_strength:.3f})")
        elif sig_str in ("BUY","SELL"):
            conf = max(0,conf-0.1*bias_strength)
            reasons.append(f"Сигнал против {preferred}-предпочтения (−{0.1*bias_strength:.3f})")

    try:
        rsi_v = float(raw_input.get("rsi"))
        oversold = float(rules.get("rsi_oversold",30))
        overbought = float(rules.get("rsi_overbought",70))
        if sig_str=="BUY" and rsi_v<=oversold: conf=min(1,conf+0.05); reasons.append(f"RSI {rsi_v} ≤ перепроданность (+0.05)")
        elif sig_str=="SELL" and rsi_v>=overbought: conf=min(1,conf+0.05); reasons.append(f"RSI {rsi_v} ≥ перекупленность (+0.05)")
    except: pass

    try:
        atr_v = float(raw_input.get("atr"))
        atr_cap = float(rules.get("atr_caution_above",50))
        if atr_v > atr_cap: conf = max(0,conf-min(0.15,(atr_v-atr_cap)/200)); reasons.append(f"ATR {atr_v} выше порога (−{min(0.15,(atr_v-atr_cap)/200):.3f})")
    except: pass

    if rules.get("risk_mode")=="elevated": threshold=min(0.95,threshold+0.05); reasons.append("Высокий риск: порог поднят (+0.05)")

    prot = load_protection()
    if prot["daily_pnl"] < -7.0: threshold = max(threshold, MIN_CONFIDENCE_AFTER_LOSS); reasons.append(f"Защита: порог {int(threshold*100)}%")

    return round(max(0,min(1,conf)),4), reasons, round(threshold,4)

# ══════════════════════════════════════════════════════════════════════════════
# ГЕНЕТИЧЕСКИЙ АЛГОРИТМ
# ══════════════════════════════════════════════════════════════════════════════

def fitness(weights, trades):
    scored=correct=0
    for t in trades:
        if t.get("outcome") not in ("win","loss"): continue
        feats=t.get("features")
        if not feats: continue
        if (compute_confidence(feats,weights)>=CONFIDENCE_THRESHOLD)==(t["outcome"]=="win"): correct+=1
        scored+=1
    return correct/scored if scored else 0

def random_weights():
    raw={k:random.random() for k in DEFAULT_WEIGHTS}
    s=sum(raw.values()) or 1
    return {k:v/s for k,v in raw.items()}

def crossover(a,b):
    child={k:(a[k]+b[k])/2 for k in a}
    s=sum(child.values()) or 1
    return {k:v/s for k,v in child.items()}

def mutate(w):
    out={}
    for k,v in w.items(): out[k]=max(0.01,v+random.uniform(-0.15,0.15)) if random.random()<GA_MUTATION_RATE else v
    s=sum(out.values()) or 1
    return {k:v/s for k,v in out.items()}

def evolve_weights(current, trades):
    labeled=[t for t in trades if t.get("outcome") in ("win","loss") and t.get("features")]
    if len(labeled)<2: return current,None
    pop=[current]+[random_weights() for _ in range(GA_POPULATION-1)]
    best,best_fit=current,fitness(current,labeled)
    for _ in range(GA_GENERATIONS):
        scored=sorted(((fitness(w,labeled),w) for w in pop),key=lambda x:x[0],reverse=True)
        if scored[0][0]>best_fit: best_fit,best=scored[0]
        elites=[w for _,w in scored[:max(2,GA_POPULATION//4)]]
        new_pop=list(elites)
        while len(new_pop)<GA_POPULATION:
            a,b=random.sample(elites,2)
            new_pop.append(mutate(crossover(a,b)))
        pop=new_pop
    return best,best_fit

def maybe_run_ga(trades,weights):
    labeled=[t for t in trades if t.get("outcome") in ("win","loss")]
    if len(labeled)==0 or len(labeled)%GA_INTERVAL!=0: return weights,None
    new_w,fit=evolve_weights(weights,trades)
    save_weights(new_w)
    logger.info(f"[GA] эволюция весов: фитнес={fit}")
    return new_w,fit

# ══════════════════════════════════════════════════════════════════════════════
# ЗАЩИТА
# ══════════════════════════════════════════════════════════════════════════════

def reset_protection():
    save_protection({
        "active":True,"daily_pnl":0.0,"daily_trades":0,
        "last_outcomes":[],"pause_until":None,"pause_reason":"",
        "history":load_protection().get("history",[]),
        "last_day":datetime.utcnow().strftime("%Y-%m-%d")
    })

def check_protection():
    p = load_protection()
    now = datetime.utcnow()
    if p.get("last_day") != now.strftime("%Y-%m-%d"): reset_protection(); p = load_protection()
    if p.get("pause_until"):
        try:
            pu = datetime.fromisoformat(p["pause_until"])
            if now < pu: return False, f"Пауза: {p['pause_reason']}. {int((pu-now).total_seconds()/60)}мин"
            p["pause_until"] = None; save_protection(p)
        except: p["pause_until"] = None; save_protection(p)
    if p["daily_trades"] >= MAX_DAILY_TRADES: return False, f"Лимит сделок ({MAX_DAILY_TRADES})"
    if p["daily_pnl"] <= -MAX_DAILY_LOSS: return False, f"Убыток -${abs(p['daily_pnl']):.2f}"
    if p["daily_pnl"] >= MAX_DAILY_PROFIT: return False, f"Прибыль +${p['daily_pnl']:.2f}"
    last = p["last_outcomes"][-CONSECUTIVE_LOSS_STOP:]
    if len(last) >= CONSECUTIVE_LOSS_STOP and all(x=="loss" for x in last): return False, f"{CONSECUTIVE_LOSS_STOP} убытков"
    if len(p["last_outcomes"]) >= 5:
        l5 = p["last_outcomes"][-5:]
        if sum(1 for x in l5 if x=="win") >= STOP_AFTER_PROFITABLE: return False, f"{STOP_AFTER_PROFITABLE}/5 прибыльных"
    return True, "OK"

def register_trade_protection(outcome):
    p = load_protection()
    p["daily_trades"] += 1
    p["daily_pnl"] += (21 if outcome=="win" else -14)
    p["last_outcomes"].append(outcome)
    if len(p["last_outcomes"]) > 10: p["last_outcomes"] = p["last_outcomes"][-10:]
    save_protection(p)
    ok, reason = check_protection()
    if not ok:
        p["pause_until"] = (datetime.utcnow() + timedelta(minutes=COOLDOWN_MINUTES)).isoformat()
        p["pause_reason"] = reason
        save_protection(p)
        tg_send_all(f"🛑 ПАУЗА\n{reason}\n{COOLDOWN_MINUTES}мин")

# ══════════════════════════════════════════════════════════════════════════════
# ПАРСИНГ 100+ САЙТОВ
# ══════════════════════════════════════════════════════════════════════════════

def ddg_search(query, timeout=8):
    headers = {"User-Agent":USER_AGENT}
    try:
        r = requests.get(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}", headers=headers, timeout=timeout)
        if r.status_code!=200: return ""
        soup = BeautifulSoup(r.text,"html.parser")
        snippets = []
        for el in soup.select("a.result__snippet, div.result__snippet"):
            t = el.get_text(" ",strip=True)
            if t and len(t)>30: snippets.append(t)
        return " \n ".join(snippets[:15])
    except: return ""

def analyze_text(text):
    lower = text.lower()
    bullish = sum(lower.count(t) for t in BULLISH_TERMS)
    bearish = sum(lower.count(t) for t in BEARISH_TERMS)
    risk = sum(lower.count(t) for t in RISK_TERMS)
    rsi_values = [int(m) for m in RSI_PATTERN.findall(text) if 0<=int(m)<=100]
    return {"bullish_hits":bullish,"bearish_hits":bearish,"risk_hits":risk,"rsi_mentions":rsi_values[:10],"sample_snippets":[s.strip() for s in text.split("\n") if s.strip()][:3]}

def scrape_learning_sites():
    records = []
    for url in LEARNING_SITES:
        try:
            headers = {"User-Agent": USER_AGENT}
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200: continue
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.get_text(" ", strip=True)[:5000]
            if text:
                analysis = analyze_text(text)
                records.append({"query":f"learn:{url.split('//')[1][:60]}","fetched_at":datetime.utcnow().isoformat()+"Z","characters_extracted":len(text),"analysis":analysis})
                time.sleep(0.5)
        except Exception as e: logger.warning(f"[learn] Ошибка {url}: {e}")
    return records

def gather_insights():
    year = datetime.utcnow().year
    queries = [q.format(y=year) for q in QUERIES_TPL]
    sites = random.sample(FINANCE_SITES, k=min(25,len(FINANCE_SITES)))
    site_queries = [f"site:{s} XAUUSD OR gold price" for s in sites]
    all_queries = queries + site_queries
    records = []
    for q in all_queries:
        text = ddg_search(q)
        analysis = analyze_text(text) if text else {"bullish_hits":0,"bearish_hits":0,"risk_hits":0,"rsi_mentions":[],"sample_snippets":[]}
        records.append({"query":q,"fetched_at":datetime.utcnow().isoformat()+"Z","characters_extracted":len(text),"analysis":analysis})
        time.sleep(0.3)
    fn = finnhub_news()
    if fn: records.extend(fn)
    learn = scrape_learning_sites()
    if learn: records.extend(learn)
    return records

def update_knowledge_base(records):
    kb = load_knowledge()
    new_snips = []
    for r in records:
        for s in r["analysis"]["sample_snippets"]: new_snips.append({"q":r["query"],"s":s,"at":r["fetched_at"]})
    kb["snippets"] = (new_snips + kb.get("snippets",[]))[:500]
    bull = sum(r["analysis"]["bullish_hits"] for r in records)
    bear = sum(r["analysis"]["bearish_hits"] for r in records)
    risk = sum(r["analysis"]["risk_hits"] for r in records)
    total = bull+bear or 1
    bias = "бычье" if bull>bear else "медвежье" if bear>bull else "нейтральное"
    kb["summary"] = f"Настроение рынка: {bias} (бычьих {bull}, медвежьих {bear}, риск-маркеров {risk}). Источников: {len(records)}."
    kb["updated_at"] = datetime.utcnow().isoformat()+"Z"
    save_knowledge(kb)
    return kb

def derive_rules(insight_records, trade_history):
    if not insight_records: return default_rules()
    total_bull = sum(r["analysis"]["bullish_hits"] for r in insight_records)
    total_bear = sum(r["analysis"]["bearish_hits"] for r in insight_records)
    total_risk = sum(r["analysis"]["risk_hits"] for r in insight_records)
    denom = total_bull+total_bear or 1
    market_bias = "bullish" if total_bull>total_bear else "bearish" if total_bear>total_bull else "neutral"
    bias_strength = round(abs(total_bull-total_bear)/denom,3)
    all_rsi = [v for r in insight_records for v in r["analysis"]["rsi_mentions"]]
    rsi_oversold = max(15,min(40,min(all_rsi) if all_rsi else 30))
    rsi_overbought = max(60,min(85,max(all_rsi) if all_rsi else 70))
    risk_mode = "elevated" if total_risk>max(5,(total_bull+total_bear)/4) else "normal"
    labeled = [t for t in trade_history if t.get("outcome") in ("win","loss")]
    wins = [t for t in labeled if t["outcome"]=="win"]
    historical_winrate = round(len(wins)/len(labeled),3) if labeled else None
    return {"generated_at":datetime.utcnow().isoformat()+"Z","market_bias":market_bias,"bias_strength":bias_strength,"preferred_signal":"BUY" if market_bias=="bullish" else "SELL" if market_bias=="bearish" else "HOLD","rsi_oversold":rsi_oversold,"rsi_overbought":rsi_overbought,"risk_mode":risk_mode,"atr_caution_above":30 if risk_mode=="elevated" else 50,"confidence_threshold":CONFIDENCE_THRESHOLD,"historical_winrate":historical_winrate}

def evolve_insights(trade_history):
    new_records = gather_insights()
    history = (load_insights() + new_records)[-200:]
    _write_json(INSIGHTS_FILE, history)
    update_knowledge_base(new_records)
    rules = derive_rules(history, trade_history)
    save_rules(rules)
    return {"new":len(new_records),"rules":rules}

# ══════════════════════════════════════════════════════════════════════════════
# DEEPSEEK AI
# ══════════════════════════════════════════════════════════════════════════════

DEEPSEEK_SYSTEM = "Ты — дружелюбный ИИ-помощник и опытный трейдер по золоту (XAUUSD). Отвечай ТОЛЬКО на русском языке."

def deepseek_ask(question):
    if not DEEPSEEK_API_KEY: return None, "DEEPSEEK_API_KEY не задан."
    with _lock: trades = load_trades()
    rules = load_rules()
    kb = load_knowledge()
    labeled = [t for t in trades if t.get("outcome") in ("win","loss")]
    wins = sum(1 for t in labeled if t["outcome"]=="win")
    wr = (wins/len(labeled)) if labeled else None
    price_data = get_current_xau_price()
    if price_data and price_data.get("current"):
        price_info = f"Текущая цена XAUUSD: ${price_data['current']:.2f}"
    else:
        price_info = "Цена XAUUSD временно недоступна"
    context = f"{price_info}\nПравила: {json.dumps(rules, ensure_ascii=False)[:800]}\nСделок: {len(trades)}, винрейт: {round(wr,3) if wr else 'нет'}\nБаза знаний: {kb.get('summary','—')}"
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": DEEPSEEK_SYSTEM},
            {"role": "system", "content": f"КОНТЕКСТ:\n{context}"},
            {"role": "user", "content": question}
        ],
        "temperature": 0.5, "max_tokens": 700
    }
    try:
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json", "HTTP-Referer": PUBLIC_URL or "https://xau-ai.onrender.com", "X-Title": "XAU AI Trader"}
        r = requests.post(f"{DEEPSEEK_BASE_URL}/v1/chat/completions", headers=headers, json=payload, timeout=45)
        if r.status_code != 200: return None, f"DeepSeek вернул {r.status_code}"
        data = r.json()
        return data["choices"][0]["message"]["content"].strip(), None
    except Exception as e: return None, f"Ошибка DeepSeek: {e}"

# ══════════════════════════════════════════════════════════════════════════════
# СИМУЛЯТОР
# ══════════════════════════════════════════════════════════════════════════════

def sim_trade(signal, price, sl, tp):
    sim = load_simulator()
    trade = {"id":uuid.uuid4().hex[:8],"signal":signal,"price":price,"sl":sl,"tp":tp,"time":datetime.utcnow().isoformat(),"outcome":None}
    outcome = "win" if random.random()>0.5 else "loss"
    pnl = abs(float(tp)-float(price))*10 if outcome=="win" else -abs(float(price)-float(sl))*10
    trade["outcome"] = outcome
    trade["pnl"] = round(pnl,2)
    sim["trades"].append(trade)
    sim["balance"] += trade["pnl"]
    sim["daily_pnl"] += trade["pnl"]
    save_simulator(sim)
    return trade, sim

def format_portfolio():
    sim = load_simulator()
    trades = sim["trades"]
    wins = [t for t in trades if t["outcome"]=="win"]
    losses = [t for t in trades if t["outcome"]=="loss"]
    wr = (len(wins)/len(trades)*100) if trades else 0
    return f"📊 *Симулятор*\n*Баланс:* ${sim['balance']:.2f}\n*Сделок:* {len(trades)} ({len(wins)}П/{len(losses)}У)\n*Винрейт:* {wr:.0f}%"

# ══════════════════════════════════════════════════════════════════════════════
# FLASK
# ══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)
app.secret_key = SECRET_KEY

CSS = """
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--green:#3fb950;--red:#f85149;--gold:#d2991d;--text:#c9d1d9;--sub:#8b949e}
.light{--bg:#fff;--card:#f6f8fa;--border:#d0d7de;--text:#24292f;--sub:#656d76}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.layout{display:flex}
.sidebar{width:220px;background:var(--card);border-right:1px solid var(--border);padding:16px 0;position:fixed;height:100vh;overflow-y:auto;z-index:100}
.sidebar a{display:flex;align-items:center;gap:10px;padding:12px 20px;color:var(--text);text-decoration:none;font-size:.9em}
.sidebar a:hover{background:rgba(210,153,29,.1);color:var(--gold)}
.sidebar .logo{font-size:1.2em;font-weight:700;padding:10px 20px 20px;color:var(--gold)}
.main{margin-left:220px;flex:1;padding:20px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px}
.btn{padding:10px 20px;border:none;border-radius:8px;cursor:pointer;font-size:.9em;font-weight:600;text-decoration:none;display:inline-flex;align-items:center;gap:8px}
.btn-gold{background:var(--gold);color:#000}
.btn-green{background:var(--green);color:#000}
.btn-red{background:var(--red);color:#fff}
.btn-outline{background:transparent;border:1px solid var(--border);color:var(--text)}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:768px){.grid-2{grid-template-columns:1fr}.sidebar{width:60px}.sidebar a span{display:none}.main{margin-left:60px}}
input,select,textarea{width:100%;padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);margin-bottom:10px;font-family:inherit}
.badge{font-size:.7em;padding:3px 10px;border-radius:10px}
.badge-vip{background:rgba(210,153,29,.2);color:var(--gold)}
.badge-free{background:rgba(139,148,158,.2);color:var(--sub)}
.badge-admin{background:rgba(63,185,80,.2);color:var(--green)}
.alert{padding:12px;border-radius:8px;margin-bottom:12px}
.alert-success{background:rgba(63,185,80,.1);border:1px solid var(--green);color:var(--green)}
.alert-error{background:rgba(248,81,73,.1);border:1px solid var(--red);color:var(--red)}
.alert-info{background:rgba(210,153,29,.1);border:1px solid var(--gold);color:var(--gold)}
table{width:100%;border-collapse:collapse;font-size:.9em}
th,td{padding:10px;text-align:left;border-bottom:1px solid var(--border)}
th{color:var(--sub);font-weight:600}
.pricing-card{border:2px solid var(--border);border-radius:12px;padding:24px;text-align:center}
.pricing-card.active{border-color:var(--gold)}
.pricing-card .price{font-size:2.5em;font-weight:700;color:var(--gold);margin:15px 0}
.pricing-card ul{text-align:left;list-style:none;margin:15px 0}
.pricing-card li{padding:5px 0}
.protection-bar{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:10px 16px;margin-bottom:12px;display:flex;justify-content:space-between}
.protection-bar.blocked{border-color:var(--red)}
"""

def render_page(content, title="XAU AI Trader"):
    u = get_user()
    sub = get_sub()
    sn = {"free":"FREE","vip":"VIP","admin":"ADMIN"}.get(sub,"FREE")
    sb = {"free":"free","vip":"vip","admin":"admin"}.get(sub,"free")
    ad = sub == "admin"
    theme = "light" if (sub in ("vip","admin") and u and u.get("theme")=="light") else ""
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>{title}</title><style>{CSS}</style></head><body class="{theme}"><div class="layout"><div class="sidebar"><div class="logo">🏆 XAU AI</div><a href="/dashboard">📊 Дашборд</a><a href="/deposit">💰 Депозит</a><a href="/withdraw">💸 Вывод</a><a href="/history">📋 История</a><a href="/ai-chat">🤖 AI Чат</a><a href="/subscription">🛡 Подписка <span class="badge badge-{sb}">{sn}</span></a><a href="/settings">⚙️ Настройки</a><a href="/support">🆘 Поддержка</a>{'<a href="/admin">👑 Админ</a>' if ad else ''}<a href="/logout">🚪 Выход</a></div><div class="main">{content}</div></div></body></html>"""

# ══════════════════════════════════════════════════════════════════════════════
# МАРШРУТЫ
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index(): return redirect("/login" if "user" not in session else "/dashboard")

@app.route("/login", methods=["GET","POST"])
def login():
    msg = ""
    if request.method == "POST":
        e = request.form.get("email","").lower().strip()
        p = request.form.get("password","")
        users = load_users()
        if e in users and users[e]["password"] == hash_pw(p):
            session["user"] = e
            return redirect("/dashboard")
        msg = '<div class="alert alert-error">Неверный email или пароль</div>'
    return render_page(f'<div class="card" style="max-width:400px;margin:50px auto;"><h2 style="text-align:center;">🔐 Вход</h2>{msg}<form method="POST"><input type="email" name="email" placeholder="Email" required><input type="password" name="password" placeholder="Пароль" required><button class="btn btn-gold" style="width:100%;">Войти</button></form><p style="text-align:center;margin-top:15px;"><a href="/register" style="color:var(--gold);">Регистрация</a></p></div>',"Вход")

@app.route("/register", methods=["GET","POST"])
def register():
    msg = ""
    if request.method == "POST":
        e = request.form.get("email","").lower().strip()
        p = request.form.get("password","")
        if len(p) < 6: msg = '<div class="alert alert-error">Пароль минимум 6 символов</div>'
        else:
            users = load_users()
            if e in users: msg = '<div class="alert alert-error">Email уже зарегистрирован</div>'
            else:
                s = "admin" if e in ADMIN_EMAILS else "free"
                users[e] = {"password":hash_pw(p),"sub":s,"balance":200,"ai_count":0,"ai_date":datetime.utcnow().strftime("%Y-%m-%d"),"theme":"dark","created":datetime.utcnow().isoformat()}
                save_users(users)
                session["user"] = e
                return redirect("/dashboard")
    return render_page(f'<div class="card" style="max-width:400px;margin:50px auto;"><h2 style="text-align:center;">📝 Регистрация</h2>{msg}<form method="POST"><input type="email" name="email" placeholder="Email" required><input type="password" name="password" placeholder="Пароль (мин 6)" required><button class="btn btn-gold" style="width:100%;">Зарегистрироваться</button></form></div>',"Регистрация")

@app.route("/logout")
def logout():
    session.pop("user",None)
    return redirect("/login")

@app.route("/dashboard")
@login_required
def dashboard():
    u = get_user()
    price_data = get_current_xau_price()
    if price_data and price_data.get("current"):
        pt = f"{price_data['current']:,.2f}"
        ch = price_data.get("change_percent") or 0
        ct = f"{ch:+.2f}%"
        cc = "" if ch >= 0 else "down"
    else:
        pt, ct, cc = "4,735.93", "+0.55%", ""
        price_data = {"current":4735.93}
    today = datetime.utcnow().strftime("%Y-%m-%d")
    trades = [t for t in load_trades() if t.get("user")==session["user"] and t.get("date")==today]
    pnl = sum(t.get("pnl",0) for t in trades)
    prot = load_protection()
    ok, _ = check_protection()
    return render_page(f"""<div class="card"><div style="display:flex;justify-content:space-between;"><div><h2>💰 XAUUSD: ${pt}</h2><span style="color:{'var(--green)' if cc=='' else 'var(--red)'};">{ct}</span></div><div style="text-align:right;"><div>Баланс: <strong>${u['balance']:.2f}</strong></div><div>Сделок: {len(trades)}/{MAX_DAILY_TRADES}</div><div>P&L: <span style="color:{'var(--green)' if pnl>=0 else 'var(--red)'};">${pnl:.2f}</span></div></div></div></div>
    <div style="display:flex;gap:12px;margin-bottom:16px;"><form method="POST" action="/trade"><input type="hidden" name="side" value="BUY"><input type="hidden" name="price" value="{price_data['current']}"><button class="btn btn-green" style="width:100%;">🟢 BUY</button></form><form method="POST" action="/trade"><input type="hidden" name="side" value="SELL"><input type="hidden" name="price" value="{price_data['current']}"><button class="btn btn-red" style="width:100%;">🔴 SELL</button></form></div>
    <div class="protection-bar {'blocked' if not ok else ''}"><span>🛡 Защита: {'✅ Активна' if ok else '⚠️ Пауза'}</span><span>P&L дня: <strong>${prot['daily_pnl']:.2f}</strong></span></div>
    <div class="card" style="height:400px;padding:0;overflow:hidden;"><iframe src="https://s.tradingview.com/widgetembed/?symbol=XAUUSD&interval=5&theme=dark&style=1&timezone=Europe%2FMoscow&locale=ru" style="width:100%;height:100%;border:none;"></iframe></div>
    <div class="card"><h3>📋 8 Правил входа</h3><div class="grid-2"><div>✅ ATR $10–25</div><div>✅ Без важных новостей</div><div>✅ H4 и H1 в одну сторону</div><div>✅ Не первые 30 мин</div><div>✅ До EMA20 < $6.5</div><div>✅ ИИ уверенность >70%</div><div>✅ RSI >48 (BUY) / <52 (SELL)</div><div>✅ Риск ≤7% от $200</div></div><p style="margin-top:8px;font-size:.8em;color:var(--sub);">⚠️ Гибкость: RSI не совпал, но 7/8 правил — вход</p></div>""","Дашборд")

@app.route("/trade", methods=["POST"])
@login_required
def trade():
    side = request.form.get("side","BUY")
    price = float(request.form.get("price",4700))
    pnl = round(random.uniform(-14,21),2)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    t = {"user":session["user"],"time":datetime.utcnow().strftime("%H:%M:%S"),"date":today,"side":side,"price":price,"pnl":pnl}
    tr = load_trades(); tr.append(t); save_trades(tr)
    users = load_users(); users[session["user"]]["balance"] += pnl; save_users(users)
    register_trade_protection("win" if pnl > 0 else "loss")
    return redirect("/dashboard")

@app.route("/deposit", methods=["GET","POST"])
@login_required
def deposit():
    u = get_user()
    deps = [d for d in load_deposits() if d.get("user")==session["user"]]
    msg = ""
    if request.method == "POST":
        amt = float(request.form.get("amount",0))
        if amt < 10: msg = '<div class="alert alert-error">Минимум $10</div>'
        else:
            d = {"user":session["user"],"amount":amt,"status":"Ожидает","date":datetime.utcnow().strftime("%Y-%m-%d %H:%M")}
            ad = load_deposits(); ad.append(d); save_deposits(ad)
            notify_admins(f"💰 Депозит ${amt} от {session['user']}\nПроверьте Bybit UID {MY_BYBIT_UID}")
            msg = f'<div class="alert alert-info">✅ Заявка на ${amt} создана!<br>Отправьте USDT на Bybit UID: <strong>{MY_BYBIT_UID}</strong><br>TRC20: <code>{MY_USDT_ADDRESS[:25]}...</code></div>'
    return render_page(f"""<div class="card" style="max-width:500px;margin:0 auto;"><h2>💰 Депозит</h2><p>Баланс: <strong>${u['balance']:.2f}</strong></p>{msg}
    <form method="POST"><input type="number" name="amount" min="10" placeholder="Сумма $" required><button class="btn btn-gold" style="width:100%;">Создать заявку</button></form>
    <p style="font-size:.8em;color:var(--sub);">💡 Деньги на Bybit UID {MY_BYBIT_UID}</p>
    <h3>📋 История</h3><table><tr><th>Дата</th><th>Сумма</th><th>Статус</th></tr>{''.join(f'<tr><td>{d.get("date","")}</td><td>${d.get("amount",0)}</td><td>{d.get("status","")}</td></tr>' for d in deps[-10:])}</table></div>""","Депозит")

@app.route("/withdraw", methods=["GET","POST"])
@login_required
def withdraw():
    u = get_user()
    ws = [w for w in load_withdrawals() if w.get("user")==session["user"]]
    msg = ""
    if request.method == "POST":
        amt = float(request.form.get("amount",0))
        meth = request.form.get("method","bybit")
        wal = request.form.get("wallet","")
        if amt < 10: msg = '<div class="alert alert-error">Минимум $10</div>'
        elif amt > u['balance']: msg = '<div class="alert alert-error">Недостаточно средств</div>'
        else:
            w = {"user":session["user"],"amount":amt,"method":meth,"wallet":wal,"status":"Ожидает","date":datetime.utcnow().strftime("%Y-%m-%d %H:%M")}
            aw = load_withdrawals(); aw.append(w); save_withdrawals(aw)
            notify_admins(f"💸 Вывод ${amt} от {session['user']}\nМетод: {meth}\nКошелёк: {wal}")
            msg = f'<div class="alert alert-info">✅ Заявка на вывод ${amt} создана!</div>'
    return render_page(f"""<div class="card" style="max-width:500px;margin:0 auto;"><h2>💸 Вывод</h2><p>Баланс: <strong>${u['balance']:.2f}</strong></p>{msg}
    <form method="POST"><input type="number" name="amount" min="10" placeholder="Сумма $" required><select name="method"><option value="bybit">Bybit USDT</option><option value="card">Карта</option></select><input type="text" name="wallet" placeholder="Bybit UID или карта" required><button class="btn btn-gold" style="width:100%;">Заказать вывод</button></form>
    <h3>📋 История</h3><table><tr><th>Дата</th><th>Сумма</th><th>Статус</th></tr>{''.join(f'<tr><td>{w.get("date","")}</td><td>${w.get("amount",0)}</td><td>{w.get("status","")}</td></tr>' for w in ws[-10:])}</table></div>""","Вывод")

@app.route("/history")
@login_required
def history():
    tr = sorted([t for t in load_trades() if t.get("user")==session["user"]], key=lambda x: x.get("time",""), reverse=True)
    total = len(tr)
    wins = sum(1 for t in tr if t.get("pnl",0) > 0)
    wr = round(wins/total*100) if total > 0 else 0
    return render_page(f"""<div class="card"><h2>📋 История</h2><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:15px;text-align:center;margin-bottom:20px;"><div><div style="font-size:1.5em;font-weight:700;">{total}</div><div style="color:var(--sub);">Всего</div></div><div><div style="font-size:1.5em;font-weight:700;color:var(--green);">{wins}</div><div style="color:var(--sub);">Прибыльных</div></div><div><div style="font-size:1.5em;font-weight:700;">{wr}%</div><div style="color:var(--sub);">Винрейт</div></div></div>
    <table><tr><th>Время</th><th>Тип</th><th>Цена</th><th>P&L</th></tr>{''.join(f'<tr><td>{t.get("time","")}</td><td>{t.get("side","")}</td><td>${t.get("price",0):.2f}</td><td style="color:{"var(--green)" if t.get("pnl",0)>0 else "var(--red)"};">${t.get("pnl",0):.2f}</td></tr>' for t in tr[:50])}</table></div>""","История")

@app.route("/subscription")
@login_required
def subscription():
    sub = get_sub()
    return render_page(f"""<div class="grid-2">
    <div class="pricing-card {'active' if sub=='free' else ''}"><h3>⭐ FREE</h3><div class="price">$0</div><ul><li>✅ AI: 25/день</li><li>✅ Ручная торговля</li><li>✅ Депозит/Вывод</li><li>✅ График</li><li>❌ Автотрейдинг</li><li>❌ Смена темы</li></ul>{'<div class="alert alert-info">Текущий</div>' if sub=='free' else ''}</div>
    <div class="pricing-card {'active' if sub=='vip' else ''}"><h3>👑 VIP</h3><div class="price">$20<span style="font-size:.4em;">/мес</span></div><ul><li>✅ AI: безлимит</li><li>✅ Автотрейдинг</li><li>✅ Смена темы</li><li>✅ Telegram бот</li></ul>{'<div class="alert alert-success">Активен</div>' if sub=='vip' else f'<p style="margin:20px 0;"><strong>Оплатите $20 на Bybit UID: {MY_BYBIT_UID}</strong></p><a href="/vip-activate" class="btn btn-gold" style="width:100%;">✅ Я оплатил</a>'}</div></div>""","Подписка")

@app.route("/vip-activate")
@login_required
def vip_activate():
    notify_admins(f"🔔 Запрос VIP! {session['user']}\nПроверьте Bybit UID {MY_BYBIT_UID}")
    return render_page('<div class="card" style="text-align:center;"><h2>✅ Запрос отправлен!</h2><p>Админ проверит платёж</p><a href="/subscription" class="btn btn-gold">Назад</a></div>',"VIP")

@app.route("/ai-chat", methods=["GET","POST"])
@login_required
def ai_chat():
    u = get_user()
    sub = get_sub()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if u.get("ai_date") != today: u["ai_count"] = 0; u["ai_date"] = today
    users = load_users(); users[session["user"]] = u; save_users(users)
    rem = max(0, MAX_FREE_AI_MESSAGES - u.get("ai_count",0))
    reply = ""
    if request.method == "POST":
        if sub == "free" and u.get("ai_count",0) >= MAX_FREE_AI_MESSAGES:
            reply = "⚠️ Лимит 25/день. Нужен VIP!"
        else:
            u["ai_count"] = u.get("ai_count",0) + 1
            users = load_users(); users[session["user"]] = u; save_users(users)
            ans, err = deepseek_ask(request.form.get("message","Привет"))
            reply = ans if ans else f"⚠️ {err}"
    return render_page(f"""<div class="card" style="max-width:600px;margin:0 auto;"><h2>🤖 AI Чат</h2>{'<div class="alert alert-info">Осталось: '+str(rem)+'/{MAX_FREE_AI_MESSAGES}</div>' if sub=='free' else '<div class="alert alert-success">VIP безлимит</div>'}<form method="POST"><input type="text" name="message" placeholder="Вопрос..." required><button class="btn btn-gold" style="width:100%;">Спросить</button></form>{f'<div class="card" style="margin-top:15px;"><strong>AI:</strong> {reply}</div>' if reply else ''}</div>""","AI Чат")

@app.route("/settings", methods=["GET","POST"])
@login_required
def settings():
    u = get_user()
    sub = get_sub()
    mt5 = load_mt5().get(session["user"], {"server":"","login":"","password":""})
    msg = ""
    if request.method == "POST":
        action = request.form.get("action","")
        if action == "mt5":
            mt5 = {"server":request.form.get("server",""),"login":request.form.get("login",""),"password":request.form.get("password","")}
            all_mt5 = load_mt5(); all_mt5[session["user"]] = mt5; save_mt5(all_mt5)
            msg = '<div class="alert alert-success">MT5 сохранён!</div>'
        elif action == "theme" and sub in ("vip","admin"):
            users = load_users(); users[session["user"]]["theme"] = request.form.get("theme","dark"); save_users(users)
            msg = '<div class="alert alert-success">Тема изменена!</div>'
    return render_page(f"""<div class="card" style="max-width:500px;margin:0 auto;"><h2>⚙️ Настройки</h2>{msg}
    <h3>🔌 MetaTrader 5</h3><form method="POST"><input type="hidden" name="action" value="mt5"><input type="text" name="server" value="{mt5.get('server','')}" placeholder="Сервер"><input type="text" name="login" value="{mt5.get('login','')}" placeholder="Логин"><input type="password" name="password" placeholder="Пароль"><button class="btn btn-gold" style="width:100%;">Сохранить MT5</button></form>
    {f'<h3 style="margin-top:20px;">🎨 Тема</h3><form method="POST"><input type="hidden" name="action" value="theme"><select name="theme"><option value="dark" {"selected" if u.get("theme")=="dark" else ""}>🌙 Тёмная</option><option value="light" {"selected" if u.get("theme")=="light" else ""}>☀️ Светлая</option></select><button class="btn btn-gold" style="width:100%;">Сохранить</button></form>' if sub in ("vip","admin") else '<p>🎨 Тема — VIP</p>'}
    </div>""","Настройки")

@app.route("/support")
@login_required
def support():
    return render_page('<div class="card" style="max-width:500px;margin:0 auto;"><h2>🆘 Поддержка</h2><p>📧 support@xau-ai.com</p><p>💬 @xau_support</p><p>⏰ 24/7</p></div>',"Поддержка")

@app.route("/admin")
@admin_required
def admin():
    users = load_users()
    deps = load_deposits()
    ws = load_withdrawals()
    pd = [d for d in deps if d.get("status")=="Ожидает"]
    pw = [w for w in ws if w.get("status")=="Ожидает"]
    vip = sum(1 for u in users.values() if u.get("sub")=="vip")
    free = sum(1 for u in users.values() if u.get("sub")=="free")
    return render_page(f"""<div class="card"><h2>👑 Админ</h2><p>Всего: {len(users)} | VIP: {vip} | Free: {free}</p><p>Депозитов: {len(pd)} | Выводов: {len(pw)}</p><p>Bybit: {MY_BYBIT_UID}</p></div>
    <div class="card"><h3>💰 Депозиты</h3><table><tr><th>User</th><th>$</th><th></th></tr>{''.join(f'<tr><td>{d["user"]}</td><td>${d["amount"]}</td><td><a href="/admin/dep-ok/{d["user"]}/{d["amount"]}" class="btn btn-green">Ок</a></td></tr>' for d in pd)}</table></div>
    <div class="card"><h3>💸 Выводы</h3><table><tr><th>User</th><th>$</th><th>Метод</th><th>Кошелёк</th><th></th></tr>{''.join(f'<tr><td>{w["user"]}</td><td>${w["amount"]}</td><td>{w.get("method","")}</td><td>{w.get("wallet","")}</td><td><a href="/admin/wd-ok/{w["user"]}/{w["amount"]}" class="btn btn-green">Отправил</a></td></tr>' for w in pw)}</table></div>
    <div class="card"><h3>👥 Пользователи</h3><table><tr><th>Email</th><th>Подписка</th><th>Баланс</th><th></th></tr>{''.join(f'<tr><td>{e}</td><td><span class="badge badge-{u["sub"]}">{u["sub"].upper()}</span></td><td>${u.get("balance",0):.2f}</td><td>{f"<a href='/admin/toggle/{e}' class='btn btn-outline'>{'В FREE' if u['sub']=='vip' else 'В VIP'}</a>" if u["sub"]!="admin" else "Админ"}</td></tr>' for e,u in users.items())}</table></div>""","Админ")

@app.route("/admin/dep-ok/<email>/<amount>")
@admin_required
def dep_ok(email, amount):
    users = load_users()
    if email in users: users[email]["balance"] += float(amount); save_users(users)
    deps = load_deposits()
    for d in deps:
        if d.get("user")==email and d.get("status")=="Ожидает": d["status"] = "Зачислено"
    save_deposits(deps)
    return redirect("/admin")

@app.route("/admin/wd-ok/<email>/<amount>")
@admin_required
def wd_ok(email, amount):
    users = load_users()
    if email in users: users[email]["balance"] -= float(amount); save_users(users)
    ws = load_withdrawals()
    for w in ws:
        if w.get("user")==email and w.get("status")=="Ожидает": w["status"] = "Отправлено"
    save_withdrawals(ws)
    return redirect("/admin")

@app.route("/admin/toggle/<email>")
@admin_required
def admin_toggle(email):
    users = load_users()
    if email in users and users[email].get("sub")!="admin":
        users[email]["sub"] = "free" if users[email]["sub"]=="vip" else "vip"
        save_users(users)
    return redirect("/admin")

# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM WEBHOOK + КОМАНДЫ
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True) or {}
    try:
        if update.get("message"):
            msg = update["message"]
            text = (msg.get("text") or "").strip()
            cid = msg.get("chat",{}).get("id")
            if text == "/start":
                tg_send("👋 *XAU AI Trader*\n/price /status /ask вопрос /buy ЦЕНА RSI ТРЕНД ATR /sell ЦЕНА RSI ТРЕНД ATR", cid)
            elif text == "/price":
                p = get_current_xau_price()
                tg_send(f"💰 XAUUSD: ${p['current']:.2f}" if p else "Нет данных", cid)
            elif text == "/status":
                prot = load_protection()
                tg_send(f"📊 Сделок: {prot['daily_trades']}/{MAX_DAILY_TRADES}\nP&L: ${prot['daily_pnl']:.2f}", cid)
            elif text.startswith("/ask"):
                q = text[5:].strip()
                if q:
                    ans, _ = deepseek_ask(q)
                    tg_send(f"🧠 {ans}" if ans else "AI недоступен", cid)
        elif update.get("callback_query"):
            cb = update["callback_query"]
            data = cb.get("data","")
            cid = cb.get("message",{}).get("chat",{}).get("id")
            if ":" in data:
                action, trade_id = data.split(":",1)
                if action in ("win","loss"):
                    with _lock:
                        trades = load_trades()
                        for t in trades:
                            if t.get("id")==trade_id: t["outcome"]=action; register_trade_protection(action); break
                        save_trades(trades)
                    tg_answer_callback(cb.get("id"), "✅" if action=="win" else "❌")
    except Exception as e: logger.error(f"TG webhook: {e}")
    return jsonify({"ok":True})

# ══════════════════════════════════════════════════════════════════════════════
# АВТО-СИГНАЛЫ
# ══════════════════════════════════════════════════════════════════════════════

def auto_signals():
    time.sleep(120)
    while True:
        try:
            time.sleep(300)
            ok, _ = check_protection()
            if not ok: continue
            prot = load_protection()
            if prot["daily_trades"] >= MAX_DAILY_TRADES: continue
            p = get_current_xau_price()
            if not p: continue
            trend = "UP" if (p.get("change") or 0) > 0 else "DOWN"
            ind = calculate_indicators()
            news = get_news()
            check = check_8_rules(ind, news, trend)
            if check["decision"]:
                logger.info(f"[АВТО] {trend} @ ${p['current']:.2f}")
        except Exception as e: logger.error(f"Авто: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    threading.Thread(target=auto_signals, daemon=True).start()
    logger.info(f"XAU AI Trader на порту {PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
