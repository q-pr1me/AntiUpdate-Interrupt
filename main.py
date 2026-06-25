import os
import sys
import json
import logging
import subprocess
import winreg
import datetime
import time
import uuid
import threading
from pathlib import Path
import requests
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

# =============================================================================
# 1. НАСТРОЙКИ ПУТЕЙ И ПАРАМЕТРЫ ПРИЛОЖЕНИЯ
# =============================================================================
APP_NAME = "AntiUpdateInterrupt"
APP_VERSION = "2.3.0"

if getattr(sys, "frozen", False):
    EXE_DIR = Path(sys.executable).parent
else:
    EXE_DIR = Path(__file__).parent

APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / APP_NAME
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = APP_DATA_DIR / "config.json"
LOG_DIR = APP_DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"
CLIENT_ID_FILE = APP_DATA_DIR / "id" / "client_id.txt"

BAT_FILE = EXE_DIR / "win_upd.bat"

# =============================================================================
# 2. ЛОГИРОВАНИЕ
# =============================================================================
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(APP_NAME)

# =============================================================================
# 3. ТЕЛЕМЕТРИЯ
# =============================================================================
TELEMETRY_URL = "https://script.google.com/macros/s/AKfycbzcUuImkdAUxdXp3IwJS-4HJSjz0687iA_PjNrG2vMUZS2FENPgoNx42SYm9qYMUvOn/exec"

def get_client_id():
    """Получает или создает уникальный ID клиента"""
    CLIENT_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    if CLIENT_ID_FILE.exists():
        try:
            with open(CLIENT_ID_FILE, "r", encoding="utf-8") as f:
                cid = f.read().strip()
                if cid:
                    return cid
        except Exception:
            pass
    
    new_id = str(uuid.uuid4())
    try:
        with open(CLIENT_ID_FILE, "w", encoding="utf-8") as f:
            f.write(new_id)
    except Exception:
        pass
    return new_id

def send_telemetry():
    """Отправляет анонимную статистику"""
    try:
        client_id = get_client_id()
        requests.post(
            TELEMETRY_URL,
            json={
                "client_id": client_id,
                "version": APP_VERSION,
                "os": sys.platform,
                "frozen": getattr(sys, "frozen", False)
            },
            timeout=10
        )
    except Exception:
        pass  # Игнорируем ошибки — статистика не критична

def send_telemetry_async():
    """Запускает отправку телеметрии в отдельном потоке"""
    thread = threading.Thread(target=send_telemetry, daemon=True)
    thread.start()

# =============================================================================
# 4. МЕНЕДЖЕР КОНФИГУРАЦИИ
# =============================================================================
class ConfigManager:
    def __init__(self):
        self.config = {
            "enabled": True,
            "interval_value": 35,
            "interval_unit": "days",
            "last_run_date": None,
            "next_run_date": None,
            "auto_start": False
        }
        self.load()

    def load(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    self.config.update(json.load(f))
            except Exception as e:
                logger.error(f"Ошибка загрузки конфига: {e}")

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=4, default=str)

    def update_timestamps(self):
        today = datetime.date.today()
        delta = self._get_delta(self.config["interval_value"], self.config["interval_unit"])
        self.config["last_run_date"] = today.isoformat()
        self.config["next_run_date"] = (today + delta).isoformat()
        self.save()
        logger.info(f"Даты обновлены. Следующий запуск: {self.config['next_run_date']}")

    @staticmethod
    def _get_delta(val, unit):
        if unit == "minutes": return datetime.timedelta(minutes=val)
        if unit == "hours": return datetime.timedelta(hours=val)
        if unit == "days": return datetime.timedelta(days=val)
        return datetime.timedelta(days=35)

# =============================================================================
# 5. УПРАВЛЕНИЕ АВТОЗАГРУЗКОЙ (РЕЕСТР HKCU)
# =============================================================================
class AutoStartManager:
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
    REG_KEY = APP_NAME

    @staticmethod
    def update(exe_path, enabled):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AutoStartManager.REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    winreg.SetValueEx(key, AutoStartManager.REG_KEY, 0, winreg.REG_SZ, f'"{exe_path}" --silent')
                else:
                    try:
                        winreg.DeleteValue(key, AutoStartManager.REG_KEY)
                    except FileNotFoundError:
                        pass
            return True
        except Exception as e:
            logger.error(f"Ошибка работы с реестром: {e}")
            return False

# =============================================================================
# 6. ЗАПУСК BAT-ФАЙЛА
# =============================================================================
def run_win_upd():
    if not BAT_FILE.exists():
        logger.error(f"Файл win_upd.bat не найден: {BAT_FILE}")
        return False
    try:
        logger.info("🚀 Запуск win_upd.bat...")
        subprocess.run(
            ["cmd.exe", "/c", str(BAT_FILE)],
            cwd=str(EXE_DIR),
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=True,
            timeout=900
        )
        logger.info("✅ win_upd.bat успешно завершён.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Батник завершился с ошибкой (код {e.returncode})")
        return False
    except Exception as e:
        logger.error(f"Ошибка выполнения батника: {e}")
        return False

# =============================================================================
# 7. GUI (НАСТРОЙКИ) — ТЕМА DARKLY
# =============================================================================
class AppGUI(ttk.Window):
    def __init__(self, config: ConfigManager, exe_path: str):
        # ✅ Всегда используем тёмную тему "darkly"
        super().__init__(themename="darkly")
        self.title("AntiUpdate Interrupt")
        self.geometry("480x580")
        self.resizable(False, False)
        self.config = config
        self.exe_path = exe_path
        self._setup_ui()
        self._refresh_ui()

    def _setup_ui(self):
        frm = ttk.Frame(self, padding=20)
        frm.pack(fill="both", expand=True)

        # Статус
        ttk.Label(frm, text="Статус программы:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=5)
        self.var_status = ttk.StringVar()
        ttk.Label(frm, textvariable=self.var_status, bootstyle="info").grid(row=0, column=1, sticky="w", pady=5)

        # Вкл/Выкл
        btn_ctrl = ttk.Frame(frm)
        btn_ctrl.grid(row=1, column=0, columnspan=2, pady=10, sticky="ew")
        self.btn_enable = ttk.Button(btn_ctrl, text="Включить", bootstyle="success", command=lambda: self._toggle(True))
        self.btn_enable.pack(side="left", padx=5, expand=True, fill="x")
        self.btn_disable = ttk.Button(btn_ctrl, text="Выключить", bootstyle="danger", command=lambda: self._toggle(False))
        self.btn_disable.pack(side="left", padx=5, expand=True, fill="x")

        # Автозапуск
        self.var_auto = ttk.BooleanVar()
        ttk.Checkbutton(frm, text="Добавить в автозагрузку Windows", variable=self.var_auto).grid(row=2, column=0, columnspan=2, sticky="w", pady=8)

        # Интервал
        ttk.Label(frm, text="Интервал запуска:", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, sticky="w", pady=10)
        intervals = ["1 минута (тест)", "10 минут (тест)", "1 час (тест)", "35 дней"]
        self.var_interval = ttk.StringVar(value=intervals[-1])
        ttk.Combobox(frm, values=intervals, textvariable=self.var_interval, state="readonly").grid(row=3, column=1, sticky="ew", pady=10)

        # Даты
        ttk.Label(frm, text="Последний запуск:").grid(row=4, column=0, sticky="w", pady=4)
        self.lbl_last = ttk.Label(frm, text="Нет данных", bootstyle="secondary")
        self.lbl_last.grid(row=4, column=1, sticky="w", pady=4)

        ttk.Label(frm, text="Следующий запуск:").grid(row=5, column=0, sticky="w", pady=4)
        self.lbl_next = ttk.Label(frm, text="Нет данных", bootstyle="secondary")
        self.lbl_next.grid(row=5, column=1, sticky="w", pady=4)

        # Действия
        frm_act = ttk.Frame(frm)
        frm_act.grid(row=6, column=0, columnspan=2, pady=20, sticky="ew")
        ttk.Button(frm_act, text="Запустить win_upd.bat сейчас", bootstyle="primary", command=self._run_now).pack(side="left", padx=5, expand=True, fill="x")
        ttk.Button(frm_act, text="Сохранить настройки", bootstyle="success-outline", command=self._save).pack(side="left", padx=5, expand=True, fill="x")

        frm.columnconfigure(1, weight=1)

    def _toggle(self, state: bool):
        self.config.config["enabled"] = state
        self.config.save()
        self._refresh_ui()

    def _run_now(self):
        self.config.update_timestamps()
        run_win_upd()
        self._refresh_ui()

    def _save(self):
        sel = self.var_interval.get()
        if "1 минута" in sel: val, unit = 1, "minutes"
        elif "10 минут" in sel: val, unit = 10, "minutes"
        elif "1 час" in sel: val, unit = 1, "hours"
        else: val, unit = 35, "days"

        self.config.config["interval_value"] = val
        self.config.config["interval_unit"] = unit
        self.config.config["auto_start"] = self.var_auto.get()

        AutoStartManager.update(self.exe_path, self.config.config["auto_start"])
        self.config.save()
        logger.info("Настройки сохранены.")

        if self.config.config["enabled"] and (unit == "minutes" or unit == "hours"):
            logger.info(f"⏳ Короткий интервал ({val} {unit}). Запуск фонового ожидания...")
            subprocess.Popen(
                [sys.executable, sys.argv[0], "--bg-worker"],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            logger.info("🚪 Окно закрывается. Задача выполняется в фоне.")
        else:
            logger.info("🚪 Окно закрывается. Ожидание по расписанию через автозагрузку.")
        
        self.destroy()

    def _refresh_ui(self):
        enabled = self.config.config.get("enabled", False)
        self.var_status.set("ВКЛЮЧЕНО" if enabled else "ВЫКЛЮЧЕНО")
        self.btn_enable.configure(state="disabled" if enabled else "normal")
        self.btn_disable.configure(state="normal" if enabled else "disabled")
        self.var_auto.set(self.config.config.get("auto_start", False))

        fmt = "%d.%m.%Y"
        try:
            last = self.config.config.get("last_run_date")
            self.lbl_last.configure(text=datetime.date.fromisoformat(last).strftime(fmt) if last else "Нет данных")
            nxt = self.config.config.get("next_run_date")
            self.lbl_next.configure(text=datetime.date.fromisoformat(nxt).strftime(fmt) if nxt else "Нет данных")
        except Exception:
            pass

# =============================================================================
# 8. ТОЧКА ВХОДА (MAIN)
# =============================================================================
def main():
    config = ConfigManager()
    exe_path = str(Path(sys.argv[0]).resolve())

    # 📊 Отправка статистики (всегда, без уведомления)
    send_telemetry_async()

    # 1️⃣ ПЕРВЫЙ ЗАПУСК
    if not config.config.get("last_run_date"):
        logger.info("🌟 Первый запуск. Выполнение батника...")
        run_win_upd()
        config.update_timestamps()
        logger.info("✅ Первый запуск завершён. Приложение закроется.")
        sys.exit(0)

    # 2️⃣ ФОНОВЫЙ РАБОЧИЙ ПРОЦЕСС (минуты/часы)
    if "--bg-worker" in sys.argv:
        if config.config.get("enabled"):
            val = config.config["interval_value"]
            unit = config.config["interval_unit"]
            delta = config._get_delta(val, unit)
            target = datetime.datetime.now() + delta

            logger.info(f"💤 Фоновый режим: ожидание до {target.strftime('%H:%M:%S')}...")
            while datetime.datetime.now() < target:
                time.sleep(30)
            
            logger.info("⏰ Время вышло. Запуск батника...")
            run_win_upd()
            config.update_timestamps()
        else:
            logger.info("⛔ Приложение отключено. Фоновый процесс завершён.")
        sys.exit(0)

    # 3️⃣ АВТОЗАГРУЗКА (ТИХИЙ РЕЖИМ `--silent`)
    if "--silent" in sys.argv:
        if not config.config.get("enabled"):
            logger.info("⛔ Автозапуск: приложение отключено. Выход.")
            sys.exit(0)
        
        next_date_str = config.config.get("next_run_date")
        if next_date_str:
            try:
                next_date = datetime.date.fromisoformat(next_date_str)
                today = datetime.date.today()
                
                if today >= next_date:
                    logger.info(f"🔄 Автозапуск: Дата запуска ({next_date}) наступила. Запуск батника...")
                    run_win_upd()
                    config.update_timestamps()
                else:
                    logger.info(f"⏳ Автозапуск: До даты запуска ({next_date}) ещё далеко. Сегодня {today}. Выход.")
            except Exception as e:
                logger.error(f"Ошибка проверки даты: {e}")
        else:
            logger.warning("Дата следующего запуска не установлена. Запуск батника для безопасности...")
            run_win_upd()
            config.update_timestamps()
            
        sys.exit(0)

    # 4️⃣ РУЧНОЙ ЗАПУСК (GUI)
    logger.info("🖥️ Ручной запуск. Открытие окна настроек...")
    app = AppGUI(config, exe_path)
    app.mainloop()

if __name__ == "__main__":
    main()