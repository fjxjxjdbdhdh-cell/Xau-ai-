import MetaTrader5 as mt5
import time
import threading
import logging

logger = logging.getLogger(__name__)

class MT5Client:
    def __init__(self, login, password, server):
        self.login = login
        self.password = password
        self.server = server
        self.connected = False
        self._lock = threading.Lock()

    def connect(self):
        with self._lock:
            if self.connected:
                return True
            for _ in range(3):
                try:
                    if mt5.initialize(login=self.login, password=self.password, server=self.server):
                        self.connected = True
                        return True
                    mt5.shutdown()
                    time.sleep(2)
                except Exception as e:
                    logger.error(f"MT5: {e}")
                    time.sleep(2)
            return False

    def disconnect(self):
        with self._lock:
            if self.connected:
                mt5.shutdown()
                self.connected = False

    def send_order(self, symbol, order_type, volume, price, sl, tp):
        if not self.connected:
            self.connect()
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 25,
            "magic": 999,
            "comment": "XAU_AI",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result and result.retcode == 10009:
            return {"ticket": result.order, "price": result.price}
        return {"error": str(result.comment) if result else "Нет ответа"}

class MT5Manager:
    def __init__(self):
        self._clients = {}
        self._lock = threading.Lock()

    def get_client(self, login, password, server):
        key = f"{login}@{server}"
        with self._lock:
            if key not in self._clients:
                c = MT5Client(login, password, server)
                c.connect()
                self._clients[key] = c
            return self._clients[key]

mt5_manager = MT5Manager()
