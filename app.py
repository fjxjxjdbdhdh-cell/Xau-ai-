"""
XAUUSD AI Trading Bot — single-file Flask app for GitHub → Render.
Все сообщения и интерфейс — на русском языке.
Приложение index.html на главной странице.
8 правил входа ($200) + гибкость: вход без RSI если остальное совпало.
Порог уверенности 70%.
"""

import json, logging, math, os, random, re, threading, time, uuid, xml.etree.ElementTree as ET
from collections import defaultdict, deque
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string, request

# ────────────────────────────────────────────────────────────────────────────
# Окружение и константы
# ────────────────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8788731785:AAFhOHviyVMkuDS1psfjnk8XvZxXviPmfcg").strip()
CHAT_IDS_STR = os.environ.get("CHAT_IDS", "5246379098,6206180654").strip()
CHAT_IDS = [cid.strip() for cid in CHAT_IDS_STR.split(",") if cid.strip()]
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://openrouter.ai/api").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek/deepseek-chat")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()
PORT = int(os.environ.get("PORT", 5000))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "xau-ai-secret")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

LOG_FILE = os.path.join(DATA_DIR, "webhook.log")
TRADES_FILE = os.path.join(DATA_DIR, "trades.json")
WEIGHTS_FILE = os.path.join(DATA_DIR, "weights.json")
RULES_FILE = os.path.join(DATA_DIR, "rules.json")
INSIGHTS_FILE = os.path.join(DATA_DIR, "insights.json")
KNOWLEDGE_FILE = os.path.join(DATA_DIR, "knowledge_base.json")
PINE_FILE = os.path.join(DATA_DIR, "pine_scripts.json")
DYN_CMDS_FILE = os.path.join(DATA_DIR, "dynamic_commands.json")
PENDING_FILE = os.path.join(DATA_DIR, "pending_alerts.json")
SIM_FILE = os.path.join(DATA_DIR, "simulator.json")

CONFIDENCE_THRESHOLD = 0.7
HIGH_CONF = 0.85
GA_INTERVAL = 10
GA_POPULATION = 20
GA_GENERATIONS = 15
GA_MUTATION_RATE = 0.2

DEFAULT_WEIGHTS = {"signal": 0.30, "price": 0.10, "rsi": 0.25, "trend": 0.25, "atr": 0.10}

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# ────────────────────────────────────────────────────────────────────────────
# Логирование
# ────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("xau-ai")

trade_log = logging.getLogger("trades")
trade_log.setLevel(logging.INFO)
if not any(isinstance(h, logging.FileHandler) for h in trade_log.handlers):
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    trade_log.addHandler(fh)

# ────────────────────────────────────────────────────────────────────────────
# Хранение JSON
# ────────────────────────────────────────────────────────────────────────────

_lock = threading.Lock()

def _read_json(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return default

def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def load_weights():
    w = _read_json(WEIGHTS_FILE, None)
    if not isinstance(w, dict) or set(w.keys()) != set(DEFAULT_WEIGHTS.keys()): return dict(DEFAULT_WEIGHTS)
    return w

def save_weights(w): _write_json(WEIGHTS_FILE, w)
def load_trades(): return _read_json(TRADES_FILE, [])
def save_trades(t): _write_json(TRADES_FILE, t)
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
def load_simulator(): return _read_json(SIM_FILE, {"balance":10000,"trades":[],"daily_pnl":0,"daily_start":datetime.utcnow().isoformat()})
def save_simulator(s): _write_json(SIM_FILE, s)

# ────────────────────────────────────────────────────────────────────────────
# Telegram
# ────────────────────────────────────────────────────────────────────────────

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
    logger.info(f"TG send to {cid}: {text[:80]}...")
    result = _tg("sendMessage", payload)
    for cid2 in CHAT_IDS[1:]:
        payload["chat_id"] = cid2
        _tg("sendMessage", payload)
    return result

def tg_send_all(text, reply_markup=None, parse_mode="Markdown"):
    for cid in CHAT_IDS:
        tg_send(text, chat_id=cid, reply_markup=reply_markup, parse_mode=parse_mode)

def tg_edit(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id":chat_id, "message_id":message_id, "text":text, "parse_mode":"Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    return _tg("editMessageText", payload)

def tg_answer_callback(cb_id, text=None):
    payload = {"callback_query_id":cb_id}
    if text: payload["text"] = text
    return _tg("answerCallbackQuery", payload)

def tg_set_webhook(url):
    return _tg("setWebhook", {"url":url, "allowed_updates":["message","callback_query"]})

# ────────────────────────────────────────────────────────────────────────────
# ИИ-движок
# ────────────────────────────────────────────────────────────────────────────

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

# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# apply_rules — 8 ПРАВИЛ ВХОДА ($200) + ВХОД БЕЗ RSI ЕСЛИ ОСТАЛЬНОЕ СОВПАЛО + ПОРОГ 70%
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

def apply_rules(base_conf, raw_input, rules):
    reasons = []
    conf = base_conf
    threshold = 0.70  # ★ ПОРОГ 70%
    sig_str = str(raw_input.get("signal","")).strip().upper()
    preferred = str(rules.get("preferred_signal","HOLD")).upper()
    bias_strength = float(rules.get("bias_strength",0))
    
    # Стандартная проверка bias
    if preferred in ("BUY","SELL") and sig_str:
        if sig_str == preferred: conf = min(1,conf+0.1*bias_strength); reasons.append(f"сигнал совпадает с {preferred}-предпочтением (+{0.1*bias_strength:.3f})")
        elif sig_str in ("BUY","SELL"): conf = max(0,conf-0.1*bias_strength); reasons.append(f"сигнал против {preferred}-предпочтения (−{0.1*bias_strength:.3f})")
    
    # ===== 8 ПРАВИЛ ВХОДА ($200) =====
    
    # Правило 1: ATR $10-25
    atr_ok = True
    try:
        atr_v = float(raw_input.get("atr", 0))
        if 10 <= atr_v <= 25:
            conf = min(1.0, conf + 0.03)
            reasons.append(f"✅ ATR {atr_v} в диапазоне 10-25 (+0.03)")
        elif atr_v > 25:
            atr_ok = False; conf = max(0.0, conf - 0.05)
            reasons.append(f"⚠️ ATR {atr_v} выше 25 (-0.05)")
        elif atr_v < 10:
            atr_ok = False; conf = max(0.0, conf - 0.02)
            reasons.append(f"⚠️ ATR {atr_v} ниже 10 (-0.02)")
    except: atr_ok = False
    
    # Правило 2: Тренд в одну сторону
    trend_ok = True
    trend = str(raw_input.get("trend","")).upper()
    if trend in ("UP", "DOWN"):
        conf = min(1.0, conf + 0.04)
        reasons.append(f"✅ Тренд {trend} подтверждён (+0.04)")
    else:
        trend_ok = False
    
    # Правило 3: До EMA20 < $6.5
    ema_ok = True
    try:
        price_v = float(raw_input.get("price", 0))
        target = float(rules.get("price_target", price_v)) if rules.get("price_target") else price_v
        ema_distance = abs(price_v - target)
        if ema_distance < 6.5:
            conf = min(1.0, conf + 0.05)
            reasons.append(f"✅ Цена близко к EMA20 (${ema_distance:.2f} < $6.5) (+0.05)")
        else:
            ema_ok = False; conf = max(0.0, conf - 0.03)
            reasons.append(f"⚠️ Цена далеко от EMA20 (${ema_distance:.2f}) (-0.03)")
    except: ema_ok = False
    
    # Правило 4: RSI >48 для BUY, <52 для SELL (★ МОЖНО ПРОПУСТИТЬ!)
    rsi_ok = True
    try:
        rsi_v = float(raw_input.get("rsi", 50))
        if sig_str == "BUY" and rsi_v > 48:
            conf = min(1.0, conf + 0.04)
            reasons.append(f"✅ RSI {rsi_v} > 48 для BUY (+0.04)")
        elif sig_str == "BUY" and rsi_v <= 48:
            rsi_ok = False; conf = max(0.0, conf - 0.05)
            reasons.append(f"❌ RSI {rsi_v} ≤ 48 для BUY (-0.05)")
        if sig_str == "SELL" and rsi_v < 52:
            conf = min(1.0, conf + 0.04)
            reasons.append(f"✅ RSI {rsi_v} < 52 для SELL (+0.04)")
        elif sig_str == "SELL" and rsi_v >= 52:
            rsi_ok = False; conf = max(0.0, conf - 0.05)
            reasons.append(f"❌ RSI {rsi_v} ≥ 52 для SELL (-0.05)")
        
        # Старая логика RSI
        oversold = float(rules.get("rsi_oversold",30))
        overbought = float(rules.get("rsi_overbought",70))
        if sig_str=="BUY" and rsi_v<=oversold: conf=min(1,conf+0.05); reasons.append(f"RSI {rsi_v} ≤ перепроданность {oversold} (+0.05)")
        elif sig_str=="SELL" and rsi_v>=overbought: conf=min(1,conf+0.05); reasons.append(f"RSI {rsi_v} ≥ перекупленность {overbought} (+0.05)")
    except: rsi_ok = False
    
    # Правило 5: Нет новостей
    news_ok = True
    if rules.get("risk_mode") != "elevated":
        conf = min(1.0, conf + 0.02)
        reasons.append(f"✅ Нет важных новостей (+0.02)")
    else:
        news_ok = False; conf = max(0.0, conf - 0.04)
        reasons.append(f"⚠️ Есть новости — осторожно (-0.04)")
    
    # Правило 6: Не первые 30 минут
    time_ok = True
    now = datetime.utcnow()
    if now.minute >= 30:
        conf = min(1.0, conf + 0.02)
        reasons.append(f"✅ Не первые 30 минут (+0.02)")
    else:
        time_ok = False; conf = max(0.0, conf - 0.03)
        reasons.append(f"⚠️ Первые 30 минут — осторожно (-0.03)")
    
    # ★★★ ГЛАВНАЯ ЛОГИКА ВХОДА ★★★
    total_ok = sum([atr_ok, trend_ok, ema_ok, rsi_ok, news_ok, time_ok])
    total_rules = sum(1 for r in reasons if r.startswith("✅"))
    
    # Если RSI не совпал, но ВСЁ остальное совпало (5 из 6) — вход разрешён!
    if not rsi_ok and total_ok >= 5:
        reasons.append(f"⚠️ RSI не идеален, но {total_ok}/6 правил совпало — ВХОД РАЗРЕШЁН!")
        conf = max(conf, 0.65)  # Минимум 65% уверенности
    
    # Если 5+ правил совпало (включая RSI) — отлично!
    if total_rules >= 5:
        reasons.append(f"🎯 {total_rules}/8 правил совпало — отличный сигнал!")
    
    # Старая проверка ATR
    try:
        atr_v2 = float(raw_input.get("atr", 0))
        atr_cap = float(rules.get("atr_caution_above",50))
        if atr_v2 > atr_cap: conf = max(0,conf-min(0.15,(atr_v2-atr_cap)/200))
    except: pass
    
    if rules.get("risk_mode")=="elevated": threshold=min(0.95,threshold+0.05)
    
    return round(max(0,min(1,conf)),4), reasons, round(threshold,4)

# ────────────────────────────────────────────────────────────────────────────
# Генетика
# ────────────────────────────────────────────────────────────────────────────

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

# ────────────────────────────────────────────────────────────────────────────
# Finnhub API
# ────────────────────────────────────────────────────────────────────────────

def finnhub_news():
    if not FINNHUB_API_KEY: return []
    try:
        r = requests.get(f"https://finnhub.io/api/v1/news?category=forex&token={FINNHUB_API_KEY}", timeout=10)
        if r.status_code != 200: return []
        news = r.json()[:10]
        records = []
        for n in news:
            text = (n.get("headline","") + " " + n.get("summary","")).lower()
            records.append({"query":f"finnhub:{n.get('headline','')[:80]}","fetched_at":datetime.utcnow().isoformat()+"Z","characters_extracted":len(text),"analysis":{"bullish_hits":text.count("bull")+text.count("buy")+text.count("rise"),"bearish_hits":text.count("bear")+text.count("sell")+text.count("drop"),"risk_hits":text.count("risk")+text.count("volatile"),"rsi_mentions":[],"sample_snippets":[n.get("headline",""),n.get("summary","")[:200]]}})
        logger.info(f"[finnhub] получено {len(records)} новостей")
        return records
    except: return []

# ────────────────────────────────────────────────────────────────────────────
# Цена XAUUSD
# ────────────────────────────────────────────────────────────────────────────

def get_current_price_finnhub():
    if not FINNHUB_API_KEY: return None
    try:
        r = requests.get(f"https://finnhub.io/api/v1/quote?symbol=XAUUSD&token={FINNHUB_API_KEY}",timeout=10)
        if r.status_code!=200: return None
        data = r.json()
        if data.get("c"): return {"current":data.get("c"),"high":data.get("h"),"low":data.get("l"),"open":data.get("o"),"prev_close":data.get("pc"),"change":round(data.get("c",0)-data.get("pc",0),2) if data.get("pc") else None}
        return None
    except: return None

def get_xau_price_reserve():
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold",timeout=10)
        if r.status_code==200:
            data = r.json()
            if isinstance(data,list) and len(data)>0: return float(data[0].get("price",0))
        return None
    except: return None

def get_current_xau_price():
    f = get_current_price_finnhub()
    if f and f.get("current"): return f
    r = get_xau_price_reserve()
    if r: return {"current":r}
    return None

def format_price_info():
    now = datetime.utcnow(); moscow_time = now + timedelta(hours=3)
    day_names = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]
    day_name = day_names[now.weekday()]
    price_data = get_current_xau_price()
    rules = load_rules()
    msg = f"📅 *{day_name} {moscow_time.strftime('%H:%M')} (МСК)*\n"
    if price_data and price_data.get("current"):
        price = price_data["current"]; change = price_data.get("change",0)
        emoji = "🟢" if change>0 else "🔴" if change<0 else "⚪"
        msg += f"💰 *XAUUSD: ${price:.2f}* {emoji}\n"
        if change: msg += f"📊 Изменение: {change:+.2f}\n"
    else: msg += f"⚠️ Рынок закрыт.\n"
    msg += f"━━━━━━━━━━━━━━\n📈 *AI:*\n• Bias: {rules.get('market_bias','—')}\n• Signal: {rules.get('preferred_signal','—')}\n• Порог: {int(rules.get('confidence_threshold',0.7)*100)}%\n"
    return msg

# ────────────────────────────────────────────────────────────────────────────
# Парсинг сайтов
# ────────────────────────────────────────────────────────────────────────────

FINANCE_SITES = ["investing.com","fxstreet.com","dailyfx.com","kitco.com","tradingview.com","marketwatch.com","bloomberg.com","reuters.com","cnbc.com"]
LEARNING_SITES = ["https://www.tradingview.com/ideas/gold/","https://www.investopedia.com/articles/trading/","https://www.babypips.com/learn/forex"]
QUERIES_TPL = ["XAUUSD прогноз","gold price forecast {y}","XAUUSD technical analysis"]
BULLISH_TERMS = ["bullish","rally","buy","long","рост","покупка","вверх","бычий"]
BEARISH_TERMS = ["bearish","decline","sell","short","падение","продажа","вниз","медвежий"]
RSI_PATTERN = re.compile(r"\brsi\b[^\d]{0,12}(\d{1,3})", re.IGNORECASE)

def ddg_search(query, timeout=8):
    try:
        r = requests.get(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}", headers={"User-Agent":USER_AGENT}, timeout=timeout)
        if r.status_code!=200: return ""
        soup = BeautifulSoup(r.text,"html.parser")
        snips = [el.get_text(" ",strip=True) for el in soup.select("a.result__snippet, div.result__snippet") if len(el.get_text(" ",strip=True))>30]
        return " \n ".join(snips[:15])
    except: return ""

def analyze_text(text):
    lower = text.lower()
    return {"bullish_hits":sum(lower.count(t) for t in BULLISH_TERMS),"bearish_hits":sum(lower.count(t) for t in BEARISH_TERMS),"risk_hits":lower.count("risk")+lower.count("volatile"),"rsi_mentions":[int(m) for m in RSI_PATTERN.findall(text) if 0<=int(m)<=100][:10],"sample_snippets":[s.strip() for s in text.split("\n") if s.strip()][:3]}

def scrape_learning_sites():
    records = []
    for url in LEARNING_SITES:
        try:
            r = requests.get(url, headers={"User-Agent":USER_AGENT}, timeout=15)
            if r.status_code!=200: continue
            text = BeautifulSoup(r.text,"html.parser").get_text(" ",strip=True)[:5000]
            if text: records.append({"query":f"learn:{url[:60]}","fetched_at":datetime.utcnow().isoformat()+"Z","characters_extracted":len(text),"analysis":analyze_text(text)})
            time.sleep(0.5)
        except: pass
    return records

def gather_insights():
    year = datetime.utcnow().year
    queries = [q.format(y=year) for q in QUERIES_TPL]
    sites = random.sample(FINANCE_SITES, k=min(10,len(FINANCE_SITES)))
    all_queries = queries + [f"site:{s} XAUUSD" for s in sites]
    records = []
    for q in all_queries:
        text = ddg_search(q)
        records.append({"query":q,"fetched_at":datetime.utcnow().isoformat()+"Z","characters_extracted":len(text),"analysis":analyze_text(text) if text else {"bullish_hits":0,"bearish_hits":0,"risk_hits":0,"rsi_mentions":[],"sample_snippets":[]}})
        time.sleep(0.3)
    fn = finnhub_news()
    if fn: records.extend(fn)
    learn = scrape_learning_sites()
    if learn: records.extend(learn)
    return records

def update_knowledge_base(records):
    kb = load_knowledge()
    new_snips = [{"q":r["query"],"s":s,"at":r["fetched_at"]} for r in records for s in r["analysis"]["sample_snippets"]]
    kb["snippets"] = (new_snips + kb.get("snippets",[]))[:500]
    bull = sum(r["analysis"]["bullish_hits"] for r in records)
    bear = sum(r["analysis"]["bearish_hits"] for r in records)
    risk = sum(r["analysis"]["risk_hits"] for r in records)
    bias = "бычье" if bull>bear else "медвежье" if bear>bull else "нейтральное"
    kb["summary"] = f"Настроение: {bias} (бычьих {bull}, медвежьих {bear}, риск {risk}). Источников: {len(records)}."
    kb["updated_at"] = datetime.utcnow().isoformat()+"Z"
    save_knowledge(kb)
    return kb

def derive_rules(insight_records, trade_history):
    if not insight_records: return default_rules()
    total_bull = sum(r["analysis"]["bullish_hits"] for r in insight_records)
    total_bear = sum(r["analysis"]["bearish_hits"] for r in insight_records)
    market_bias = "bullish" if total_bull>total_bear else "bearish"
    return {"generated_at":datetime.utcnow().isoformat()+"Z","market_bias":market_bias,"bias_strength":round(abs(total_bull-total_bear)/max(total_bull+total_bear,1),3),"preferred_signal":"BUY" if market_bias=="bullish" else "SELL","rsi_oversold":30,"rsi_overbought":70,"price_target":None,"risk_mode":"normal","atr_caution_above":50,"confidence_threshold":0.7,"historical_winrate":None,"based_on":{"insight_records":len(insight_records)}}

def default_rules():
    return {"generated_at":datetime.utcnow().isoformat()+"Z","market_bias":"neutral","bias_strength":0,"preferred_signal":"HOLD","rsi_oversold":30,"rsi_overbought":70,"price_target":None,"risk_mode":"normal","atr_caution_above":50,"confidence_threshold":0.7,"historical_winrate":None,"based_on":{"insight_records":0}}

def evolve_insights(trade_history):
    new_records = gather_insights()
    history = (load_insights() + new_records)[-200:]
    _write_json(INSIGHTS_FILE, history)
    update_knowledge_base(new_records)
    rules = derive_rules(history, trade_history)
    save_rules(rules)
    return {"new":len(new_records),"rules":rules}

# ────────────────────────────────────────────────────────────────────────────
# Само-тюнинг
# ────────────────────────────────────────────────────────────────────────────

def hourly_self_tune():
    while True:
        time.sleep(3600)
        try:
            with _lock: trades = load_trades()
            labeled = [t for t in trades if t.get("outcome") in ("win","loss")][-30:]
            if len(labeled)<10: continue
            wr = sum(1 for t in labeled if t["outcome"]=="win")/len(labeled)
            rules = load_rules()
            old = float(rules.get("confidence_threshold") or 0.7)
            new = round(max(0.5,min(0.8,old+(0.6-wr)*0.1)),3)
            if abs(new-old)>=0.005: rules["confidence_threshold"] = new; save_rules(rules)
        except: pass

# ────────────────────────────────────────────────────────────────────────────
# DeepSeek Чат
# ────────────────────────────────────────────────────────────────────────────

DEEPSEEK_SYSTEM = "Ты — трейдер по золоту. Отвечай на русском."

def deepseek_ask(question):
    if not DEEPSEEK_API_KEY: return None, "Нет ключа"
    with _lock: trades = load_trades()
    rules = load_rules(); kb = load_knowledge()
    labeled = [t for t in trades if t.get("outcome") in ("win","loss")]
    wins = sum(1 for t in labeled if t["outcome"]=="win")
    wr = (wins/len(labeled)) if labeled else None
    price_data = get_current_xau_price()
    price_info = f"Цена XAUUSD: ${price_data['current']:.2f}" if price_data and price_data.get("current") else "Цена недоступна"
    context = f"ЦЕНА: {price_info}\nПравила: {json.dumps(rules, ensure_ascii=False)[:500]}\nСделок: {len(trades)}, винрейт: {round(wr,3) if wr else 'нет'}"
    payload = {"model":DEEPSEEK_MODEL,"messages":[{"role":"system","content":DEEPSEEK_SYSTEM},{"role":"system","content":f"КОНТЕКСТ:\n{context}"},{"role":"user","content":question}],"temperature":0.5,"max_tokens":700}
    try:
        headers = {"Authorization":f"Bearer {DEEPSEEK_API_KEY}","Content-Type":"application/json","HTTP-Referer":PUBLIC_URL or "https://xau-ai.onrender.com","X-Title":"XAU AI"}
        r = requests.post(f"{DEEPSEEK_BASE_URL}/v1/chat/completions", headers=headers, json=payload, timeout=45)
        if r.status_code!=200: return None, f"Ошибка {r.status_code}"
        return r.json()["choices"][0]["message"]["content"].strip(), None
    except Exception as e: return None, f"Ошибка: {e}"

# ────────────────────────────────────────────────────────────────────────────
# Симулятор
# ────────────────────────────────────────────────────────────────────────────

def sim_trade(signal, price, sl, tp):
    sim = load_simulator()
    trade = {"id":uuid.uuid4().hex[:8],"signal":signal,"price":price,"sl":sl,"tp":tp,"time":datetime.utcnow().isoformat(),"outcome":None}
    outcome = "win" if random.random()>0.5 else "loss"
    pnl = abs(float(tp)-float(price))*10 if outcome=="win" else -abs(float(price)-float(sl))*10
    trade["outcome"] = outcome; trade["pnl"] = round(pnl,2)
    sim["trades"].append(trade); sim["balance"] += trade["pnl"]; sim["daily_pnl"] += trade["pnl"]
    save_simulator(sim)
    return trade, sim

def format_portfolio():
    sim = load_simulator()
    trades = sim["trades"]
    wins = [t for t in trades if t["outcome"]=="win"]; losses = [t for t in trades if t["outcome"]=="loss"]
    wr = (len(wins)/len(trades)*100) if trades else 0
    pf = sum(t["pnl"] for t in wins)/abs(sum(t["pnl"] for t in losses)) if losses else 0
    emoji = "🟢" if sim["daily_pnl"]>=0 else "🔴"
    return f"📊 *Симулятор*\n💰 Баланс: ${sim['balance']:.2f}\n📈 P&L: {emoji} ${sim['daily_pnl']:.2f}\n🎯 Винрейт: {wr:.0f}% | PF: {pf:.2f}"

# ────────────────────────────────────────────────────────────────────────────
# Конвейер сигнала
# ────────────────────────────────────────────────────────────────────────────

def _signal_label(sig): return "🟢 ПОКУПКА" if str(sig).upper()=="BUY" else "🔴 ПРОДАЖА" if str(sig).upper()=="SELL" else "⚪"
def _decision_label(dec): return "ИСПОЛНИТЬ" if dec=="execute" else "ПРОПУСТИТЬ"

def format_signal_ru(trade, reasons):
    inp = trade["input"]
    rs = "\n".join(f"  • {r}" for r in reasons) if reasons else "  • —"
    return f"{_signal_label(inp.get('signal'))} *XAUUSD*\n*Цена:* `{inp.get('price')}`  *RSI:* `{inp.get('rsi')}`  *Тренд:* `{inp.get('trend')}`  *ATR:* `{inp.get('atr')}`\n*Уверенность:* `{int(trade['confidence']*100)}%`  *Порог:* `{int(trade['threshold']*100)}%`\n*Решение:* *{_decision_label(trade['decision'])}*\n*Обоснование:*\n{rs}"

def build_outcome_keyboard(trade_id): return {"inline_keyboard":[[{"text":"✅ Победа","callback_data":f"win:{trade_id}"},{"text":"❌ Убыток","callback_data":f"loss:{trade_id}"}]]}
def build_alert_keyboard(alert_id): return {"inline_keyboard":[[{"text":"✅ Согласен","callback_data":f"alert_ok:{alert_id}"},{"text":"🚫 Отклонить","callback_data":f"alert_no:{alert_id}"},{"text":"❓ Почему?","callback_data":f"alert_why:{alert_id}"}]]}

def send_proactive_alert(trade, reasons):
    alert_id = uuid.uuid4().hex[:10]
    pending = load_pending()
    pending[alert_id] = {"trade_id":trade["id"],"input":trade["input"],"confidence":trade["confidence"],"reasons":reasons,"created_at":datetime.utcnow().isoformat()+"Z"}
    save_pending(pending)
    tg_send_all(f"🚨 *ВЫСОКАЯ УВЕРЕННОСТЬ* ({int(trade['confidence']*100)}%)\n{_signal_label(trade['input'].get('signal'))} *XAUUSD* по `{trade['input'].get('price')}`\n_Рекомендую открыть сделку._", reply_markup=build_alert_keyboard(alert_id))

def process_signal(signal, price, rsi, trend, atr, outcome=None, send_telegram=True, source="webhook"):
    with _lock:
        weights = load_weights(); rules = load_rules()
        raw = {"signal":signal,"price":price,"rsi":rsi,"trend":trend,"atr":atr}
        features = normalize_features(signal,price,rsi,trend,atr)
        base_conf = compute_confidence(features,weights)
        conf,reasons,threshold = apply_rules(base_conf,raw,rules)
        decision = "execute" if conf>=threshold else "skip"
        trade = {"id":uuid.uuid4().hex[:12],"received_at":datetime.utcnow().isoformat()+"Z","source":source,"input":raw,"features":features,"weights_used":weights,"base_confidence":base_conf,"confidence":conf,"threshold":threshold,"reasons":reasons,"decision":decision,"outcome":outcome}
        trades = load_trades(); trades.append(trade); save_trades(trades)
        ga_result = None
        if outcome is not None:
            new_w,fit = maybe_run_ga(trades,weights)
            if new_w!=weights: ga_result = {"updated":True,"fitness":fit}
    if send_telegram:
        tg_send_all(format_signal_ru(trade,reasons), reply_markup=build_outcome_keyboard(trade["id"]))
        if conf>=HIGH_CONF and decision=="execute": send_proactive_alert(trade,reasons)
    return trade, ga_result

# ────────────────────────────────────────────────────────────────────────────
# Отчёт и планировщики
# ────────────────────────────────────────────────────────────────────────────

def build_daily_report():
    with _lock: trades = load_trades()
    rules = load_rules(); kb = load_knowledge()
    labeled = [t for t in trades if t.get("outcome") in ("win","loss")]
    wins_all = sum(1 for t in labeled if t["outcome"]=="win")
    avg_conf = (sum(t["confidence"] for t in trades)/len(trades)) if trades else 0
    bias_map = {"bullish":"📈 бычье","bearish":"📉 медвежье","neutral":"➖ нейтральное"}
    return f"🌅 *Отчёт XAUUSD*\nСделок: {len(trades)} | Размечено: {len(labeled)}\nВинрейт: {(int(wins_all/len(labeled)*100)) if labeled else '—'}%\nУверенность: {round(avg_conf,3)}\n{bias_map.get(rules.get('market_bias'),'—')} | {rules.get('preferred_signal')}\n📚 {kb.get('summary','—')}"

def scheduler_hourly_insights():
    time.sleep(60)
    while True:
        try:
            with _lock: trades = load_trades()
            evolve_insights(trades)
        except: pass
        time.sleep(3600)

def scheduler_daily_report(hour_utc=8):
    while True:
        now = datetime.utcnow()
        target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
        if target <= now: target += timedelta(days=1)
        time.sleep((target-now).total_seconds())
        try: tg_send_all(build_daily_report())
        except: pass

def scheduler_self_pinger(interval=300):
    url = f"http://127.0.0.1:{PORT}/ping"
    time.sleep(15)
    while True:
        try: requests.get(url,timeout=8)
        except: pass
        time.sleep(interval)

# ────────────────────────────────────────────────────────────────────────────
# Telegram-команды + МЕНЮ
# ────────────────────────────────────────────────────────────────────────────

def welcome_text():
    return ("👋 *XAUUSD ИИ-бот*\n\n*/buy ЦЕНА RSI ТРЕНД ATR* — BUY\n*/sell ЦЕНА RSI ТРЕНД ATR* — SELL\n*/price* — цена\n*/status* — статус\n*/menu* — меню\n*/users* — пользователи\n*/ask* — спросить AI")

def _parse_trade_args(args):
    if len(args)!=4: raise ValueError("Формат: ЦЕНА RSI ТРЕНД ATR")
    try: price,rsi,atr = float(args[0]),float(args[1]),float(args[3])
    except: raise ValueError("Числа!")
    trend = args[2].upper()
    if trend not in ("UP","DOWN","FLAT"): raise ValueError("ТРЕНД: UP/DOWN/FLAT")
    return price,rsi,trend,atr

def format_status_ru():
    with _lock: trades = load_trades()
    weights = load_weights(); rules = load_rules()
    labeled = [t for t in trades if t.get("outcome") in ("win","loss")]
    wins = sum(1 for t in labeled if t["outcome"]=="win")
    wr = (wins/len(labeled)) if labeled else None
    bias_map = {"bullish":"📈 бычье","bearish":"📉 медвежье","neutral":"➖ нейтральное"}
    return f"📊 *Статус*\nСделок: {len(trades)} | Винрейт: {int(wr*100) if wr else '—'}%\n{bias_map.get(rules.get('market_bias'),'—')} | Порог: {rules.get('confidence_threshold')}"

def format_auto_signal(signal, price, sl, tp, confidence, insights_count):
    risk_pct = round(abs(price - sl) / price * 100, 2)
    rr = round(abs(tp - price) / abs(price - sl), 1) if abs(price - sl) > 0 else 0
    emoji = "🚨" if confidence >= 0.85 else "📊"
    return f"{emoji} *{signal} XAUUSD @ {price}*\n   SL: {sl} ({risk_pct}% риска)\n   TP: {tp} (1:{rr} R/R)\n   Conf: {int(confidence*100)}% ({insights_count} инсайтов)"

def auto_signal_checker():
    time.sleep(120)
    while True:
        time.sleep(300)
        try:
            price_data = get_current_xau_price()
            if not price_data or not price_data.get("current"): continue
            price = price_data["current"]; rules = load_rules(); insights = load_insights()
            rsi_val, atr_val, trend = 50, 15, "UP" if price_data.get("change",0) > 0 else "DOWN"
            signal = "BUY" if trend == "UP" else "SELL"
            with _lock: weights = load_weights()
            features = normalize_features(signal, price, rsi_val, trend, atr_val)
            conf = compute_confidence(features, weights)
            raw = {"signal":signal,"price":price,"rsi":rsi_val,"trend":trend,"atr":atr_val}
            conf, reasons, threshold = apply_rules(conf, raw, rules)
            if conf >= threshold:
                sl = round(price - atr_val*0.8,2) if signal=="BUY" else round(price + atr_val*0.8,2)
                tp = round(price + atr_val*2.5,2) if signal=="BUY" else round(price - atr_val*2.5,2)
                tg_send_all(format_auto_signal(signal, price, sl, tp, conf, len(insights)))
                logger.info(f"[AUTO-SIGNAL] {signal} @ {price} | Conf: {conf}")
        except: pass

def handle_command(message):
    text = (message.get("text") or "").strip()
    chat_id = message.get("chat",{}).get("id")
    if text and not text.startswith("/"):
        if any(w in text.lower() for w in ["цена","price","золото","сколько"]):
            tg_send(format_price_info(), chat_id=chat_id); return True
        answer, err = deepseek_ask(text)
        tg_send(f"⚠️ {err}" if err else f"🧠 {answer}", chat_id=chat_id)
        return True
    parts = text.split()
    cmd = parts[0].split("@",1)[0].lower()
    args = parts[1:]
    if cmd in ("/","/menu"):
        keyboard = {"inline_keyboard":[[{"text":"🟢 BUY","callback_data":"menu_buy"},{"text":"🔴 SELL","callback_data":"menu_sell"}],[{"text":"💰 Цена","callback_data":"menu_price"},{"text":"📊 Статус","callback_data":"menu_status"}],[{"text":"🧠 AI","callback_data":"menu_ask"},{"text":"❓ Помощь","callback_data":"menu_help"}]]}
        tg_send("📋 *Меню*", chat_id=chat_id, reply_markup=keyboard); return True
    if cmd in ("/start","/help"): tg_send(welcome_text(), chat_id=chat_id); return True
    if cmd in ("/buy","/sell"):
        try: price,rsi,trend,atr = _parse_trade_args(args)
        except ValueError as e: tg_send(f"⚠️ {e}", chat_id=chat_id); return True
        process_signal("BUY" if cmd=="/buy" else "SELL",price,rsi,trend,atr,source="telegram"); return True
    if cmd == "/price": tg_send(format_price_info(), chat_id=chat_id); return True
    if cmd == "/users": tg_send(f"👥 Пользователи:\n"+"\n".join(f"• `{c}`" for c in CHAT_IDS), chat_id=chat_id); return True
    if cmd == "/status": tg_send(format_status_ru(), chat_id=chat_id); return True
    if cmd in ("/sim_buy","/sim_sell"):
        try: price,rsi,trend,atr = _parse_trade_args(args)
        except ValueError as e: tg_send(f"⚠️ {e}", chat_id=chat_id); return True
        sl = round(price-atr*0.8,2) if cmd=="/sim_buy" else round(price+atr*0.8,2)
        tp = round(price+atr*2.5,2) if cmd=="/sim_buy" else round(price-atr*2.5,2)
        trade,sim = sim_trade("BUY" if cmd=="/sim_buy" else "SELL",price,sl,tp)
        tg_send(f"🧪 Симуляция: {'✅' if trade['outcome']=='win' else '❌'} ${trade['pnl']:.2f} | Баланс: ${sim['balance']:.2f}", chat_id=chat_id); return True
    if cmd == "/portfolio": tg_send(format_portfolio(), chat_id=chat_id); return True
    if cmd == "/report": tg_send(build_daily_report(), chat_id=chat_id); return True
    if cmd == "/ask":
        question = " ".join(args).strip()
        if not question: tg_send("Использование: `/ask вопрос`", chat_id=chat_id); return True
        answer,err = deepseek_ask(question)
        tg_send(f"⚠️ {err}" if err else f"🧠 {answer}", chat_id=chat_id); return True
    if cmd == "/knowledge":
        kb = load_knowledge()
        tail = "\n".join(f"  • {s['s'][:160]}" for s in kb.get("snippets",[])[:5]) or "  • —"
        tg_send(f"📚 *База знаний*\n{kb.get('summary','—')}\n{tail}", chat_id=chat_id); return True
    tg_send(f"❓ Неизвестная команда. /help", chat_id=chat_id); return True

def handle_callback(cb):
    data = cb.get("data",""); cb_id = cb.get("id"); msg = cb.get("message",{}); chat_id = msg.get("chat",{}).get("id")
    if ":" not in data:
        if data == "menu_buy": tg_send("/buy ЦЕНА RSI ТРЕНД ATR", chat_id=chat_id); return
        if data == "menu_sell": tg_send("/sell ЦЕНА RSI ТРЕНД ATR", chat_id=chat_id); return
        if data == "menu_price": tg_send(format_price_info(), chat_id=chat_id); return
        if data == "menu_status": tg_send(format_status_ru(), chat_id=chat_id); return
        if data == "menu_report": tg_send(build_daily_report(), chat_id=chat_id); return
        if data == "menu_help": tg_send(welcome_text(), chat_id=chat_id); return
        if data == "menu_ask": tg_send("/ask вопрос", chat_id=chat_id); return
        return
    action,payload = data.split(":",1)
    if action in ("win","loss"):
        with _lock:
            trades = load_trades()
            target = next((t for t in trades if t.get("id")==payload),None)
            if target: target["outcome"] = action; target["labeled_at"] = datetime.utcnow().isoformat()+"Z"; save_trades(trades); maybe_run_ga(trades, load_weights())
        tg_answer_callback(cb_id, "✅" if action=="win" else "❌")
    if action.startswith("alert"): tg_answer_callback(cb_id, "Принято")

# ────────────────────────────────────────────────────────────────────────────
# Flask
# ────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = SESSION_SECRET

@app.route("/")
def home(): return app.send_static_file('index.html')

@app.route("/ping")
def ping(): return jsonify({"status":"alive"})

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    if any(data.get(k) is None for k in ["signal","price","rsi","trend","atr"]): return jsonify({"error":"Missing"}),400
    trade,ga = process_signal(data["signal"],data["price"],data["rsi"],data["trend"],data["atr"],data.get("outcome"))
    return jsonify({"status":"ok","confidence":trade["confidence"],"decision":trade["decision"]})

@app.route("/stats")
def stats():
    with _lock: trades = load_trades()
    labeled = [t for t in trades if t.get("outcome") in ("win","loss")]
    wins = sum(1 for t in labeled if t["outcome"]=="win")
    return jsonify({"total_trades":len(trades),"labeled":len(labeled),"winrate":round(wins/max(len(labeled),1),2) if labeled else 0,"avg_conf":round(sum(t.get("confidence",0) for t in trades)/max(len(trades),1),2),"weights":load_weights()})

@app.route("/learn")
def learn(): return jsonify({"rules":load_rules()})

@app.route("/knowledge")
def knowledge(): return jsonify(load_knowledge())

@app.route("/report")
def report_endpoint(): tg_send_all(build_daily_report()); return jsonify({"ok":True})

@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True) or {}
    try:
        if update.get("message"): handle_command(update["message"])
        elif update.get("callback_query"): handle_callback(update["callback_query"])
    except: pass
    return jsonify({"ok":True})

def start_background_threads():
    for t in [hourly_self_tune, scheduler_hourly_insights, scheduler_daily_report, scheduler_self_pinger, auto_signal_checker]:
        threading.Thread(target=t, daemon=True).start()

start_background_threads()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
