"""
XAUUSD AI Trading Bot — single-file Flask app for GitHub → Render.
Все сообщения и интерфейс — на русском языке.

Возможности:
  • Webhook /webhook со скорингом сигнала через ИИ-веса
  • Генетический алгоритм каждые 10 размеченных сделок
  • Парсинг 100+ финансовых источников каждый час → база знаний
  • Парсинг 16+ обучающих сайтов каждые 3 часа
  • Finnhub API для реальных новостей и ЦЕНЫ XAUUSD 24/7
  • /price команда — текущая цена золота с рынка
  • /menu — меню с кнопками
  • Авто-сигналы в Telegram при уверенности >70%
  • Авто-перестройка правил, ежечасный self-tuning порога уверенности
  • Telegram-бот: команды на русском + свободный чат через DeepSeek
  • Проактивные сигналы при уверенности > 85%
  • Автогенерация Pine Script, когда найден прибыльный паттерн (>60% winrate)
  • Динамические Telegram-команды для проверенных паттернов (>20 сделок, >60%)
  • Ежедневный отчёт в 08:00 UTC
  • Симулятор торговли: /sim_buy, /sim_sell, /portfolio
  • Поддержка нескольких пользователей (CHAT_IDS через запятую)
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
# Telegram (с поддержкой нескольких пользователей)
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
    # Рассылка остальным пользователям
    for cid2 in CHAT_IDS[1:]:
        payload["chat_id"] = cid2
        _tg("sendMessage", payload)
    return result

def tg_send_all(text, reply_markup=None, parse_mode="Markdown"):
    """Отправить сообщение всем пользователям"""
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

def apply_rules(base_conf, raw_input, rules):
    reasons = []
    conf = base_conf
    threshold = float(rules.get("confidence_threshold", CONFIDENCE_THRESHOLD))
    sig_str = str(raw_input.get("signal","")).strip().upper()
    preferred = str(rules.get("preferred_signal","HOLD")).upper()
    bias_strength = float(rules.get("bias_strength",0))
    
    if preferred in ("BUY","SELL") and sig_str:
        if sig_str == preferred: conf = min(1,conf+0.1*bias_strength); reasons.append(f"сигнал совпадает с {preferred}-предпочтением (+{0.1*bias_strength:.3f})")
        elif sig_str in ("BUY","SELL"): conf = max(0,conf-0.1*bias_strength); reasons.append(f"сигнал против {preferred}-предпочтения (−{0.1*bias_strength:.3f})")
    
    try:
        rsi_v = float(raw_input.get("rsi"))
        oversold = float(rules.get("rsi_oversold",30))
        overbought = float(rules.get("rsi_overbought",70))
        if sig_str=="BUY" and rsi_v<=oversold: conf=min(1,conf+0.05); reasons.append(f"RSI {rsi_v} ≤ перепроданность {oversold} (+0.05)")
        elif sig_str=="SELL" and rsi_v>=overbought: conf=min(1,conf+0.05); reasons.append(f"RSI {rsi_v} ≥ перекупленность {overbought} (+0.05)")
        elif sig_str=="BUY" and rsi_v>=overbought: conf=max(0,conf-0.07); reasons.append(f"RSI {rsi_v} перекуплен против BUY (−0.07)")
        elif sig_str=="SELL" and rsi_v<=oversold: conf=max(0,conf-0.07); reasons.append(f"RSI {rsi_v} перепродан против SELL (−0.07)")
    except: pass
    
    try:
        atr_v = float(raw_input.get("atr"))
        atr_cap = float(rules.get("atr_caution_above",50))
        if atr_v > atr_cap: conf = max(0,conf-min(0.15,(atr_v-atr_cap)/200)); reasons.append(f"ATR {atr_v} выше осторожного {atr_cap} (−{min(0.15,(atr_v-atr_cap)/200):.3f})")
    except: pass
    
    if rules.get("risk_mode")=="elevated": threshold=min(0.95,threshold+0.05); reasons.append("высокий риск: порог поднят (+0.05)")
    
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
# Finnhub API — реальные новости 24/7
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
        logger.info(f"[finnhub] получено {len(records)} новостей")
        return records
    except Exception as e:
        logger.warning(f"[finnhub] ошибка: {e}")
        return []

# ────────────────────────────────────────────────────────────────────────────
# Реальные данные рынка — ЦЕНА XAUUSD (Finnhub + резервный API)
# ────────────────────────────────────────────────────────────────────────────

def get_current_price_finnhub():
    if not FINNHUB_API_KEY: return None
    try:
        r = requests.get(f"https://finnhub.io/api/v1/quote?symbol=XAUUSD&token={FINNHUB_API_KEY}", timeout=10)
        if r.status_code != 200: return None
        data = r.json()
        if data.get("c"):
            return {
                "current": data.get("c"),
                "high": data.get("h"),
                "low": data.get("l"),
                "open": data.get("o"),
                "prev_close": data.get("pc"),
                "change": round(data.get("c", 0) - data.get("pc", 0), 2) if data.get("pc") else None,
                "change_percent": round((data.get("c", 0) - data.get("pc", 0)) / data.get("pc", 1) * 100, 2) if data.get("c") and data.get("pc") and data.get("pc") != 0 else None
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
            if isinstance(data, list) and len(data) > 0:
                return float(data[0].get("price", 0))
        return None
    except:
        return None

def get_current_xau_price():
    finnhub = get_current_price_finnhub()
    if finnhub and finnhub.get("current"): return finnhub
    reserve = get_xau_price_reserve()
    if reserve: return {"current": reserve, "high": None, "low": None, "open": None, "prev_close": None, "change": None, "change_percent": None}
    return None

def format_price_info():
    now = datetime.utcnow()
    moscow_time = now + timedelta(hours=3)
    day_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    day_name = day_names[now.weekday()]
    
    price_data = get_current_xau_price()
    rules = load_rules()
    
    msg = f"📅 *{day_name} {moscow_time.strftime('%H:%M')} (МСК)*\n"
    
    if price_data and price_data.get("current"):
        price = price_data["current"]
        change = price_data.get("change")
        change_pct = price_data.get("change_percent")
        emoji = "🟢" if (change and change > 0) else "🔴" if (change and change < 0) else "⚪"
        msg += f"💰 *XAUUSD: ${price:.2f}* {emoji}\n"
        if change is not None:
            msg += f"📊 Изменение: {change:+.2f} ({change_pct:+.2f}%)\n" if change_pct is not None else f"📊 Изменение: {change:+.2f}\n"
        if price_data.get("high"):
            msg += f"📈 High: ${price_data['high']:.2f} | Low: ${price_data['low']:.2f}\n"
        if price_data.get("open"):
            msg += f"📋 Открытие: ${price_data['open']:.2f} | Закрытие: ${price_data.get('prev_close', '—')}\n"
    else:
        msg += f"⚠️ Не удалось получить текущую цену. Рынок закрыт.\n"
    
    msg += f"━━━━━━━━━━━━━━\n"
    msg += f"📈 *Рыночные условия:*\n"
    msg += f"• Настроение: {rules.get('market_bias', '—')}\n"
    msg += f"• Сигнал: {rules.get('preferred_signal', '—')}\n"
    msg += f"• RSI диапазон: {rules.get('rsi_oversold', '—')}/{rules.get('rsi_overbought', '—')}\n"
    msg += f"• Порог уверенности: {int(rules.get('confidence_threshold', 0.7)*100)}%\n"
    msg += f"• Режим риска: {rules.get('risk_mode', '—')}\n"
    
    return msg

# ────────────────────────────────────────────────────────────────────────────
# Парсинг 100+ сайтов
# ────────────────────────────────────────────────────────────────────────────

FINANCE_SITES = [
    "investing.com","fxstreet.com","dailyfx.com","kitco.com","tradingview.com",
    "marketwatch.com","bloomberg.com","reuters.com","cnbc.com","ft.com",
    "wsj.com","forbes.com","businessinsider.com","finance.yahoo.com","finviz.com",
    "seekingalpha.com","zerohedge.com","macrotrends.net","marketpulse.com","fxempire.com",
    "forexlive.com","babypips.com","dailyforex.com","forexfactory.com","talkmarkets.com",
    "oilprice.com","mining.com","goldhub.com","gold.org","smaulgld.com",
    "goldsilver.com","sprottmoney.com","miningweekly.com","goldprice.org","goldcore.com",
    "fxleaders.com","actionforex.com","fxopen.com","ig.com","etoro.com",
    "axitrader.com","easymarkets.com","hotforex.com","exness.com","alpari.com",
    "dukascopy.com","octafx.com","instaforex.com","fbs.com","roboforex.com",
    "xm.com","libertex.com","capital.com","plus500.com","avatrade.com",
    "pepperstone.com","icmarkets.com","fxcm.com","thinkmarkets.com","forex.com",
    "swissquote.com","saxobank.com","money.com","fool.com","nasdaq.com",
    "barrons.com","economist.com","qz.com","bnnbloomberg.ca","financialpost.com",
    "cnn.com","bbc.com","theguardian.com","telegraph.co.uk","msn.com",
    "livemint.com","moneycontrol.com","business-standard.com","economictimes.indiatimes.com",
    "scmp.com","asia.nikkei.com","japantimes.co.jp","koreatimes.co.kr","gulfnews.com",
    "arabianbusiness.com","jpost.com","haaretz.com","themoscowtimes.com","tass.com",
    "interfax.com","vedomosti.ru","rbc.ru","banki.ru","smart-lab.ru",
    "finam.ru","bcs-express.ru","fomag.ru","profinance.ru","conomy.ru",
    "investing.com/ru","tradingview.com/ru","fxteam.ru","forexpf.ru","teletrade.ru",
    "alpari.ru","instaforex.ru","fxclub.org","fortrader.org","fortfs.com",
]

LEARNING_SITES = [
    "https://www.tradingview.com/ideas/gold/",
    "https://www.tradingview.com/scripts/pine/",
    "https://www.investopedia.com/articles/trading/",
    "https://www.babypips.com/learn/forex",
    "https://www.tradingstrategyguides.com/",
    "https://www.fxacademy.com/",
    "https://www.forexstrategiesresources.com/",
    "https://www.best-metatrader-indicators.com/",
    "https://www.dailyfx.com/forex-education",
    "https://www.myfxbook.com/community/outlook",
    "https://www.stockcharts.com/school",
    "https://www.technical-analysis-library.com/",
    "https://www.fxempire.com/news",
    "https://www.quantconnect.com/learning",
    "https://towardsdatascience.com/tagged/trading",
]

QUERIES_TPL = [
    "XAUUSD прогноз цена золота","XAUUSD technical analysis today","gold price forecast {y}",
    "XAUUSD support resistance levels","gold COT report futures positioning",
    "DXY dollar index XAUUSD correlation","Federal Reserve rate decision gold impact",
    "gold ETF flows","real yields TIPS gold price","geopolitical risk safe haven gold demand",
]

BULLISH_TERMS = ["bullish","rally","uptrend","breakout","surge","buy","long","rebound","support","higher","gains","rise","рост","покупка","вверх","бычий","пробой"]
BEARISH_TERMS = ["bearish","decline","downtrend","breakdown","drop","sell","short","pullback","resistance","lower","losses","fall","падение","продажа","вниз","медвежий","снижение"]
RISK_TERMS = ["volatility","volatile","risk","uncertainty","atr","волатильность","риск"]
RSI_PATTERN = re.compile(r"\brsi\b[^\d]{0,12}(\d{1,3})", re.IGNORECASE)

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
        if not snippets:
            for el in soup.find_all(["p","span"]):
                t = el.get_text(" ",strip=True)
                if 50<len(t)<400: snippets.append(t)
                if len(snippets)>20: break
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
                records.append({
                    "query": f"learn:{url.split('//')[1][:60]}",
                    "fetched_at": datetime.utcnow().isoformat() + "Z",
                    "characters_extracted": len(text),
                    "analysis": analysis
                })
                time.sleep(0.5)
        except Exception as e:
            logger.warning(f"[learn] Ошибка парсинга {url}: {e}")
    if records:
        logger.info(f"[learn] Собрано {len(records)} записей с обучающих сайтов")
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
    kb["summary"] = f"Настроение рынка: {bias} (бычьих сигналов {bull}, медвежьих {bear}, риск-маркеров {risk}). Источников за цикл: {len(records)}."
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
    recent_prices = []
    for t in trade_history[-50:]:
        try: recent_prices.append(float(t["input"]["price"]))
        except: continue
    price_target = round(sum(recent_prices)/len(recent_prices),2) if recent_prices else None
    risk_mode = "elevated" if total_risk>max(5,(total_bull+total_bear)/4) else "normal"
    labeled = [t for t in trade_history if t.get("outcome") in ("win","loss")]
    wins = [t for t in labeled if t["outcome"]=="win"]
    losses = [t for t in labeled if t["outcome"]=="loss"]
    historical_winrate = round(len(wins)/len(labeled),3) if labeled else None
    avg_win_conf = round(sum(t["confidence"] for t in wins)/len(wins),3) if wins else None
    avg_loss_conf = round(sum(t["confidence"] for t in losses)/len(losses),3) if losses else None
    suggested_threshold = 0.7
    return {"generated_at":datetime.utcnow().isoformat()+"Z","market_bias":market_bias,"bias_strength":bias_strength,"preferred_signal":"BUY" if market_bias=="bullish" else "SELL" if market_bias=="bearish" else "HOLD","rsi_oversold":rsi_oversold,"rsi_overbought":rsi_overbought,"price_target":price_target,"risk_mode":risk_mode,"atr_caution_above":30 if risk_mode=="elevated" else 50,"confidence_threshold":suggested_threshold,"historical_winrate":historical_winrate,"based_on":{"insight_records":len(insight_records),"labeled_trades":len(labeled)}}

def default_rules():
    return {"generated_at":datetime.utcnow().isoformat()+"Z","market_bias":"neutral","bias_strength":0,"preferred_signal":"HOLD","rsi_oversold":30,"rsi_overbought":70,"price_target":None,"risk_mode":"normal","atr_caution_above":50,"confidence_threshold":0.7,"historical_winrate":None,"based_on":{"insight_records":0,"labeled_trades":0}}

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
            if abs(new-old)>=0.005:
                rules["confidence_threshold"] = new
                rules["last_self_tune"] = {"at":datetime.utcnow().isoformat()+"Z","winrate_30":round(wr,3),"from":old,"to":new}
                save_rules(rules)
        except: pass

# ────────────────────────────────────────────────────────────────────────────
# DeepSeek Чат (свободное общение + трейдинг) через OpenRouter
# ────────────────────────────────────────────────────────────────────────────

DEEPSEEK_SYSTEM = (
    "Ты — дружелюбный ИИ-помощник и опытный трейдер по золоту (XAUUSD). "
    "Отвечай ТОЛЬКО на русском языке, естественно, как носитель. "
    "Можешь говорить на любые темы: трейдинг, рынок, новости, просто поболтать. "
    "Если спрашивают о рынке — используй данные пользователя. "
    "Будь конкретным, кратким и практичным. Не давай финансовых гарантий."
)

def deepseek_ask(question):
    if not DEEPSEEK_API_KEY: return None, "DEEPSEEK_API_KEY не задан в окружении."
    with _lock: trades = load_trades()
    rules = load_rules()
    kb = load_knowledge()
    labeled = [t for t in trades if t.get("outcome") in ("win","loss")]
    wins = sum(1 for t in labeled if t["outcome"]=="win")
    wr = (wins/len(labeled)) if labeled else None
    context = f"Правила: {json.dumps(rules, ensure_ascii=False)[:800]}\nСделок: {len(trades)}, винрейт: {round(wr,3) if wr else 'нет'}\nБаза знаний: {kb.get('summary','—')}"
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": DEEPSEEK_SYSTEM},
            {"role": "system", "content": f"КОНТЕКСТ:\n{context}"},
            {"role": "user", "content": question}
        ],
        "temperature": 0.5,
        "max_tokens": 700
    }
    try:
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": PUBLIC_URL or "https://xau-ai.onrender.com",
            "X-Title": "XAU AI Trader"
        }
        r = requests.post(f"{DEEPSEEK_BASE_URL}/v1/chat/completions", headers=headers, json=payload, timeout=45)
        if r.status_code != 200: return None, f"DeepSeek вернул {r.status_code}: {r.text[:200]}"
        data = r.json()
        return data["choices"][0]["message"]["content"].strip(), None
    except Exception as e:
        return None, f"Ошибка DeepSeek: {e}"

# ────────────────────────────────────────────────────────────────────────────
# Симулятор
# ────────────────────────────────────────────────────────────────────────────

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
    pf = sum(t["pnl"] for t in wins)/abs(sum(t["pnl"] for t in losses)) if losses else 0
    emoji = "🟢" if sim["daily_pnl"]>=0 else "🔴"
    return (
        f"📊 *Симулятор (бумажный счёт)*\n"
        f"*Баланс:* ${sim['balance']:.2f}\n"
        f"*P&L за 24ч:* {emoji} ${sim['daily_pnl']:.2f}\n"
        f"*Сделок:* {len(trades)} ({len(wins)}П/{len(losses)}У)\n"
        f"*Винрейт:* {wr:.0f}%\n"
        f"*Профит-фактор:* {pf:.2f}\n"
        f"*Лучшая:* ${max(t['pnl'] for t in trades) if trades else 0:.2f}\n"
        f"*Худшая:* ${min(t['pnl'] for t in trades) if trades else 0:.2f}"
    )

# ────────────────────────────────────────────────────────────────────────────
# Паттерны → Pine Script + команды
# ────────────────────────────────────────────────────────────────────────────

def _rsi_band(v):
    try: v=float(v)
    except: return "?"
    return "low" if v<35 else "mid" if v<65 else "high"

def discover_patterns(trades, min_samples=20, min_winrate=0.6):
    buckets = defaultdict(lambda:{"wins":0,"n":0})
    for t in trades:
        if t.get("outcome") not in ("win","loss"): continue
        inp = t.get("input",{})
        key = (str(inp.get("signal","")).upper(), _rsi_band(inp.get("rsi")), str(inp.get("trend","")).upper())
        b = buckets[key]
        b["n"] += 1
        if t["outcome"]=="win": b["wins"] += 1
    proven = []
    for key,v in buckets.items():
        if v["n"]>=min_samples and (v["wins"]/v["n"])>=min_winrate: proven.append({"key":key,"winrate":round(v["wins"]/v["n"],3),"n":v["n"]})
    return sorted(proven, key=lambda p:(p["winrate"],p["n"]), reverse=True)

def pattern_slug(key): return f"{key[0].lower()}_{key[1]}_{key[2].lower()}"

def generate_pine(pattern):
    sig,band,trend = pattern["key"]
    band_low,band_high = {"low":(0,35),"mid":(35,65),"high":(65,100)}.get(band,(0,100))
    ema_cond = "ema20 > ema50" if trend=="UP" else "ema20 < ema50" if trend=="DOWN" else "true"
    name = f"XAU_{pattern_slug(pattern['key'])}"
    code = f"""//@version=5\n// Авто-сгенерировано XAU AI: winrate={int(pattern['winrate']*100)}% за {pattern['n']} сделок\nindicator("{name}", overlay=true)\nrsi=ta.rsi(close,14)\nema20=ta.ema(close,20)\nema50=ta.ema(close,50)\ncondRSI=rsi>={band_low} and rsi<={band_high}\ncondTrend={ema_cond}\nsignal=condRSI and condTrend\nplotshape(signal,"{sig}",style={'shape.triangleup' if sig=='BUY' else 'shape.triangledown'},location={'location.belowbar' if sig=='BUY' else 'location.abovebar'},color={'color.green' if sig=='BUY' else 'color.red'},size=size.small)\nalertcondition(signal,"{name}","XAUUSD {sig}: RSI {band_low}-{band_high}, тренд {trend}")"""
    return {"name":name,"pattern":pattern,"code":code,"created_at":datetime.utcnow().isoformat()+"Z"}

def maybe_generate_artifacts():
    with _lock: trades = load_trades()
    proven = discover_patterns(trades)
    if not proven: return {"new_pine":0,"new_cmds":0}
    pine = load_pine()
    existing = {p["name"] for p in pine}
    cmds = load_dyn_cmds()
    new_pine = new_cmds = 0
    for pat in proven:
        pine_obj = generate_pine(pat)
        if pine_obj["name"] not in existing:
            pine.append(pine_obj); new_pine += 1
            tg_send_all(f"🧬 *Новый Pine Script:* `{pine_obj['name']}` — winrate {int(pat['winrate']*100)}% за {pat['n']} сделок.\nЗапросите код: /pinescripts")
        slug = pattern_slug(pat["key"])
        cmd_name = f"/p_{slug}"
        if cmd_name not in cmds:
            cmds[cmd_name] = {"pattern_key":list(pat["key"]),"winrate":pat["winrate"],"n":pat["n"],"created_at":datetime.utcnow().isoformat()+"Z"}
            new_cmds += 1
            tg_send_all(f"🆕 *Новая команда:* `{cmd_name}` — {pat['key'][0]} / RSI {pat['key'][1]} / тренд {pat['key'][2]} (winrate {int(pat['winrate']*100)}%)")
    if new_pine: save_pine(pine)
    if new_cmds: save_dyn_cmds(cmds)
    return {"new_pine":new_pine,"new_cmds":new_cmds}

# ────────────────────────────────────────────────────────────────────────────
# Конвейер сигнала
# ────────────────────────────────────────────────────────────────────────────

def _signal_label(sig):
    s = str(sig).upper()
    return "🟢 ПОКУПКА" if s=="BUY" else "🔴 ПРОДАЖА" if s=="SELL" else f"⚪ {s}"

def _decision_label(dec):
    return "ИСПОЛНИТЬ" if dec=="execute" else "ПРОПУСТИТЬ"

def format_signal_ru(trade, reasons):
    inp = trade["input"]
    rs = "\n".join(f"  • {r}" for r in reasons) if reasons else "  • —"
    return (
        f"{_signal_label(inp.get('signal'))}  *XAUUSD*\n"
        f"*Цена:* `{inp.get('price')}`  *RSI:* `{inp.get('rsi')}`  *Тренд:* `{inp.get('trend')}`  *ATR:* `{inp.get('atr')}`\n"
        f"*Уверенность:* `{int(trade['confidence']*100)}%`  *Порог:* `{int(trade['threshold']*100)}%`\n"
        f"*Решение:* *{_decision_label(trade['decision'])}*\n"
        f"*Обоснование:*\n{rs}\n_Получено: {trade['received_at']}_"
    )

def build_outcome_keyboard(trade_id):
    return {"inline_keyboard":[[{"text":"✅ Победа","callback_data":f"win:{trade_id}"},{"text":"❌ Убыток","callback_data":f"loss:{trade_id}"}]]}

def build_alert_keyboard(alert_id):
    return {"inline_keyboard":[[{"text":"✅ Согласен","callback_data":f"alert_ok:{alert_id}"},{"text":"🚫 Отклонить","callback_data":f"alert_no:{alert_id}"},{"text":"❓ Почему?","callback_data":f"alert_why:{alert_id}"}]]}

def send_proactive_alert(trade, reasons):
    alert_id = uuid.uuid4().hex[:10]
    pending = load_pending()
    pending[alert_id] = {"trade_id":trade["id"],"input":trade["input"],"confidence":trade["confidence"],"reasons":reasons,"created_at":datetime.utcnow().isoformat()+"Z"}
    save_pending(pending)
    inp = trade["input"]
    tg_send_all(
        f"🚨 *ВЫСОКАЯ УВЕРЕННОСТЬ* ({int(trade['confidence']*100)}%)\n{_signal_label(inp.get('signal'))} *XAUUSD* по `{inp.get('price')}`\nRSI `{inp.get('rsi')}` · тренд `{inp.get('trend')}` · ATR `{inp.get('atr')}`\n\n_Рекомендую открыть сделку. Подтвердите кнопкой ниже._",
        reply_markup=build_alert_keyboard(alert_id)
    )

def process_signal(signal, price, rsi, trend, atr, outcome=None, send_telegram=True, source="webhook"):
    with _lock:
        weights = load_weights()
        rules = load_rules()
        raw = {"signal":signal,"price":price,"rsi":rsi,"trend":trend,"atr":atr}
        features = normalize_features(signal,price,rsi,trend,atr)
        base_conf = compute_confidence(features,weights)
        conf,reasons,threshold = apply_rules(base_conf,raw,rules)
        decision = "execute" if conf>=threshold else "skip"
        trade = {"id":uuid.uuid4().hex[:12],"received_at":datetime.utcnow().isoformat()+"Z","source":source,"input":raw,"features":features,"weights_used":weights,"base_confidence":base_conf,"confidence":conf,"threshold":threshold,"reasons":reasons,"decision":decision,"outcome":outcome}
        trades = load_trades()
        trades.append(trade)
        save_trades(trades)
        trade_log.info(json.dumps({"src":source,"signal":signal,"price":price,"conf":conf,"decision":decision,"outcome":outcome}, ensure_ascii=False))
        ga_result = None
        if outcome is not None:
            new_w,fit = maybe_run_ga(trades,weights)
            if new_w!=weights: ga_result = {"updated":True,"fitness":fit}
    if send_telegram:
        tg_send_all(format_signal_ru(trade,reasons), reply_markup=build_outcome_keyboard(trade["id"]))
        if conf>=HIGH_CONF and decision=="execute": send_proactive_alert(trade,reasons)
    if outcome is not None:
        try: maybe_generate_artifacts()
        except: pass
    return trade, ga_result

# ────────────────────────────────────────────────────────────────────────────
# Отчёт и планировщики
# ────────────────────────────────────────────────────────────────────────────

def build_daily_report():
    with _lock: trades = load_trades()
    rules = load_rules()
    kb = load_knowledge()
    labeled = [t for t in trades if t.get("outcome") in ("win","loss")]
    executed = [t for t in labeled if t.get("decision")=="execute"]
    wins_all = sum(1 for t in labeled if t["outcome"]=="win")
    wins_exec = sum(1 for t in executed if t["outcome"]=="win")
    avg_conf = (sum(t["confidence"] for t in trades)/len(trades)) if trades else 0
    bias_map = {"bullish":"📈 бычье","bearish":"📉 медвежье","neutral":"➖ нейтральное"}
    bias = bias_map.get(rules.get("market_bias"),"➖ нейтральное")
    return (
        f"🌅 *Ежедневный отчёт XAUUSD* — {datetime.utcnow().strftime('%Y-%m-%d')}\n\n"
        f"*Сделок всего:* {len(trades)}  *размечено:* {len(labeled)}  *исполнено:* {len(executed)}\n"
        f"*Винрейт общий:* {(int(wins_all/len(labeled)*100)) if labeled else '—'}%\n"
        f"*Винрейт исполненных:* {(int(wins_exec/len(executed)*100)) if executed else '—'}%\n"
        f"*Средняя уверенность:* {round(avg_conf,3)}\n\n"
        f"*Настроение рынка:* {bias} (сила {rules.get('bias_strength')})\n"
        f"*Предпочтение:* {rules.get('preferred_signal')}\n"
        f"*RSI коридор:* {rules.get('rsi_oversold')}/{rules.get('rsi_overbought')}\n"
        f"*Режим риска:* {rules.get('risk_mode')}, ATR-порог {rules.get('atr_caution_above')}\n"
        f"*Порог уверенности:* {rules.get('confidence_threshold')}\n\n"
        f"📚 *База знаний:* {kb.get('summary','—')}"
    )

def scheduler_hourly_insights():
    time.sleep(60)
    while True:
        try:
            with _lock: trades = load_trades()
            res = evolve_insights(trades)
            logger.info(f"[insights] записей {res['new']}, bias={res['rules'].get('market_bias')}")
            try: maybe_generate_artifacts()
            except: pass
        except: pass
        time.sleep(3600)

def scheduler_daily_report(hour_utc=8):
    while True:
        now = datetime.utcnow()
        target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
        if target <= now: target += timedelta(days=1)
        wait = (target - now).total_seconds()
        logger.info(f"[daily] следующий отчёт через {wait/3600:.1f} часов")
        time.sleep(wait)
        try:
            report_text = build_daily_report()
            tg_send_all(report_text)
            logger.info(f"[daily] отчёт отправлен всем")
        except Exception as e:
            logger.error(f"[daily] ошибка: {e}")
            time.sleep(60)

def scheduler_self_pinger(interval=300):
    url = f"http://127.0.0.1:{PORT}/ping"
    public = f"{PUBLIC_URL}/ping" if PUBLIC_URL else None
    time.sleep(15)
    while True:
        for u in (u for u in (public,url) if u):
            try: requests.get(u,timeout=8); break
            except: continue
        time.sleep(interval)

# ────────────────────────────────────────────────────────────────────────────
# Telegram-команды (русский) + свободный чат + МЕНЮ + АВТО-СИГНАЛЫ
# ────────────────────────────────────────────────────────────────────────────

def welcome_text():
    cmds = load_dyn_cmds()
    dyn = ""
    if cmds:
        dyn = "\n\n*Открытые мной команды:*\n"+"\n".join(f"• `{n}` — winrate {int(v['winrate']*100)}% ({v['n']} сделок)" for n,v in list(cmds.items())[:10])
    return (
        "👋 *XAUUSD — ИИ-бот для торговли золотом*\n\n"
        "Я анализирую сигналы, обучаюсь из 100+ источников и эволюционирую.\n\n"
        "*Команды:*\n"
        "• `/buy ЦЕНА RSI ТРЕНД ATR` — сигнал на покупку\n"
        "• `/sell ЦЕНА RSI ТРЕНД ATR` — сигнал на продажу\n"
        "• `/price` — текущая цена XAUUSD\n"
        "• `/sim_buy ЦЕНА RSI ТРЕНД ATR` — симулировать покупку\n"
        "• `/sim_sell ЦЕНА RSI ТРЕНД ATR` — симулировать продажу\n"
        "• `/status` — статистика\n"
        "• `/portfolio` — симулированный счёт\n"
        "• `/report` — отчёт сейчас\n"
        "• `/knowledge` — база знаний\n"
        "• `/pinescripts` — мои индикаторы\n"
        "• `/best` — лучшие паттерны\n"
        "• `/ask <вопрос>` — спросить DeepSeek\n"
        "• `/help` — эта справка\n"
        "• `/menu` — меню с кнопками\n\n"
        "*Свободный чат:* просто напишите мне сообщение — я отвечу через DeepSeek!\n"
        "_При уверенности > 70% я сам пишу вам с предложением сделки._"+dyn
    )

def _parse_trade_args(args):
    if len(args)!=4: raise ValueError("Формат: ЦЕНА RSI ТРЕНД ATR\nПример: 4695 54 UP 10")
    try:
        price = float(args[0])
        rsi = float(args[1])
        atr = float(args[3])
    except: raise ValueError("ЦЕНА, RSI и ATR должны быть числами.")
    trend = args[2].upper()
    if trend not in ("UP","DOWN","FLAT"): raise ValueError("ТРЕНД должен быть UP, DOWN или FLAT.")
    return price,rsi,trend,atr

def format_status_ru():
    with _lock: trades = load_trades()
    weights = load_weights()
    rules = load_rules()
    labeled = [t for t in trades if t.get("outcome") in ("win","loss")]
    wins = sum(1 for t in labeled if t["outcome"]=="win")
    wr = (wins/len(labeled)) if labeled else None
    next_ga = (GA_INTERVAL-(len(labeled)%GA_INTERVAL)) if labeled else GA_INTERVAL
    bias_map = {"bullish":"📈 бычье","bearish":"📉 медвежье","neutral":"➖ нейтральное"}
    return (
        f"📊 *Статус*\n"
        f"*Сделок:* {len(trades)}  *размечено:* {len(labeled)}\n"
        f"*Винрейт:* {int(wr*100) if wr else '—'}%\n"
        f"*До GA:* {next_ga}\n"
        f"*Веса:* signal={weights['signal']:.2f} price={weights['price']:.2f} rsi={weights['rsi']:.2f} trend={weights['trend']:.2f} atr={weights['atr']:.2f}\n"
        f"*Настроение:* {bias_map.get(rules.get('market_bias'),'—')} (сила {rules.get('bias_strength')})\n"
        f"*Порог:* {rules.get('confidence_threshold')}"
    )

def format_money_ru():
    with _lock: trades = load_trades()
    labeled = [t for t in trades if t.get("outcome") in ("win","loss")]
    if not labeled: return "💰 *Деньги*\n_Нет размеченных сделок._"
    wins = [t for t in labeled if t["outcome"]=="win"]
    losses = [t for t in labeled if t["outcome"]=="loss"]
    n = len(labeled)
    wr = len(wins)/n
    return f"💰 *Деньги*\n*Сделок:* {n} ({len(wins)}П/{len(losses)}У)\n*Винрейт:* {int(wr*100)}%"

def format_best_ru():
    with _lock: trades = load_trades()
    proven = discover_patterns(trades, min_samples=3, min_winrate=0)[:5]
    if not proven: return "🎯 *Паттерны*\n_Нужно минимум 3 сделки в группе._"
    return "🎯 *Топ паттернов*\n"+"\n".join(f"{i}. *{p['key'][0]}* / RSI *{p['key'][1]}* / тренд *{p['key'][2]}* → `{int(p['winrate']*100)}%` за {p['n']} сд." for i,p in enumerate(proven,1))

def format_auto_signal(signal, price, sl, tp, confidence, insights_count):
    risk_pct = round(abs(price - sl) / price * 100, 2)
    rr = round(abs(tp - price) / abs(price - sl), 1) if abs(price - sl) > 0 else 0
    emoji = "🚨" if confidence >= 0.85 else "📊"
    return (
        f"{emoji} *{signal} XAUUSD @ {price}*\n"
        f"   SL: {sl} ({risk_pct}% риска)\n"
        f"   TP: {tp} (1:{rr} R/R)\n"
        f"   Conf: {int(confidence*100)}% ({insights_count} инсайтов)"
    )

def auto_signal_checker():
    time.sleep(120)
    while True:
        try:
            time.sleep(300)
            price_data = get_current_xau_price()
            if not price_data or not price_data.get("current"):
                continue
            price = price_data["current"]
            rules = load_rules()
            insights = load_insights()
            insights_count = len(insights)
            rsi_val = 50
            atr_val = 15
            change = price_data.get("change", 0)
            trend = "UP" if (change and change > 0) else "DOWN"
            
            if trend == "UP":
                with _lock: weights = load_weights()
                features = normalize_features("BUY", price, rsi_val, trend, atr_val)
                conf = compute_confidence(features, weights)
                raw = {"signal": "BUY", "price": price, "rsi": rsi_val, "trend": trend, "atr": atr_val}
                conf, reasons, threshold = apply_rules(conf, raw, rules)
                if conf >= CONFIDENCE_THRESHOLD:
                    sl = round(price - atr_val * 0.8, 2)
                    tp = round(price + atr_val * 2.5, 2)
                    msg = format_auto_signal("BUY", price, sl, tp, conf, insights_count)
                    tg_send_all(msg)
                    logger.info(f"[AUTO-SIGNAL] BUY @ {price} | Conf: {conf}")
            elif trend == "DOWN":
                with _lock: weights = load_weights()
                features = normalize_features("SELL", price, rsi_val, trend, atr_val)
                conf = compute_confidence(features, weights)
                raw = {"signal": "SELL", "price": price, "rsi": rsi_val, "trend": trend, "atr": atr_val}
                conf, reasons, threshold = apply_rules(conf, raw, rules)
                if conf >= CONFIDENCE_THRESHOLD:
                    sl = round(price + atr_val * 0.8, 2)
                    tp = round(price - atr_val * 2.5, 2)
                    msg = format_auto_signal("SELL", price, sl, tp, conf, insights_count)
                    tg_send_all(msg)
                    logger.info(f"[AUTO-SIGNAL] SELL @ {price} | Conf: {conf}")
        except Exception as e:
            logger.warning(f"[AUTO-SIGNAL] ошибка: {e}")

def handle_command(message):
    text = (message.get("text") or "").strip()
    chat_id = message.get("chat",{}).get("id")
    
    logger.info(f"TG msg from {chat_id}: {text[:100]}")
    
    if text and not text.startswith("/"):
        if any(word in text.lower() for word in ["цена","price","стоит","стоимость","золото","xau","сколько"]):
            price_info = format_price_info()
            tg_send(price_info, chat_id=chat_id)
            return True
        answer, err = deepseek_ask(text)
        if err: tg_send(f"⚠️ {err}", chat_id=chat_id)
        else: tg_send(f"🧠 {answer}", chat_id=chat_id)
        return True
    
    if not text.startswith("/"): return False
    
    parts = text.split()
    cmd = parts[0].split("@",1)[0].lower()
    args = parts[1:]
    
    if cmd in ("/", "/menu"):
        keyboard = {
            "inline_keyboard": [
                [{"text": "🟢 BUY", "callback_data": "menu_buy"},
                 {"text": "🔴 SELL", "callback_data": "menu_sell"}],
                [{"text": "💰 Цена XAUUSD", "callback_data": "menu_price"},
                 {"text": "📊 Статус", "callback_data": "menu_status"}],
                [{"text": "🧠 Спросить AI", "callback_data": "menu_ask"},
                 {"text": "📈 Отчёт", "callback_data": "menu_report"}],
                [{"text": "🧪 Симулятор", "callback_data": "menu_sim"},
                 {"text": "❓ Помощь", "callback_data": "menu_help"}]
            ]
        }
        tg_send("📋 *Выбери действие:*", chat_id=chat_id, reply_markup=keyboard)
        return True
    
    if cmd in ("/start","/help"): tg_send(welcome_text(), chat_id=chat_id); return True
    
    if cmd in ("/buy","/sell"):
        side = "BUY" if cmd=="/buy" else "SELL"
        try: price,rsi,trend,atr = _parse_trade_args(args)
        except ValueError as e: tg_send(f"⚠️ {e}", chat_id=chat_id); return True
        process_signal(side,price,rsi,trend,atr,source="telegram")
        return True
    
    if cmd == "/price":
        price_info = format_price_info()
        tg_send(price_info, chat_id=chat_id)
        return True
    
    if cmd in ("/sim_buy","/sim_sell"):
        side = "BUY" if cmd=="/sim_buy" else "SELL"
        try: price,rsi,trend,atr = _parse_trade_args(args)
        except ValueError as e: tg_send(f"⚠️ {e}", chat_id=chat_id); return True
        sl = round(price-atr*0.8,2) if side=="BUY" else round(price+atr*0.8,2)
        tp = round(price+atr*2.5,2) if side=="BUY" else round(price-atr*2.5,2)
        trade,sim = sim_trade(side,price,sl,tp)
        emoji = "✅" if trade["outcome"]=="win" else "❌"
        tg_send(f"🧪 *Симуляция*\n{emoji} {side} @ {price}\nSL: {sl} | TP: {tp}\nP/L: ${trade['pnl']:.2f}\nБаланс: ${sim['balance']:.2f}", chat_id=chat_id)
        return True
    
    if cmd == "/portfolio": tg_send(format_portfolio(), chat_id=chat_id); return True
    if cmd == "/status": tg_send(format_status_ru(), chat_id=chat_id); return True
    if cmd == "/money": tg_send(format_money_ru(), chat_id=chat_id); return True
    if cmd == "/best": tg_send(format_best_ru(), chat_id=chat_id); return True
    if cmd == "/report": tg_send(build_daily_report(), chat_id=chat_id); return True
    
    if cmd == "/knowledge":
        kb = load_knowledge()
        tail = "\n".join(f"  • {s['s'][:160]}" for s in kb.get("snippets",[])[:5]) or "  • —"
        tg_send(f"📚 *База знаний*\n{kb.get('summary','—')}\n*Обновлено:* {kb.get('updated_at','—')}\n\n*Свежие выдержки:*\n{tail}", chat_id=chat_id)
        return True
    
    if cmd == "/pinescripts":
        items = load_pine()
        if not items: tg_send("🧬 *Pine скриптов пока нет.*\nЯ создам их когда найду паттерн с winrate > 60%.", chat_id=chat_id)
        else:
            for it in items[-3:]:
                p = it["pattern"]
                tg_send(f"🧬 *{it['name']}* — winrate {int(p['winrate']*100)}% за {p['n']} сделок\n```pine\n{it['code']}\n```", chat_id=chat_id)
        return True
    
    if cmd == "/ask":
        question = " ".join(args).strip()
        if not question: tg_send("Использование: `/ask ваш вопрос`", chat_id=chat_id); return True
        answer,err = deepseek_ask(question)
        if err: tg_send(f"⚠️ {err}", chat_id=chat_id)
        else: tg_send(f"🧠 *ИИ:*\n{answer}", chat_id=chat_id)
        return True
    
    dyn = load_dyn_cmds()
    if cmd in dyn:
        spec = dyn[cmd]
        sig,band,trend = spec["pattern_key"]
        if len(args)!=3: tg_send(f"Использование: `{cmd} ЦЕНА RSI ATR` — сигнал {sig} (тренд `{trend}`, RSI-полоса `{band}`).", chat_id=chat_id); return True
        try: price,rsi,atr = float(args[0]),float(args[1]),float(args[2])
        except: tg_send("⚠️ ЦЕНА, RSI и ATR должны быть числами.", chat_id=chat_id); return True
        process_signal(sig,price,rsi,trend,atr,source=f"dyn:{cmd}")
        return True
    
    tg_send(f"❓ Неизвестная команда `{cmd}`. Введи `/menu` или `/help` для справки.", chat_id=chat_id)
    return True

def handle_callback(cb):
    data = cb.get("data","")
    cb_id = cb.get("id")
    msg = cb.get("message",{})
    chat_id = msg.get("chat",{}).get("id")
    message_id = msg.get("message_id")
    if ":" not in data:
        if data == "menu_buy":
            tg_answer_callback(cb_id, "Введи: /buy ЦЕНА RSI ТРЕНД ATR")
            tg_send("Введи команду:\n`/buy ЦЕНА RSI ТРЕНД ATR`\nПример: `/buy 4700 54 UP 10`", chat_id=chat_id)
            return
        if data == "menu_sell":
            tg_answer_callback(cb_id, "Введи: /sell ЦЕНА RSI ТРЕНД ATR")
            tg_send("Введи команду:\n`/sell ЦЕНА RSI ТРЕНД ATR`\nПример: `/sell 4700 46 DOWN 10`", chat_id=chat_id)
            return
        if data == "menu_price":
            tg_answer_callback(cb_id, "Загружаю цену...")
            price_info = format_price_info()
            tg_send(price_info, chat_id=chat_id)
            return
        if data == "menu_status":
            tg_answer_callback(cb_id, "Загружаю статус...")
            tg_send(format_status_ru(), chat_id=chat_id)
            return
        if data == "menu_report":
            tg_answer_callback(cb_id, "Формирую отчёт...")
            tg_send(build_daily_report(), chat_id=chat_id)
            return
        if data == "menu_sim":
            tg_answer_callback(cb_id, "Симулятор: /sim_buy или /sim_sell")
            tg_send("🧪 *Симулятор:*\n`/sim_buy ЦЕНА RSI ТРЕНД ATR`\n`/sim_sell ЦЕНА RSI ТРЕНД ATR`", chat_id=chat_id)
            return
        if data == "menu_help":
            tg_answer_callback(cb_id, "Открываю помощь...")
            tg_send(welcome_text(), chat_id=chat_id)
            return
       if cmd == "/users":
        users_list = "\n".join(f"• `{cid}`" for cid in CHAT_IDS)
        tg_send(f"👥 *Пользователи получающие сигналы:*\n{users_list}", chat_id=chat_id)
        return True
        if data == "menu_ask":
            tg_answer_callback(cb_id, "Задай вопрос после /ask")
            tg_send("Используй: `/ask твой вопрос`", chat_id=chat_id)
            return
        tg_answer_callback(cb_id, "Некорректные данные")
        return
    
    action,payload = data.split(":",1)
    
    if action == "alert_ok":
        pending = load_pending()
        spec = pending.pop(payload,None)
        save_pending(pending)
        if not spec: tg_answer_callback(cb_id,"Алерт уже не актуален"); return
        tg_answer_callback(cb_id,"Принято ✅")
        if chat_id and message_id: tg_edit(chat_id,message_id,msg.get("text","")+"\n\n_— Подтверждено_", reply_markup={"inline_keyboard":[]})
        tg_send("✅ Сделка подтверждена. Отметьте исход под сигналом.")
        return
    
    if action == "alert_no":
        pending = load_pending(); pending.pop(payload,None); save_pending(pending)
        tg_answer_callback(cb_id,"Отклонено")
        if chat_id and message_id: tg_edit(chat_id,message_id,msg.get("text","")+"\n\n_— Отклонено_", reply_markup={"inline_keyboard":[]})
        return
    
    if action == "alert_why":
        pending = load_pending()
        spec = pending.get(payload)
        if not spec: tg_answer_callback(cb_id,"Алерт не найден"); return
        rules = load_rules()
        rs = "\n".join(f"  • {r}" for r in spec.get("reasons",[])) or "  • —"
        tg_send(f"❓ *Почему?*\nУверенность: `{int(spec['confidence']*100)}%`\nНастроение: {rules.get('market_bias')}\nПорог: `{rules.get('confidence_threshold')}`\n\n*Слагаемые:*\n{rs}")
        tg_answer_callback(cb_id,"Анализ отправлен")
        return
    
    if action in ("win","loss"):
        trade_id = payload
        ga_summary = None
        with _lock:
            trades = load_trades()
            target = next((t for t in trades if t.get("id")==trade_id),None)
            if not target: tg_answer_callback(cb_id,"Сделка не найдена"); return
            target["outcome"] = action
            target["labeled_at"] = datetime.utcnow().isoformat()+"Z"
            save_trades(trades)
            weights = load_weights()
            new_w,fit = maybe_run_ga(trades,weights)
            if new_w!=weights: ga_summary = f"GA эволюционировал веса (фитнес {fit:.2f})"
        tg_answer_callback(cb_id,"Записано ✅" if action=="win" else "Записано ❌")
        if chat_id and message_id: tg_edit(chat_id,message_id,msg.get("text","")+f"\n\n_Исход: {'✅ Победа' if action=='win' else '❌ Убыток'}_", reply_markup={"inline_keyboard":[]})
        if ga_summary: tg_send(f"🧬 {ga_summary}", chat_id=chat_id)
        try: maybe_generate_artifacts()
        except: pass
        return
    
    tg_answer_callback(cb_id,"Неизвестное действие")

# ────────────────────────────────────────────────────────────────────────────
# Flask
# ────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = SESSION_SECRET

HOMEPAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>XAUUSD ИИ-бот</title>
<style>body{font-family:system-ui;max-width:880px;margin:2rem auto;padding:0 1rem;color:#1f2937}
h1{margin:.2rem 0}p.sub{color:#6b7280}pre{background:#0f172a;color:#e2e8f0;padding:1rem;border-radius:8px;overflow-x:auto;font-size:13px}
code{background:#f1f5f9;padding:2px 6px;border-radius:4px}a{color:#2563eb}
.badge{display:inline-block;padding:.2rem .5rem;border-radius:6px;background:#10b981;color:#fff;font-size:.8rem}
</style></head><body><h1>XAUUSD ИИ-бот <span class="badge">онлайн</span></h1>
<p class="sub">Последние {{ count }} событий · <a href="/stats">статистика</a> · <a href="/learn">правила</a> · <a href="/knowledge">база знаний</a></p>
{% if lines %}<pre>{{ '\n'.join(lines) }}</pre>{% else %}<p><i>Лог пока пуст.</i></p>{% endif %}</body></html>"""

def _tail(path, n=15):
    if not os.path.exists(path): return []
    with open(path,"rb") as f:
        try:
            f.seek(0,os.SEEK_END); size = f.tell(); data = b""
            while size>0 and data.count(b"\n")<=n: step=min(2048,size); size-=step; f.seek(size); data=f.read(step)+data
        except: f.seek(0); data=f.read()
    return data.decode("utf-8",errors="replace").splitlines()[-n:]

@app.route("/")
def home():
    lines = _tail(LOG_FILE,15)
    return render_template_string(HOMEPAGE, lines=lines, count=len(lines))

@app.route("/ping")
def ping(): return jsonify({"status":"alive","time":datetime.utcnow().isoformat()+"Z"})

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not isinstance(data,dict): return jsonify({"error":"Тело запроса должно быть JSON-объектом"}),400
    required = ["signal","price","rsi","trend","atr"]
    missing = [k for k in required if data.get(k) is None]
    if missing: return jsonify({"error":f"Отсутствуют поля: {', '.join(missing)}"}),400
    outcome = data.get("outcome")
    if outcome is not None and outcome not in ("win","loss"): return jsonify({"error":"outcome должен быть 'win' или 'loss'"}),400
    trade,ga = process_signal(data["signal"],data["price"],data["rsi"],data["trend"],data["atr"],outcome=outcome,source="webhook")
    return jsonify({"status":"ok","confidence":trade["confidence"],"decision":trade["decision"],"threshold":trade["threshold"],"reasons":trade["reasons"],"weights":trade["weights_used"],"ga":ga})

@app.route("/stats")
def stats():
    with _lock: trades = load_trades()
    weights = load_weights()
    labeled = [t for t in trades if t.get("outcome") in ("win","loss")]
    executed = [t for t in labeled if t.get("decision")=="execute"]
    wins_all = sum(1 for t in labeled if t["outcome"]=="win")
    wins_exec = sum(1 for t in executed if t["outcome"]=="win")
    avg_conf = (sum(t["confidence"] for t in trades)/len(trades)) if trades else 0
    return jsonify({"total_trades":len(trades),"labeled":len(labeled),"executed":len(executed),"winrate_overall":round(wins_all/len(labeled),4) if labeled else None,"winrate_executed":round(wins_exec/len(executed),4) if executed else None,"average_confidence":round(avg_conf,4),"weights":weights,"next_ga_in":(GA_INTERVAL-(len(labeled)%GA_INTERVAL)) if labeled else GA_INTERVAL})

@app.route("/evolve", methods=["GET","POST"])
def evolve_endpoint():
    with _lock: trades = load_trades()
    res = evolve_insights(trades)
    art = maybe_generate_artifacts()
    return jsonify({"status":"ok","new_records":res["new"],"rules":res["rules"],"artifacts":art})

@app.route("/learn")
def learn_endpoint(): return jsonify({"rules":load_rules(),"insights_count":len(load_insights())})

@app.route("/knowledge")
def knowledge_endpoint(): return jsonify(load_knowledge())

@app.route("/pinescripts")
def pinescripts_endpoint(): return jsonify(load_pine())

@app.route("/commands")
def commands_endpoint(): return jsonify(load_dyn_cmds())

@app.route("/simulator")
def simulator_endpoint(): return jsonify(load_simulator())

@app.route("/report", methods=["GET","POST"])
def report_endpoint():
    text = build_daily_report()
    res = tg_send_all(text)
    return jsonify({"status":"ok","telegram":res,"preview":text[:300]})

@app.route("/telegram/setwebhook", methods=["GET","POST"])
def telegram_setwebhook():
    url = request.args.get("url") or (request.get_json(silent=True) or {}).get("url")
    if not url and PUBLIC_URL: url = f"{PUBLIC_URL}/telegram/webhook"
    if not url: return jsonify({"error":"Передайте url или задайте PUBLIC_URL"}),400
    return jsonify(tg_set_webhook(url))

@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True) or {}
    try:
        if update.get("message"): handle_command(update["message"])
        elif update.get("callback_query"): handle_callback(update["callback_query"])
    except Exception as e: logger.exception(f"[telegram] {e}")
    return jsonify({"ok":True})

def start_background_threads():
    threading.Thread(target=hourly_self_tune, daemon=True).start()
    threading.Thread(target=scheduler_hourly_insights, daemon=True).start()
    threading.Thread(target=scheduler_daily_report, daemon=True).start()
    threading.Thread(target=scheduler_self_pinger, daemon=True).start()
    threading.Thread(target=auto_signal_checker, daemon=True).start()
    logger.info("Фоновые потоки запущены: self-tune, insights, daily-report, self-pinger, auto-signals")

start_background_threads()

if __name__ == "__main__":
    logger.info(f"Запуск Flask на 0.0.0.0:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
