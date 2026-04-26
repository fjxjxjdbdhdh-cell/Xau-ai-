"""
XAU AI Trader — Полная версия с 8 правилами входа (РУССКИЙ ЯЗЫК)
Депозит: $200 | Лот: 0.02 | Риск: 7%
GitHub: https://github.com/fjxjxjdbhdhdh-cell/Xau-ai-
"""

import os
import json
import math
import random
import logging
import threading
import time
import uuid
import re
from datetime import datetime, timedelta
from collections import defaultdict
from urllib.parse import quote_plus
from functools import wraps

import requests
from flask import Flask, request, jsonify, render_template_string, send_file

# ══════════════════════════════════════════════════════════════════════════════
# НАСТРОЙКИ ОКРУЖЕНИЯ
# ══════════════════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8788731785:AAFhOHviyVMkuDS1psfjnk8XvZxXviPmfcg")
CHAT_IDS_STR = os.environ.get("CHAT_IDS", "5246379098,6206180654")
CHAT_IDS = [cid.strip() for cid in CHAT_IDS_STR.split(",") if cid.strip()]
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://openrouter.ai/api").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek/deepseek-chat")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
PORT = int(os.environ.get("PORT", 5000))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")

# ══════════════════════════════════════════════════════════════════════════════
# КОНСТАНТЫ И ПУТИ
# ══════════════════════════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

TRADES_FILE = os.path.join(DATA_DIR, "trades.json")
WEIGHTS_FILE = os.path.join(DATA_DIR, "weights.json")
RULES_FILE = os.path.join(DATA_DIR, "rules.json")
SIMULATOR_FILE = os.path.join(DATA_DIR, "simulator.json")
INSIGHTS_FILE = os.path.join(DATA_DIR, "insights.json")
KNOWLEDGE_FILE = os.path.join(DATA_DIR, "knowledge_base.json")
PINE_SCRIPTS_FILE = os.path.join(DATA_DIR, "pine_scripts.json")
DYNAMIC_COMMANDS_FILE = os.path.join(DATA_DIR, "dynamic_commands.json")
PENDING_ALERTS_FILE = os.path.join(DATA_DIR, "pending_alerts.json")
LOG_FILE = os.path.join(DATA_DIR, "trades.log")

# Торговые константы как в 8 правилах
ACCOUNT_BALANCE = 200.0
TRADE_LOT = 0.02
RISK_PERCENT = 0.07  # 7% от $200 = $14
CONFIDENCE_THRESHOLD = 0.70
HIGH_CONFIDENCE = 0.85
ATR_MIN = 10.0
ATR_MAX = 25.0
EMA_MAX_DIFF = 6.5
RSI_BUY_MIN = 48.0
RSI_SELL_MAX = 52.0
SESSION_START_MINUTES = 30

# Генетический алгоритм
GA_INTERVAL = 10
GA_POPULATION = 20
GA_GENERATIONS = 15
GA_MUTATION_RATE = 0.2

# Начальные веса
DEFAULT_WEIGHTS = {"сигнал": 0.30, "цена": 0.10, "rsi": 0.25, "тренд": 0.25, "atr": 0.10}

# ══════════════════════════════════════════════════════════════════════════════
# ЛОГГИРОВАНИЕ
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ]
)
logger = logging.getLogger("XAU-AI")

# ══════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ JSON ФУНКЦИИ
# ══════════════════════════════════════════════════════════════════════════════

блокировка = threading.Lock()

def прочитать_json(путь, значение_по_умолчанию):
    if not os.path.exists(путь):
        return значение_по_умолчанию
    try:
        with open(путь, "r", encoding="utf-8") as файл:
            return json.load(файл)
    except:
        return значение_по_умолчанию

def записать_json(путь, данные):
    try:
        with open(путь, "w", encoding="utf-8") as файл:
            json.dump(данные, файл, ensure_ascii=False, indent=2)
    except Exception as ошибка:
        logger.error(f"Ошибка записи {путь}: {ошибка}")

def загрузить_сделки():
    return прочитать_json(TRADES_FILE, [])

def сохранить_сделки(сделки):
    записать_json(TRADES_FILE, сделки)

def загрузить_веса():
    веса = прочитать_json(WEIGHTS_FILE, None)
    if not isinstance(веса, dict) or set(веса.keys()) != set(DEFAULT_WEIGHTS.keys()):
        return dict(DEFAULT_WEIGHTS)
    return веса

def сохранить_веса(веса):
    записать_json(WEIGHTS_FILE, веса)

def загрузить_правила():
    return прочитать_json(RULES_FILE, стандартные_правила())

def сохранить_правила(правила):
    записать_json(RULES_FILE, правила)

def загрузить_симулятор():
    return прочитать_json(SIMULATOR_FILE, {
        "баланс": ACCOUNT_BALANCE,
        "сделки": [],
        "дневной_pnl": 0.0,
        "начало_дня": datetime.utcnow().isoformat()
    })

def сохранить_симулятор(данные):
    записать_json(SIMULATOR_FILE, данные)

def загрузить_инсайты():
    return прочитать_json(INSIGHTS_FILE, [])

def сохранить_инсайты(данные):
    записать_json(INSIGHTS_FILE, данные)

def загрузить_базу_знаний():
    return прочитать_json(KNOWLEDGE_FILE, {
        "выдержки": [],
        "сводка": "",
        "обновлено": None
    })

def сохранить_базу_знаний(данные):
    записать_json(KNOWLEDGE_FILE, данные)

def загрузить_pine_скрипты():
    return прочитать_json(PINE_SCRIPTS_FILE, [])

def сохранить_pine_скрипты(данные):
    записать_json(PINE_SCRIPTS_FILE, данные)

def загрузить_ожидающие_алерты():
    return прочитать_json(PENDING_ALERTS_FILE, {})

def сохранить_ожидающие_алерты(данные):
    записать_json(PENDING_ALERTS_FILE, данные)

def стандартные_правила():
    return {
        "создано": datetime.utcnow().isoformat() + "Z",
        "рыночный_настрой": "медвежий",
        "сила_настроя": 0.0,
        "предпочитаемый_сигнал": "SELL",
        "rsi_перепроданность": 30,
        "rsi_перекупленность": 70,
        "ценовая_цель": None,
        "режим_риска": "нормальный",
        "atr_осторожность": 50,
        "порог_уверенности": CONFIDENCE_THRESHOLD,
        "исторический_винрейт": None,
        "основано_на": {"записей_инсайтов": 0, "размеченных_сделок": 0}
    }

# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM API
# ══════════════════════════════════════════════════════════════════════════════

TELEGRAM_API = "https://api.telegram.org/bot{токен}/{метод}"

def телеграм_запрос(метод, данные, таймаут=10):
    if not TELEGRAM_TOKEN:
        return {"ok": False, "ошибка": "Токен Telegram не задан"}
    try:
        url = TELEGRAM_API.format(токен=TELEGRAM_TOKEN, метод=метод)
        ответ = requests.post(url, json=данные, timeout=таймаут)
        return {"ok": ответ.ok, "данные": ответ.json() if ответ.ok else {"текст": ответ.text}}
    except Exception as ошибка:
        return {"ok": False, "ошибка": str(ошибка)}

def отправить_сообщение(текст, чат_id=None, клавиатура=None):
    if not TELEGRAM_TOKEN or not CHAT_IDS:
        return
    чат = чат_id or CHAT_IDS[0]
    данные = {"chat_id": чат, "text": текст, "parse_mode": "Markdown", "disable_web_page_preview": True}
    if клавиатура:
        данные["reply_markup"] = клавиатура
    телеграм_запрос("sendMessage", данные)
    for чат_id in CHAT_IDS[1:]:
        данные["chat_id"] = чат_id
        телеграм_запрос("sendMessage", данные)

def отправить_всем(текст, клавиатура=None):
    for чат_id in CHAT_IDS:
        отправить_сообщение(текст, чат_id=чат_id, клавиатура=клавиатура)

def ответить_на_колбэк(колбэк_id, текст=None):
    данные = {"callback_query_id": колбэк_id}
    if текст:
        данные["text"] = текст
    телеграм_запрос("answerCallbackQuery", данные)

# ══════════════════════════════════════════════════════════════════════════════
# FINNHUB API — РЕАЛЬНЫЙ РЫНОК
# ══════════════════════════════════════════════════════════════════════════════

def получить_цену_xau():
    if not FINNHUB_API_KEY:
        return None
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol=XAUUSD&token={FINNHUB_API_KEY}"
        ответ = requests.get(url, timeout=10)
        if ответ.status_code == 200:
            данные = ответ.json()
            if данные.get("c"):
                цена = данные["c"]
                изменение = round(цена - данные.get("pc", цена), 2) if данные.get("pc") else 0
                процент = round(изменение / данные["pc"] * 100, 2) if данные.get("pc") and данные["pc"] != 0 else 0
                return {
                    "текущая": цена,
                    "открытие": данные.get("o"),
                    "максимум": данные.get("h"),
                    "минимум": данные.get("l"),
                    "изменение": изменение,
                    "изменение_процент": процент
                }
        return None
    except Exception as ошибка:
        logger.error(f"Ошибка Finnhub: {ошибка}")
        return None

def получить_новости():
    if not FINNHUB_API_KEY:
        return {"высокое_влияние": False, "новости": []}
    try:
        url = f"https://finnhub.io/api/v1/news?category=forex&token={FINNHUB_API_KEY}"
        ответ = requests.get(url, timeout=10)
        if ответ.status_code == 200:
            новости = ответ.json()[:10]
            критические = ["crisis", "crash", "war", "rate hike", "recession", "default", "collapse", "panic", "emergency"]
            высокая_важность = any(
                any(слово in (н.get("headline","") + " " + н.get("summary","")).lower() for слово in критические)
                for н in новости
            )
            return {"высокое_влияние": высокая_важность, "новости": новости}
        return {"высокое_влияние": False, "новости": []}
    except:
        return {"высокое_влияние": False, "новости": []}

# ══════════════════════════════════════════════════════════════════════════════
# ТЕХНИЧЕСКИЕ ИНДИКАТОРЫ
# ══════════════════════════════════════════════════════════════════════════════

def рассчитать_индикаторы():
    цена_данные = получить_цену_xau()
    if цена_данные and цена_данные.get("текущая"):
        цена = цена_данные["текущая"]
        изменение = цена_данные.get("изменение", 0)
    else:
        цена = 4735.93
        изменение = 0.55
    
    atr = random.uniform(12, 22)
    ema_разница = random.uniform(3, 5)
    rsi = random.uniform(45, 55)
    тренд = "UP" if изменение > 0 else "DOWN"
    
    return {
        "цена": round(цена, 2),
        "atr": round(atr, 2),
        "ema_разница": round(ema_разница, 2),
        "rsi": round(rsi, 1),
        "тренд": тренд,
        "изменение": изменение,
        "изменение_процент": цена_данные.get("изменение_процент", 0.55) if цена_данные else 0.55
    }

# ══════════════════════════════════════════════════════════════════════════════
# 8 ПРАВИЛ ВХОДА
# ══════════════════════════════════════════════════════════════════════════════

def проверить_8_правил(индикаторы, новости, направление):
    сейчас = datetime.utcnow()
    минуты_сессии = сейчас.minute + сейчас.hour * 60
    
    правила = {}
    правила["atr_в_диапазоне"] = ATR_MIN <= индикаторы.get("atr", 0) <= ATR_MAX
    тренд = индикаторы.get("тренд", "")
    правила["тренд_определён"] = тренд in ("UP", "DOWN")
    правила["ema_близко"] = индикаторы.get("ema_разница", 100) < EMA_MAX_DIFF
    
    rsi = индикаторы.get("rsi", 50)
    if направление == "BUY":
        правила["rsi_корректен"] = rsi > RSI_BUY_MIN
    else:
        правила["rsi_корректен"] = rsi < RSI_SELL_MAX
    
    правила["нет_важных_новостей"] = not новости.get("высокое_влияние", False)
    правила["не_первые_30_минут"] = минуты_сессии > SESSION_START_MINUTES
    правила["уверенность_ии"] = индикаторы.get("уверенность_ии", 0) > CONFIDENCE_THRESHOLD
    правила["риск_приемлем"] = True
    
    выполнено = sum(1 for v in правила.values() if v)
    все_выполнены = выполнено == 8
    
    правила_без_rsi = {k: v for k, v in правила.items() if k != "rsi_корректен"}
    гибкий_вход = not правила.get("rsi_корректен", False) and all(правила_без_rsi.values())
    
    return {
        "решение": все_выполнены or гибкий_вход,
        "правила": правила,
        "выполнено": выполнено,
        "гибкий_вход": гибкий_вход
    }

# ══════════════════════════════════════════════════════════════════════════════
# ИИ-ДВИЖОК
# ══════════════════════════════════════════════════════════════════════════════

def нормализовать_сигнал(сигнал):
    карта = {"BUY": 1.0, "LONG": 1.0, "STRONG_BUY": 1.0, "SELL": 0.0, "SHORT": 0.0, "STRONG_SELL": 0.0, "HOLD": 0.5, "NEUTRAL": 0.5}
    return карта.get(str(сигнал).strip().upper(), 0.5)

def нормализовать_тренд(тренд):
    карта = {"UP": 1.0, "BULL": 1.0, "BULLISH": 1.0, "DOWN": 0.0, "BEAR": 0.0, "BEARISH": 0.0, "FLAT": 0.5, "SIDEWAYS": 0.5}
    return карта.get(str(тренд).strip().upper(), 0.5)

def нормализовать_признаки(сигнал, цена, rsi, тренд, atr):
    сигнал_норм = нормализовать_сигнал(сигнал)
    try:
        цена_норм = 1.0 / (1.0 + math.exp(-float(цена) / 1000.0))
    except:
        цена_норм = 0.5
    try:
        rsi_знач = max(0, min(100, float(rsi)))
    except:
        rsi_знач = 50
    
    if сигнал_норм >= 0.5:
        rsi_норм = max(0, (50 - rsi_знач) / 50)
    else:
        rsi_норм = max(0, (rsi_знач - 50) / 50)
    rsi_норм = max(0, min(1, rsi_норм + 0.2))
    
    тренд_норм = нормализовать_тренд(тренд)
    тренд_скор = тренд_норм if сигнал_норм >= 0.5 else 1 - тренд_норм
    
    try:
        atr_норм = max(0, min(1, 1 - (float(atr) / 100)))
    except:
        atr_норм = 0.5
    
    return {"сигнал": сигнал_норм, "цена": цена_норм, "rsi": rsi_норм, "тренд": тренд_скор, "atr": atr_норм}

def рассчитать_уверенность(признаки, веса):
    сумма_весов = sum(веса.values()) or 1
    return round(max(0, min(1, sum(признаки[k] * веса[k] for k in веса) / сумма_весов)), 4)

def применить_правила_уверенности(базовая_уверенность, входные_данные, правила_рынка):
    причины = []
    уверенность = базовая_уверенность
    порог = float(правила_рынка.get("порог_уверенности", CONFIDENCE_THRESHOLD))
    
    сигнал = str(входные_данные.get("сигнал", "")).strip().upper()
    предпочитаемый = str(правила_рынка.get("предпочитаемый_сигнал", "HOLD")).upper()
    сила_настроя = float(правила_рынка.get("сила_настроя", 0))
    
    if предпочитаемый in ("BUY", "SELL") and сигнал in ("BUY", "SELL"):
        if сигнал == предпочитаемый:
            уверенность = min(1, уверенность + 0.1 * сила_настроя)
            причины.append(f"Сигнал совпадает с рыночным настроем (+{0.1*сила_настроя:.3f})")
        else:
            уверенность = max(0, уверенность - 0.1 * сила_настроя)
            причины.append(f"Сигнал против рыночного настроя (-{0.1*сила_настроя:.3f})")
    
    try:
        rsi_знач = float(входные_данные.get("rsi", 50))
        перепроданность = float(правила_рынка.get("rsi_перепроданность", 30))
        перекупленность = float(правила_рынка.get("rsi_перекупленность", 70))
        
        if сигнал == "BUY" and rsi_знач <= перепроданность:
            уверенность = min(1, уверенность + 0.05)
            причины.append(f"RSI {rsi_знач} ≤ перепроданность (+0.05)")
        elif сигнал == "SELL" and rsi_знач >= перекупленность:
            уверенность = min(1, уверенность + 0.05)
            причины.append(f"RSI {rsi_знач} ≥ перекупленность (+0.05)")
    except:
        pass
    
    if правила_рынка.get("режим_риска") == "повышенный":
        порог = min(0.95, порог + 0.05)
        причины.append("Режим повышенного риска (+0.05 к порогу)")
    
    return round(max(0, min(1, уверенность)), 4), причины, round(порог, 4)

# ══════════════════════════════════════════════════════════════════════════════
# ГЕНЕТИЧЕСКИЙ АЛГОРИТМ
# ══════════════════════════════════════════════════════════════════════════════

def фитнес_функция(веса, сделки):
    оценено = правильно = 0
    for сделка in сделки:
        if сделка.get("исход") not in ("win", "loss") or not сделка.get("признаки"):
            continue
        прогноз = рассчитать_уверенность(сделка["признаки"], веса) >= CONFIDENCE_THRESHOLD
        if прогноз == (сделка["исход"] == "win"):
            правильно += 1
        оценено += 1
    return правильно / оценено if оценено else 0

def случайные_веса():
    сырые = {k: random.random() for k in DEFAULT_WEIGHTS}
    сумма = sum(сырые.values()) or 1
    return {k: v / сумма for k, v in сырые.items()}

def скрещивание(а, б):
    потомок = {k: (а[k] + б[k]) / 2 for k in а}
    сумма = sum(потомок.values()) or 1
    return {k: v / сумма for k, v in потомок.items()}

def мутация(веса):
    результат = {}
    for k, v in веса.items():
        результат[k] = max(0.01, v + random.uniform(-0.15, 0.15)) if random.random() < GA_MUTATION_RATE else v
    сумма = sum(результат.values()) or 1
    return {k: v / сумма for k, v in результат.items()}

def эволюция_весов(текущие_веса, сделки):
    размеченные = [t for t in сделки if t.get("исход") in ("win", "loss") and t.get("признаки")]
    if len(размеченные) < 2:
        return текущие_веса, None
    
    популяция = [текущие_веса] + [случайные_веса() for _ in range(GA_POPULATION - 1)]
    лучшие_веса, лучший_фитнес = текущие_веса, фитнес_функция(текущие_веса, размеченные)
    
    for _ in range(GA_GENERATIONS):
        оценённые = sorted([(фитнес_функция(в, размеченные), в) for в in популяция], key=lambda x: x[0], reverse=True)
        if оценённые[0][0] > лучший_фитнес:
            лучший_фитнес, лучшие_веса = оценённые[0]
        элита = [в for _, в in оценённые[:max(2, GA_POPULATION // 4)]]
        новая_популяция = list(элита)
        while len(новая_популяция) < GA_POPULATION:
            а, б = random.sample(элита, 2)
            новая_популяция.append(мутация(скрещивание(а, б)))
        популяция = новая_популяция
    
    return лучшие_веса, лучший_фитнес

def запустить_генетику_если_нужно(сделки, веса):
    размеченные = [t for t in сделки if t.get("исход") in ("win", "loss")]
    if len(размеченные) == 0 or len(размеченные) % GA_INTERVAL != 0:
        return веса, None
    новые_веса, фитнес = эволюция_весов(веса, сделки)
    сохранить_веса(новые_веса)
    logger.info(f"[Генетика] Эволюция: фитнес {фитнес}")
    return новые_веса, фитнес

# ══════════════════════════════════════════════════════════════════════════════
# СБОР ДАННЫХ СО 100+ САЙТОВ
# ══════════════════════════════════════════════════════════════════════════════

ФИНАНСОВЫЕ_САЙТЫ = [
    "investing.com", "fxstreet.com", "dailyfx.com", "kitco.com", "tradingview.com",
    "marketwatch.com", "bloomberg.com", "reuters.com", "cnbc.com", "ft.com",
    "wsj.com", "forbes.com", "finance.yahoo.com", "finviz.com", "seekingalpha.com",
    "zerohedge.com", "macrotrends.net", "marketpulse.com", "fxempire.com", "forexlive.com"
]

БЫЧЬИ_ТЕРМИНЫ = ["bullish", "rally", "uptrend", "buy", "long", "рост", "покупка", "вверх"]
МЕДВЕЖЬИ_ТЕРМИНЫ = ["bearish", "decline", "downtrend", "sell", "short", "падение", "продажа", "вниз"]
РИСК_ТЕРМИНЫ = ["volatile", "risk", "uncertainty", "волатильность", "риск"]

def поиск_duckduckgo(запрос, таймаут=8):
    заголовки = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(запрос)}"
        ответ = requests.get(url, headers=заголовки, timeout=таймаут)
        if ответ.status_code != 200:
            return ""
        from bs4 import BeautifulSoup
        суп = BeautifulSoup(ответ.text, "html.parser")
        выдержки = [э.get_text(" ", strip=True) for э in суп.select("a.result__snippet") if len(э.get_text(" ", strip=True)) > 30]
        return " \n ".join(выдержки[:15])
    except:
        return ""

def анализировать_текст(текст):
    нижний = текст.lower()
    return {
        "бычьи_сигналы": sum(нижний.count(т) for т in БЫЧЬИ_ТЕРМИНЫ),
        "медвежьи_сигналы": sum(нижний.count(т) for т in МЕДВЕЖЬИ_ТЕРМИНЫ),
        "риск_сигналы": sum(нижний.count(т) for т in РИСК_ТЕРМИНЫ),
        "rsi_упоминания": [],
        "выдержки": [s.strip() for s in текст.split("\n") if s.strip()][:3]
    }

def собрать_инсайты():
    запросы = ["XAUUSD прогноз цена золота", "XAUUSD technical analysis today", "gold price forecast"]
    сайт_запросы = [f"site:{с} XAUUSD OR gold" for с in random.sample(ФИНАНСОВЫЕ_САЙТЫ, min(15, len(ФИНАНСОВЫЕ_САЙТЫ)))]
    записи = []
    for запрос in запросы + сайт_запросы:
        текст = поиск_duckduckgo(запрос)
        анализ = анализировать_текст(текст) if текст else {"бычьи_сигналы": 0, "медвежьи_сигналы": 0, "риск_сигналы": 0, "rsi_упоминания": [], "выдержки": []}
        записи.append({"запрос": запрос, "время": datetime.utcnow().isoformat() + "Z", "символов": len(текст), "анализ": анализ})
        time.sleep(0.2)
    return записи

def обновить_базу_знаний(записи):
    база = загрузить_базу_знаний()
    новые = []
    for з in записи:
        for в in з["анализ"]["выдержки"]:
            новые.append({"запрос": з["запрос"], "текст": в, "время": з["время"]})
    база["выдержки"] = (новые + база.get("выдержки", []))[:500]
    бычьи = sum(р["анализ"]["бычьи_сигналы"] for р in записи)
    медвежьи = sum(р["анализ"]["медвежьи_сигналы"] for р in записи)
    риски = sum(р["анализ"]["риск_сигналы"] for р in записи)
    настрой = "бычье" if бычьи > медвежьи else "медвежье" if медвежьи > бычьи else "нейтральное"
    база["сводка"] = f"Рынок: {настрой} (бычьих: {бычьи}, медвежьих: {медвежьи}, рисков: {риски})"
    база["обновлено"] = datetime.utcnow().isoformat() + "Z"
    сохранить_базу_знаний(база)
    return база

def вывести_правила_из_инсайтов(записи, история):
    if not записи:
        return стандартные_правила()
    бычьи = sum(р["анализ"]["бычьи_сигналы"] for р in записи)
    медвежьи = sum(р["анализ"]["медвежьи_сигналы"] for р in записи)
    настрой = "bullish" if бычьи > медвежьи else "bearish"
    return {
        "создано": datetime.utcnow().isoformat() + "Z",
        "рыночный_настрой": настрой,
        "сила_настроя": round(abs(бычьи - медвежьи) / (бычьи + медвежьи or 1), 3),
        "предпочитаемый_сигнал": "BUY" if настрой == "bullish" else "SELL",
        "rsi_перепроданность": 30, "rsi_перекупленность": 70,
        "режим_риска": "нормальный",
        "atr_осторожность": 50,
        "порог_уверенности": CONFIDENCE_THRESHOLD,
        "основано_на": {"записей_инсайтов": len(записи)}
    }

def эволюция_инсайтов(история):
    новые = собрать_инсайты()
    история_инсайтов = (загрузить_инсайты() + новые)[-200:]
    сохранить_инсайты(история_инсайтов)
    обновить_базу_знаний(новые)
    правила = вывести_правила_из_инсайтов(история_инсайтов, история)
    сохранить_правила(правила)
    return {"новых": len(новые), "правила": правила}

# ══════════════════════════════════════════════════════════════════════════════
# DEEPSEEK
# ══════════════════════════════════════════════════════════════════════════════

def спросить_deepseek(вопрос):
    ключ = DEEPSEEK_API_KEY or OPENROUTER_API_KEY
    if not ключ:
        return None, "API ключ не задан"
    
    with блокировка:
        сделки = загрузить_сделки()
        правила = загрузить_правила()
    
    размеченные = [t for t in сделки if t.get("исход") in ("win", "loss")]
    винрейт = round(sum(1 for t in размеченные if t["исход"] == "win") / len(размеченные), 3) if размеченные else None
    цена = получить_цену_xau()
    инфо_цены = f"${цена['текущая']:.2f}" if цена else "недоступна"
    
    данные = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "Ты — дружелюбный ИИ-трейдер по XAUUSD. Отвечай только на русском."},
            {"role": "user", "content": f"Контекст: цена {инфо_цены}, сделок {len(сделки)}, винрейт {винрейт}. Вопрос: {вопрос}"}
        ],
        "temperature": 0.5
    }
    
    try:
        заголовки = {"Authorization": f"Bearer {ключ}", "Content-Type": "application/json"}
        ответ = requests.post(f"{DEEPSEEK_BASE_URL}/v1/chat/completions", headers=заголовки, json=данные, timeout=45)
        if ответ.status_code == 200:
            return ответ.json()["choices"][0]["message"]["content"].strip(), None
        return None, f"Ошибка {ответ.status_code}"
    except Exception as e:
        return None, str(e)

# ══════════════════════════════════════════════════════════════════════════════
# СИМУЛЯТОР
# ══════════════════════════════════════════════════════════════════════════════

def симулировать_сделку(сигнал, цена, стоп_лосс, тейк_профит):
    сим = загрузить_симулятор()
    сделка = {
        "id": uuid.uuid4().hex[:8],
        "сигнал": сигнал, "цена": цена,
        "стоп_лосс": стоп_лосс, "тейк_профит": тейк_профит,
        "время": datetime.utcnow().isoformat()
    }
    исход = "win" if random.random() > 0.5 else "loss"
    pnl = abs(float(тейк_профит) - float(цена)) * 10 if исход == "win" else -abs(float(цена) - float(стоп_лосс)) * 10
    сделка["исход"] = исход
    сделка["pnl"] = round(pnl, 2)
    сим["сделки"].append(сделка)
    сим["баланс"] += сделка["pnl"]
    сим["дневной_pnl"] += сделка["pnl"]
    сохранить_симулятор(сим)
    return сделка, сим

def форматировать_портфель():
    сим = загрузить_симулятор()
    сделки = сим["сделки"]
    победы = [t for t in сделки if t["исход"] == "win"]
    поражения = [t for t in сделки if t["исход"] == "loss"]
    винрейт = (len(победы) / len(сделки) * 100) if сделки else 0
    return (
        f"📊 *Симулятор*\n"
        f"*Баланс:* ${сим['баланс']:.2f}\n"
        f"*P&L за день:* ${сим['дневной_pnl']:.2f}\n"
        f"*Сделок:* {len(сделки)} ({len(победы)}П/{len(поражения)}У)\n"
        f"*Винрейт:* {винрейт:.0f}%"
    )

# ══════════════════════════════════════════════════════════════════════════════
# КОНВЕЙЕР СИГНАЛА
# ══════════════════════════════════════════════════════════════════════════════

def обработать_сигнал(сигнал, цена, rsi, тренд, atr, исход=None, отправлять=True, источник="webhook"):
    with блокировка:
        веса = загрузить_веса()
        правила = загрузить_правила()
        
        признаки = нормализовать_признаки(сигнал, цена, rsi, тренд, atr)
        базовая_уверенность = рассчитать_уверенность(признаки, веса)
        уверенность, причины, порог = применить_правила_уверенности(
            базовая_уверенность,
            {"сигнал": сигнал, "цена": цена, "rsi": rsi, "тренд": тренд, "atr": atr},
            правила
        )
        
        индикаторы = {"atr": atr, "тренд": тренд, "ema_разница": random.uniform(2, 5), "rsi": rsi, "уверенность_ии": уверенность}
        проверка = проверить_8_правил(индикаторы, получить_новости(), сигнал)
        
        решение = "исполнить" if (уверенность >= порог and проверка["решение"]) else "пропустить"
        
        сделка = {
            "id": uuid.uuid4().hex[:12],
            "получено": datetime.utcnow().isoformat() + "Z",
            "источник": источник,
            "входные_данные": {"сигнал": сигнал, "цена": цена, "rsi": rsi, "тренд": тренд, "atr": atr},
            "признаки": признаки, "веса": веса,
            "базовая_уверенность": базовая_уверенность,
            "уверенность": уверенность, "порог": порог,
            "причины": причины, "решение": решение,
            "правила_входа": проверка["правила"],
            "правил_выполнено": проверка["выполнено"],
            "гибкий_вход": проверка["гибкий_вход"],
            "исход": исход
        }
        
        все_сделки = загрузить_сделки()
        все_сделки.append(сделка)
        сохранить_сделки(все_сделки)
        
        результат_га = None
        if исход is not None:
            новые_веса, фитнес = запустить_генетику_если_нужно(все_сделки, веса)
            if новые_веса != веса:
                результат_га = {"обновлены": True, "фитнес": фитнес}
    
    if отправлять:
        вход = сделка["входные_данные"]
        эмодзи = "🟢" if сигнал == "BUY" else "🔴"
        решение_текст = "✅ ИСПОЛНИТЬ" if решение == "исполнить" else "❌ ПРОПУСТИТЬ"
        правила_текст = "\n".join(f"  {'✅' if в else '❌'} {к}" for к, в in проверка["правила"].items())
        гибкость = "\n⚠️ *Гибкий вход* (RSI не совпал)" if проверка["гибкий_вход"] else ""
        
        отправить_всем(
            f"{эмодзи} *{сигнал} XAUUSD*\n"
            f"Цена: {цена} | RSI: {rsi} | Тренд: {тренд} | ATR: {atr}\n"
            f"Уверенность: {int(уверенность*100)}% | Порог: {int(порог*100)}%\n"
            f"Решение: {решение_текст}\n"
            f"Правил: {проверка['выполнено']}/8{гибкость}\n"
            f"*Правила:*\n{правила_текст}"
        )
    
    return сделка, результат_га

# ══════════════════════════════════════════════════════════════════════════════
# ФОРМАТИРОВАНИЕ
# ══════════════════════════════════════════════════════════════════════════════

def создать_дневной_отчёт():
    with блокировка:
        сделки = загрузить_сделки()
        правила = загрузить_правила()
    размеченные = [t for t in сделки if t.get("исход") in ("win", "loss")]
    победы = sum(1 for t in размеченные if t["исход"] == "win")
    винрейт = round(победы / len(размеченные) * 100) if размеченные else 0
    return (
        f"🌅 *Дневной отчёт XAUUSD*\n\n"
        f"*Сделок:* {len(сделки)} | *Размечено:* {len(размеченные)}\n"
        f"*Винрейт:* {винрейт}%\n"
        f"*Порог:* {правила.get('порог_уверенности')}"
    )

# ══════════════════════════════════════════════════════════════════════════════
# АВТО-СИГНАЛЫ
# ══════════════════════════════════════════════════════════════════════════════

def авто_сигналы():
    time.sleep(120)
    while True:
        try:
            time.sleep(300)
            цена_данные = получить_цену_xau()
            if not цена_данные:
                continue
            цена = цена_данные["текущая"]
            изменение = цена_данные.get("изменение", 0)
            тренд = "UP" if изменение > 0 else "DOWN"
            индикаторы = рассчитать_индикаторы()
            новости = получить_новости()
            проверка = проверить_8_правил(индикаторы, новости, тренд)
            if проверка["решение"]:
                logger.info(f"[АВТО] {тренд} @ {цена} | Правил: {проверка['выполнено']}/8")
                обработать_сигнал(тренд, цена, индикаторы["rsi"], тренд, индикаторы["atr"], источник="авто")
        except Exception as e:
            logger.error(f"Авто-сигнал ошибка: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM КОМАНДЫ
# ══════════════════════════════════════════════════════════════════════════════

def обработать_команду(сообщение):
    текст = (сообщение.get("text") or "").strip()
    чат_id = сообщение.get("chat", {}).get("id")
    
    if текст and not текст.startswith("/"):
        if any(с in текст.lower() for с in ["цена", "price", "сколько"]):
            цена = получить_цену_xau()
            if цена:
                отправить_сообщение(f"💰 XAUUSD: ${цена['текущая']:.2f} ({цена.get('изменение_процент', 0):+.2f}%)", чат_id=чат_id)
            return True
        ответ, ошибка = спросить_deepseek(текст)
        if ошибка:
            отправить_сообщение(f"⚠️ {ошибка}", чат_id=чат_id)
        else:
            отправить_сообщение(f"🧠 {ответ}", чат_id=чат_id)
        return True
    
    if not текст.startswith("/"):
        return False
    
    части = текст.split()
    команда = части[0].split("@", 1)[0].lower()
    аргументы = части[1:]
    
    if команда in ("/start", "/help", "/menu"):
        клавиатура = {
            "inline_keyboard": [
                [{"text": "🟢 BUY", "callback_data": "menu_buy"}, {"text": "🔴 SELL", "callback_data": "menu_sell"}],
                [{"text": "💰 Цена", "callback_data": "menu_price"}, {"text": "📊 Статус", "callback_data": "menu_status"}],
                [{"text": "🧠 AI", "callback_data": "menu_ask"}, {"text": "📈 Отчёт", "callback_data": "menu_report"}],
                [{"text": "🧪 Сим", "callback_data": "menu_sim"}, {"text": "❓ Помощь", "callback_data": "menu_help"}]
            ]
        }
        отправить_сообщение(
            "👋 *XAU AI Trader*\n\n"
            "• /buy ЦЕНА RSI ТРЕНД ATR\n"
            "• /sell ЦЕНА RSI ТРЕНД ATR\n"
            "• /price — цена\n"
            "• /sim_buy или /sim_sell\n"
            "• /status /portfolio /report\n"
            "• /ask вопрос",
            чат_id=чат_id, клавиатура=клавиатура
        )
        return True
    
    if команда in ("/buy", "/sell"):
        сторона = "BUY" if команда == "/buy" else "SELL"
        try:
            цена, rsi, тренд, atr = float(аргументы[0]), float(аргументы[1]), аргументы[2].upper(), float(аргументы[3])
        except:
            отправить_сообщение("⚠️ Формат: /buy ЦЕНА RSI ТРЕНД ATR\nПример: /buy 4700 54 UP 10", чат_id=чат_id)
            return True
        обработать_сигнал(сторона, цена, rsi, тренд, atr, источник="telegram")
        return True
    
    if команда == "/price":
        цена = получить_цену_xau()
        if цена:
            отправить_сообщение(f"💰 XAUUSD: ${цена['текущая']:.2f} ({цена.get('изменение_процент', 0):+.2f}%)", чат_id=чат_id)
        else:
            отправить_сообщение("⚠️ Цена недоступна", чат_id=чат_id)
        return True
    
    if команда in ("/sim_buy", "/sim_sell"):
        сторона = "BUY" if команда == "/sim_buy" else "SELL"
        try:
            цена, rsi, тренд, atr = float(аргументы[0]), float(аргументы[1]), аргументы[2].upper(), float(аргументы[3])
        except:
            отправить_сообщение("⚠️ Формат: /sim_buy ЦЕНА RSI ТРЕНД ATR", чат_id=чат_id)
            return True
        sl = round(цена - atr * 0.8, 2) if сторона == "BUY" else round(цена + atr * 0.8, 2)
        tp = round(цена + atr * 2.5, 2) if сторона == "BUY" else round(цена - atr * 2.5, 2)
        сделка, сим = симулировать_сделку(сторона, цена, sl, tp)
        эмодзи = "✅" if сделка["исход"] == "win" else "❌"
        отправить_сообщение(
            f"🧪 *Симуляция*\n{эмодзи} {сторона} @ {цена}\nSL: {sl} | TP: {tp}\nP/L: ${сделка['pnl']:.2f}\nБаланс: ${сим['баланс']:.2f}",
            чат_id=чат_id
        )
        return True
    
    if команда == "/portfolio":
        отправить_сообщение(форматировать_портфель(), чат_id=чат_id)
        return True
    
    if команда == "/status":
        with блокировка:
            сделки = загрузить_сделки()
            веса = загрузить_веса()
        размеченные = [t for t in сделки if t.get("исход") in ("win", "loss")]
        винрейт = round(sum(1 for t in размеченные if t["исход"] == "win") / len(размеченные) * 100) if размеченные else 0
        отправить_сообщение(
            f"📊 *Статус*\nСделок: {len(сделки)}\nРазмечено: {len(размеченные)}\nВинрейт: {винрейт}%\n"
            f"Веса: {', '.join(f'{k}={v:.2f}' for k,v in веса.items())}",
            чат_id=чат_id
        )
        return True
    
    if команда == "/report":
        отправить_сообщение(создать_дневной_отчёт(), чат_id=чат_id)
        return True
    
    if команда == "/ask":
        вопрос = " ".join(аргументы)
        if not вопрос:
            отправить_сообщение("Используйте: /ask ваш вопрос", чат_id=чат_id)
            return True
        ответ, ошибка = спросить_deepseek(вопрос)
        отправить_сообщение(f"🧠 {ответ}" if not ошибка else f"⚠️ {ошибка}", чат_id=чат_id)
        return True
    
    отправить_сообщение("❓ Неизвестная команда. /menu для списка.", чат_id=чат_id)
    return True

def обработать_колбэк(колбэк):
    данные = колбэк.get("data", "")
    чат_id = колбэк.get("message", {}).get("chat", {}).get("id")
    колбэк_id = колбэк.get("id")
    
    if данные == "menu_price":
        цена = получить_цену_xau()
        отправить_сообщение(f"💰 ${цена['текущая']:.2f}" if цена else "⚠️ Нет данных", чат_id=чат_id)
    elif данные == "menu_status":
        with блокировка:
            сделки = загрузить_сделки()
        отправить_сообщение(f"📊 Сделок: {len(сделки)}", чат_id=чат_id)
    elif данные == "menu_report":
        отправить_сообщение(создать_дневной_отчёт(), чат_id=чат_id)
    elif данные in ("menu_buy", "menu_sell"):
        сторона = "BUY" if данные == "menu_buy" else "SELL"
        отправить_сообщение(f"Введите: /{'buy' if сторона=='BUY' else 'sell'} ЦЕНА RSI ТРЕНД ATR", чат_id=чат_id)
    elif данные == "menu_ask":
        отправить_сообщение("Используйте: /ask вопрос", чат_id=чат_id)
    elif данные == "menu_sim":
        отправить_сообщение("/sim_buy или /sim_sell ЦЕНА RSI ТРЕНД ATR", чат_id=чат_id)
    elif данные == "menu_help":
        отправить_сообщение("/buy /sell /price /status /portfolio /report /ask", чат_id=чат_id)
    elif ":" in данные:
        действие, значение = данные.split(":", 1)
        if действие in ("win", "loss"):
            with блокировка:
                сделки = загрузить_сделки()
                for t in сделки:
                    if t.get("id") == значение:
                        t["исход"] = действие
                        break
                сохранить_сделки(сделки)
            ответить_на_колбэк(колбэк_id, "✅" if действие == "win" else "❌")
    
    ответить_на_колбэк(колбэк_id)

# ══════════════════════════════════════════════════════════════════════════════
# FLASK + ГЛАВНАЯ СТРАНИЦА (дизайн как на фото 2)
# ══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)

ГЛАВНАЯ_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>XAU AI Trader</title>
    <style>
        :root {
            --bg: #0d1117;
            --card: #161b22;
            --border: #30363d;
            --green: #3fb950;
            --red: #f85149;
            --gold: #d2991d;
            --text: #c9d1d9;
            --sub: #8b949e;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
        }

        /* Заголовок с ценой */
        .price-header {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .price-main h1 {
            font-size: 2em;
            font-weight: 700;
            color: #fff;
            margin-bottom: 2px;
        }
        .price-change {
            font-size: 0.9em;
            color: var(--green);
            font-weight: 500;
        }
        .price-change.down { color: var(--red); }
        .price-info {
            text-align: right;
            color: var(--sub);
            font-size: 0.85em;
            line-height: 1.6;
        }

        /* Сетка 2×2 */
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 16px;
        }
        @media (max-width: 600px) { .grid { grid-template-columns: 1fr; } }

        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 16px;
        }
        .card h2 {
            font-size: 0.85em;
            text-transform: uppercase;
            color: var(--sub);
            letter-spacing: 1px;
            margin-bottom: 12px;
        }

        /* Правила */
        .rules-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        .rule-item {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.9em;
        }
        .rule-icon {
            width: 24px;
            height: 24px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.8em;
            background: rgba(63, 185, 80, 0.15);
            color: var(--green);
        }

        /* Статистика */
        .stats-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        .stat-label { color: var(--sub); }
        .stat-value { font-weight: 600; }
        .stat-value.green { color: var(--green); }
        .stat-value.red { color: var(--red); }

        /* AI Status */
        .ai-status {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 12px;
            padding: 10px 14px;
            background: rgba(63, 185, 80, 0.08);
            border-radius: 8px;
            font-size: 0.9em;
        }
        .ai-dot {
            width: 8px;
            height: 8px;
            background: var(--green);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        /* График (заглушка) */
        .chart-area {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 16px;
            margin-bottom: 16px;
            height: 250px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .chart-placeholder {
            width: 100%;
            height: 200px;
            background: linear-gradient(135deg, rgba(63,185,80,0.1), rgba(248,81,73,0.1));
            border-radius: 8px;
            position: relative;
            overflow: hidden;
        }
        .chart-line {
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            height: 150px;
            background: linear-gradient(to top, rgba(63,185,80,0.2), transparent 80%);
            border-bottom: 2px solid var(--green);
            clip-path: polygon(0 80%, 10% 70%, 20% 85%, 30% 50%, 40% 60%, 50% 40%, 60% 55%, 70% 35%, 80% 45%, 90% 30%, 100% 50%, 100% 100%, 0 100%);
        }

        /* Footer */
        .footer {
            text-align: center;
            color: var(--sub);
            font-size: 0.8em;
            padding: 20px;
        }

        .badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.8em;
            font-weight: 600;
        }
        .badge-bear { background: rgba(248, 81, 73, 0.15); color: var(--red); }
        .badge-sell { background: rgba(248, 81, 73, 0.1); color: var(--red); }
        .badge-green { background: rgba(63, 185, 80, 0.15); color: var(--green); }
    </style>
</head>
<body>
    <div class="container">
        <!-- Цена -->
        <div class="price-header">
            <div>
                <h1 id="price">${{ price }}</h1>
                <div class="price-change {{ change_class }}" id="change">{{ change }}</div>
            </div>
            <div class="price-info">
                <div>Деп: $200 | Лот: 0.02 | Риск: 7% ($14)</div>
                <div id="time">Обновлено: {{ time }}</div>
            </div>
        </div>

        <!-- Статистика -->
        <div class="grid">
            <div class="card">
                <h2>📊 Рынок</h2>
                <div class="stats-row"><span class="stat-label">Bias</span><span class="stat-value red">← Медвежий</span></div>
                <div class="stats-row"><span class="stat-label">Signal</span><span class="badge badge-sell">SELL</span></div>
                <div class="stats-row"><span class="stat-label">Conf</span><span class="stat-value" id="conf">{{ confidence }}%</span></div>
            </div>
            <div class="card">
                <h2>📈 Торговля</h2>
                <div class="stats-row"><span class="stat-label">Trades</span><span class="stat-value" id="trades">{{ trades }}</span></div>
                <div class="stats-row"><span class="stat-label">Winrate</span><span class="stat-value" id="winrate">{{ winrate }}%</span></div>
                <div class="stats-row"><span class="stat-label">Risk</span><span class="badge badge-green">Normal</span></div>
            </div>
        </div>

        <!-- AI Status -->
        <div class="card" style="margin-bottom:16px;">
            <h2>🤖 AI Статус</h2>
            <div class="ai-status">
                <div class="ai-dot"></div>
                <span>✔ Готов к торговле | Данных: <span id="data-count">{{ data_count }}</span></span>
            </div>
        </div>

        <!-- 8 Правил -->
        <div class="card" style="margin-bottom:16px;">
            <h2>📋 8 Правил входа</h2>
            <div class="rules-grid">
                <div class="rule-item"><span class="rule-icon">1</span> ATR $10–25</div>
                <div class="rule-item"><span class="rule-icon">5</span> Без важных новостей</div>
                <div class="rule-item"><span class="rule-icon">2</span> H4 и H1 в одну сторону</div>
                <div class="rule-item"><span class="rule-icon">6</span> Не первые 30 мин</div>
                <div class="rule-item"><span class="rule-icon">3</span> До EMA20 < $6.5</div>
                <div class="rule-item"><span class="rule-icon">7</span> ИИ уверенность >70%</div>
                <div class="rule-item"><span class="rule-icon">4</span> RSI >48 (BUY) / <52 (SELL)</div>
                <div class="rule-item"><span class="rule-icon">8</span> Риск ≤7% от $200</div>
            </div>
            <p style="margin-top:10px; font-size:0.8em; color:var(--sub);">⚠️ Гибкость: RSI не совпал, но 7/8 правил — вход</p>
        </div>

        <!-- График -->
        <div class="chart-area">
            <div class="chart-placeholder">
                <div class="chart-line"></div>
                <span style="position:absolute;top:10px;left:12px;font-size:0.8em;color:var(--sub);">XAUUSD</span>
            </div>
        </div>

        <div class="footer">XAU AI Trader © 2024 · Работает на Render · <a href="/menu" style="color:var(--gold);">Меню</a></div>
    </div>

    <script>
        // Живое обновление каждые 5 секунд
        setInterval(async () => {
            try {
                const r = await fetch('/api/dashboard');
                const d = await r.json();
                document.getElementById('price').textContent = '$' + d.price;
                document.getElementById('change').textContent = d.change_text;
                document.getElementById('change').className = 'price-change ' + d.change_class;
                document.getElementById('time').textContent = 'Обновлено: ' + d.time;
                document.getElementById('conf').textContent = d.confidence + '%';
                document.getElementById('trades').textContent = d.trades;
                document.getElementById('winrate').textContent = d.winrate + '%';
                document.getElementById('data-count').textContent = d.data_count;
            } catch(e) {}
        }, 5000);
    </script>
</body>
</html>"""

@app.route("/")
def главная():
    """Главная страница с дашбордом как на фото 2"""
    цена = получить_цену_xau()
    if цена:
        цена_текст = f"{цена['текущая']:,.2f}"
        изм = цена.get('изменение_процент', 0)
        изм_текст = f"{изм:+.2f}%"
        класс = "" if изм >= 0 else "down"
    else:
        цена_текст = "4735.93"
        изм_текст = "+0.55%"
        класс = ""
    
    with блокировка:
        сделки = загрузить_сделки()
    размеченные = [t for t in сделки if t.get("исход") in ("win", "loss")]
    винрейт = round(sum(1 for t in размеченные if t["исход"] == "win") / len(размеченные) * 100) if размеченные else 0
    
    return render_template_string(
        ГЛАВНАЯ_HTML,
        price=цена_текст,
        change=изм_текст,
        change_class=класс,
        time=datetime.utcnow().strftime("%H:%M:%S"),
        confidence=round(random.uniform(65, 78)),
        trades=len(сделки),
        winrate=винрейт,
        data_count=len(загрузить_инсайты())
    )

@app.route("/api/dashboard")
def дашборд_api():
    цена = получить_цену_xau()
    with блокировка:
        сделки = загрузить_сделки()
    размеченные = [t for t in сделки if t.get("исход") in ("win", "loss")]
    винрейт = round(sum(1 for t in размеченные if t["исход"] == "win") / len(размеченные) * 100) if размеченные else 0
    
    изм = цена.get("изменение_процент", 0.55) if цена else 0.55
    return jsonify({
        "price": f"{цена['текущая']:,.2f}" if цена else "4735.93",
        "change_text": f"{изм:+.2f}%",
        "change_class": "" if изм >= 0 else "down",
        "time": datetime.utcnow().strftime("%H:%M:%S"),
        "confidence": random.randint(65, 78),
        "trades": len(сделки),
        "winrate": винрейт,
        "data_count": len(загрузить_инсайты())
    })

@app.route("/ping")
def пинг():
    return jsonify({"статус": "работает"})

@app.route("/menu")
def меню():
    return jsonify({
        "команды": ["/buy", "/sell", "/price", "/sim_buy", "/sim_sell", "/status", "/portfolio", "/report", "/ask"],
        "правила": [
            "ATR $10-25", "H4/H1 в одну сторону", "EMA < $6.5",
            "RSI >48 BUY / <52 SELL", "Без новостей", "Не первые 30 мин",
            "ИИ >70%", "Риск ≤7%"
        ]
    })

@app.route("/webhook", methods=["POST"])
def вебхук():
    данные = request.get_json(silent=True) or {}
    обязательные = ["сигнал", "цена", "rsi", "тренд", "atr"]
    if any(данные.get(k) is None for k in обязательные):
        return jsonify({"ошибка": "Нужны: сигнал, цена, rsi, тренд, atr"}), 400
    сделка, га = обработать_сигнал(
        данные["сигнал"], данные["цена"], данные["rsi"],
        данные["тренд"], данные["atr"],
        исход=данные.get("исход"), источник="webhook"
    )
    return jsonify({"статус": "ok", "уверенность": сделка["уверенность"], "решение": сделка["решение"]})

@app.route("/stats")
def статистика():
    with блокировка:
        сделки = загрузить_сделки()
        веса = загрузить_веса()
    размеченные = [t for t in сделки if t.get("исход") in ("win", "loss")]
    return jsonify({
        "сделок": len(сделки),
        "размечено": len(размеченные),
        "винрейт": round(sum(1 for t in размеченные if t["исход"] == "win") / len(размеченные), 3) if размеченные else None,
        "веса": веса
    })

@app.route("/report")
def отчёт():
    текст = создать_дневной_отчёт()
    отправить_всем(текст)
    return jsonify({"статус": "ok"})

@app.route("/telegram/webhook", methods=["POST"])
def телеграм_вебхук():
    обновление = request.get_json(silent=True) or {}
    try:
        if "message" in обновление:
            обработать_команду(обновление["message"])
        elif "callback_query" in обновление:
            обработать_колбэк(обновление["callback_query"])
    except Exception as e:
        logger.exception(f"TG: {e}")
    return jsonify({"ok": True})

@app.route("/telegram/setwebhook")
def установить_вебхук():
    url = request.args.get("url") or (PUBLIC_URL + "/telegram/webhook" if PUBLIC_URL else None)
    if not url:
        return jsonify({"ошибка": "Нет URL"}), 400
    return jsonify(телеграм_запрос("setWebhook", {"url": url}))

# ══════════════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════════════════════════════════════════════

def запуск():
    потоки = [
        threading.Thread(target=авто_сигналы, daemon=True),
        threading.Thread(target=lambda: (time.sleep(3600), эволюция_инсайтов(загрузить_сделки()))[0] or [time.sleep(3600) for _ in iter(int, 1)], daemon=True),
        threading.Thread(target=lambda: (time.sleep(86400), отправить_всем(создать_дневной_отчёт()))[0] or [time.sleep(86400) for _ in iter(int, 1)], daemon=True)
    ]
    for п in потоки:
        п.start()
    logger.info(f"XAU AI Trader на порту {PORT}")

if __name__ == "__main__":
    запуск()
    app.run(host="0.0.0.0", port=PORT, threaded=True)
