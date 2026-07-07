import base64
import sys
import re
import subprocess
import streamlit as st
import pandas as pd
import requests
import time
import os
import json
import random

BASE_DIR = os.path.dirname(os.path.realpath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")
WALLETS_FILE = os.path.join(BASE_DIR, "data", "wallets.txt")
from concurrent.futures import ThreadPoolExecutor, as_completed
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from datetime import datetime, time as dt_time, timedelta
from streamlit_autorefresh import st_autorefresh
from dotenv import load_dotenv
from fake_useragent import UserAgent

load_dotenv(ENV_FILE)

def _now():
    return datetime.utcnow() + timedelta(hours=3)

st.markdown("""
<style>
    [data-testid="stApp"] {
        background: transparent !important;
    }
    .main .block-container {
        position: relative;
        z-index: 1;
    }
    section[data-testid="stSidebar"] {
        background-color: #101618 !important;
        position: relative;
        z-index: 1;
    }
    section[data-testid="stSidebar"] [data-testid="stMetricLabel"] {
        font-size: 0.95rem !important;
    }
    button[kind="primary"] {
        border-radius: 59px !important;
    }
    .seekertable tbody tr:hover {
        background-color: rgba(168,186,204,0.5) !important;
    }
    .seekertable td:first-child {
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

try:
    if st.query_params.get("hide_bg_video") == "true":
        st.session_state.hide_bg_video = True
    for k in st.query_params:
        if k.startswith("th_"):
            try:
                setattr(st.session_state, k, float(st.query_params[k]))
            except (ValueError, TypeError):
                pass
    if "row_bg" in st.query_params:
        st.session_state.row_bg = st.query_params["row_bg"]
    if "row_tx" in st.query_params:
        st.session_state.row_tx = st.query_params["row_tx"]
except Exception as e:
    print(f"⚠️ Ошибка загрузки настроек из URL: {e}", file=sys.stderr)

if not st.session_state.get("hide_bg_video"):
    try:
        st.markdown(
            '<video class="bg-video" autoplay muted loop playsinline webkit-playsinline oncontextmenu="return false">'
            '<source src="https://raw.githubusercontent.com/iFlash04/felaviro/main/media/bg.mp4" type="video/mp4">'
            '</video>',
            unsafe_allow_html=True,
        )
    except Exception as e:
        print(f"⚠️ Ошибка загрузки видео: {e}", file=sys.stderr)
    st.markdown(
        """
<style>
    video.bg-video {
        position: fixed !important;
        top: 0 !important; left: 0 !important;
        width: 100% !important; height: 100% !important;
        min-width: 100vw !important; min-height: 100vh !important;
        object-fit: cover !important;
        z-index: -1 !important;
        pointer-events: none !important;
        opacity: 0.25;
    }
    [data-testid="stAppViewContainer"] {
        overflow: hidden !important;
    }
    ::-webkit-scrollbar { display: none !important; }
    * { scrollbar-width: none !important; }
</style>
""",
        unsafe_allow_html=True,
    )

def check_first_run():
    try:
        if st.secrets.get("helius_api_key") and st.secrets.get("wallets"):
            return False
    except Exception:
        pass
    has_env = os.path.exists(ENV_FILE)
    api_key = os.getenv("HELIUS_API_KEY")
    has_wallets = os.path.exists(WALLETS_FILE)
    if has_wallets:
        with open(WALLETS_FILE, "r") as f:
            has_wallets = bool(f.read().strip())
    return not (has_env and api_key and has_wallets)

def setup_form():
    st.title("🚀 Первая настройка")
    st.markdown("Добро пожаловать! Введите данные для настройки.")

    with st.form("setup_form"):
        api_key = st.text_input("🔑 Helius API Key", type="password", help="Получить на https://dashboard.helius.dev")
        wallets = st.text_area("📋 Список кошельков", height=200, help="Один адрес на строку", placeholder="Addr1...\nAddr2...\nAddr3...")

        submit = st.form_submit_button("💾 Сохранить и запустить")

        if submit:
            if not api_key:
                st.error("❌ Введите API Key!")
            elif not wallets.strip():
                st.error("❌ Введите хотя бы один кошелек!")
            else:
                env_content = f"""# Environment Variables
HELIUS_API_KEY={api_key}
RPC_URL=https://mainnet.helius-rpc.com
"""
                with open(ENV_FILE, "w") as f:
                    f.write(env_content)

                with open(WALLETS_FILE, "w") as f:
                    valid = 0
                    invalid = 0
                    base58_pattern = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
                    for line in wallets.strip().split("\n"):
                        addr = line.strip()
                        if base58_pattern.match(addr):
                            f.write(addr + "\n")
                            valid += 1
                        elif addr:
                            invalid += 1
                    if invalid:
                        st.warning(f"⚠️ Пропущено невалидных адресов: {invalid}")

                st.success(f"✅ Сохранено! {valid} кошельков добавлено.")
                st.rerun()

    st.info("📖 После сохранения создастся файл .env и wallets.txt")
    return True

if check_first_run():
    setup_form()
    st.stop()

_API_KEY = None
try:
    _API_KEY = st.secrets.get("helius_api_key") or os.getenv("HELIUS_API_KEY")
    _RPC_BASE = st.secrets.get("rpc_url") or os.getenv("RPC_URL", "https://mainnet.helius-rpc.com")
except Exception:
    _API_KEY = os.getenv("HELIUS_API_KEY")
    _RPC_BASE = os.getenv("RPC_URL", "https://mainnet.helius-rpc.com")
RPC_URL = f"{_RPC_BASE}/?api-key={_API_KEY}"
SKR_MINT = "SKRbvo6Gf7GondiT3BbTfuRDPqLWei4j2Qy2NPGZhW3"
SKR_STAKING_PROGRAM = "SKRskrmtL83pcL4YqLWt6iPefDqwXQWHSw9S9vz94BZ"
DATA_FILE = os.path.join(BASE_DIR, "data", "farm_data.json")
STATE_FILE = os.path.join(BASE_DIR, "data", "state_txs.json")
UA_FILE = os.path.join(BASE_DIR, "data", "wallet_agents.json")
CONFIG_FILE = os.path.join(BASE_DIR, "data", "config.json")
PRICES_FILE = os.path.join(BASE_DIR, "data", "prices.json")
_price_ua = UserAgent().random

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE) as f:
            _cfg_init = json.load(f)
        if _cfg_init.get("hide_bg_video"):
            st.session_state.hide_bg_video = True
    except Exception as e:
        print(f"⚠️ Ошибка чтения config.json: {e}", file=sys.stderr)

SKR_DIVISOR = 235767466
try:
    SKR_DIVISOR = float(st.secrets.get("skr_divisor", SKR_DIVISOR))
except Exception:
    pass
try:
    if "skr_divisor" in st.query_params:
        SKR_DIVISOR = float(st.query_params["skr_divisor"])
except Exception as e:
    print(f"⚠️ Ошибка чтения skr_divisor из URL: {e}", file=sys.stderr)

client = Client(RPC_URL)

def check_rpc_health():
    try:
        client.get_version()
        return True
    except Exception as e:
        st.error(f"❌ Ошибка подключения к RPC: {e}")
        st.info("Проверьте API ключ в файле .env")
        return False


def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                # Проверяем дату - если новый день, сбрасываем
                if data.get("_date") != _now().strftime("%Y-%m-%d"):
                    return {}
                return data
    except Exception as e:
        print(f"⚠️ [load_state]: {e}", file=sys.stderr)
    return {}

def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        state["_date"] = _now().strftime("%Y-%m-%d")
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        print(f"⚠️ [save_state]: {e}", file=sys.stderr)

def load_agents():
    try:
        if os.path.exists(UA_FILE):
            with open(UA_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️ [load_agents]: {e}", file=sys.stderr)
    return {}

def save_agents(agents):
    try:
        os.makedirs(os.path.dirname(UA_FILE), exist_ok=True)
        with open(UA_FILE, 'w') as f:
            json.dump(agents, f)
    except Exception as e:
        print(f"⚠️ [save_agents]: {e}", file=sys.stderr)

def init_agents(wallets):
    agents = load_agents()
    ua = UserAgent()
    for addr in wallets:
        if addr not in agents:
            agents[addr] = ua.random
    save_agents(agents)
    return agents

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                if data.get("_date") == _now().strftime("%Y-%m-%d"):
                    return data
    except Exception as e:
        print(f"⚠️ Ошибка чтения state_txs.json: {e}", file=sys.stderr)
    return {}

def save_data(data_dict):
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        data_dict["_date"] = _now().strftime("%Y-%m-%d")
        with open(DATA_FILE, 'w') as f:
            json.dump(data_dict, f)
    except Exception as e:
        print(f"⚠️ [save_data]: {e}", file=sys.stderr)

def check_threshold(data):
    state = load_state()
    new_green, new_yellow, new_fire = [], [], []
    t = st.session_state
    for item in data:
        addr = item["wallet"]
        txs = item["txs"]
        old = state.get(addr, 0)
        if old < t.th_badge_green + 1 <= txs:
            new_green.append(addr)
        if old < t.th_badge_yellow + 1 <= txs:
            new_yellow.append(addr)
        if old < t.th_badge_fire + 1 <= txs:
            new_fire.append(addr)
    new_state = {item["wallet"]: item["txs"] for item in data}
    save_state(new_state)
    return set(new_green), set(new_yellow), set(new_fire)

st.set_page_config(page_title="Monitor", layout="wide")
DEFAULTS = {
    "th_sol_low": 0.10, "th_sol_mid": 0.11, "th_sol_high": 0.15, "th_sol_top": 0.20,
    "th_tx_green": 11, "th_tx_yellow": 50, "th_tx_fire": 100,
    "th_badge_green": 10, "th_badge_yellow": 50, "th_badge_fire": 100,
    "th_skr_zero": 0, "th_skr_low": 1000, "th_skr_mid": 10000,
    "th_stakeskr_low": 10000, "th_stakeskr_mid": 20000, "th_stakeskr_high": 30000,
    "th_stakeskr_top": 50000, "th_stakeskr_max": 100000,
    "th_stakesol_low": 0.1, "th_stakesol_mid": 0.5, "th_stakesol_high": 1.0,
}
HARD_DEFAULTS = dict(DEFAULTS)
if "th_sol_low" not in st.session_state:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
            DEFAULTS.update(saved)
        except Exception as e:
            print(f"⚠️ [load DEFAULTS config]: {e}", file=sys.stderr)
    for k, v in DEFAULTS.items():
        setattr(st.session_state, k, v)
saved = load_data()

if not saved and "d" not in st.query_params and not st.session_state.get("refresh_mode") and not st.session_state.get("_first_run_tried"):
    st.session_state._first_run_tried = True
    st.session_state.refresh_mode = "full"
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    st.rerun()

if "_auto_inited" not in st.session_state:
    st.session_state._auto_inited = True
    st.session_state.auto_interval = random.randint(15 * 60 * 1000, 40 * 60 * 1000)
counter = st_autorefresh(interval=st.session_state.auto_interval, key="refresh_key")
if counter > 0 and not st.session_state.get("refresh_mode"):
    if counter != st.session_state.get("_last_auto_counter", 0):
        st.session_state._last_auto_counter = counter
        if st.session_state.get("auto_full", False):
            st.session_state.refresh_mode = "full"
            if os.path.exists(DATA_FILE):
                os.remove(DATA_FILE)
        elif st.session_state.get("auto_refresh", True):
            st.session_state.refresh_mode = "fast"
        else:
            st.session_state.refresh_mode = ""
        if st.session_state.refresh_mode:
            st.session_state.auto_interval = random.randint(15 * 60 * 1000, 40 * 60 * 1000)
            st.rerun()

def get_sol_price():
    try:
        res = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", headers={"User-Agent": _price_ua}, timeout=random.randint(3, 10))
        return float(res.json()['price'])
    except Exception as e:
        print(f"⚠️ Ошибка получения цены SOL: {e}", file=sys.stderr)
        return 0.0

def get_skr_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/token_price/solana"
        params = {"contract_addresses": SKR_MINT, "vs_currencies": "usd"}
        res = requests.get(url, params=params, headers={"User-Agent": _price_ua}, timeout=random.randint(3, 10))
        return float(res.json()[SKR_MINT]["usd"])
    except Exception as e:
        print(f"⚠️ Ошибка получения цены SKR: {e}", file=sys.stderr)
        return 0.0

def _rpc_with_retry(payload, ua_string=None, max_retries=3, delay=0.5):
    ua = ua_string or UserAgent().random
    for attempt in range(max_retries):
        start = time.time()
        try:
            response = requests.post(RPC_URL, json=payload, headers={"User-Agent": ua}, timeout=random.randint(5, 20))
            elapsed = time.time() - start
            log_msg = f"  🌐 RPC: {response.status_code} ({elapsed:.2f}s)"
            print(log_msg, file=sys.stderr)
            if response.status_code == 429:
                print(f"  ⚠️ 429 RATE LIMIT! retry {attempt+1}", file=sys.stderr)
                time.sleep(random.uniform(0.1, 2.5))
                continue
            return response.json()
        except Exception as e:
            elapsed = time.time() - start
            print(f"  ❌ Request failed ({elapsed:.2f}s)", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(random.uniform(0.1, 2.5))
    return None

def get_skr_balance(address, ua_string):
    try:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
                  "params": [address, {"mint": SKR_MINT}, {"encoding": "jsonParsed"}]}
        response = _rpc_with_retry(payload, ua_string)
        if response and "result" in response and response["result"].get("value"):
            return sum(float(x["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]) for x in response["result"]["value"])
    except Exception as e:
        print(f"⚠️ [get_skr_balance]: {e}", file=sys.stderr)
    return 0.0

def get_skr_staked(address, ua_string):
    try:
        filters = [{"memcmp": {"offset": 41, "bytes": address}}]
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getProgramAccounts",
                 "params": [SKR_STAKING_PROGRAM, {"encoding": "base64", "filters": filters}]}
        response = _rpc_with_retry(payload, ua_string)
        if response and "result" in response and response["result"]:
            total_raw = 0
            for acc in response["result"]:
                raw_data = base64.b64decode(acc["account"]["data"][0])
                total_raw += int.from_bytes(raw_data[104:112], "little")
            if total_raw > 0:
                return total_raw / SKR_DIVISOR, total_raw
    except Exception as e:
        print(f"⚠️ Ошибка get_skr_staked({address[:8]}...): {e}", file=sys.stderr)
    return 0.0, 0

def get_data(address, wallet_agents, log_callback=None):
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
    ua = wallet_agents.get(address, UserAgent().random)
    log(f"🔄 {address[:8]}... UA: {ua[:40]}...")
    delay = random.uniform(0.05, 1.5)
    time.sleep(delay)
    log(f"  ⏳ старт (+{delay:.2f}s)")
    sol_bal, skr_bal, stake_sol, skr_staked, txs = 0.0, 0.0, 0.0, 0.0, 0
    try:
        pubkey = Pubkey.from_string(address)
        queries = ['balance', 'sigs', 'skr', 'stake']
        random.shuffle(queries)
        for q in queries:
            if q == 'balance':
                start = time.time()
                sol_bal = 0.0
                for attempt in range(3):
                    try:
                        sol_bal = client.get_balance(pubkey).value / 10**9
                        elapsed = time.time() - start
                        log(f"  🌐 solanaRPC ({elapsed:.2f}s)")
                        break
                    except Exception as e:
                        if attempt < 2:
                            time.sleep(random.uniform(0.5, 2.0))
                            continue
                        elapsed = time.time() - start
                        log(f"  ❌ Error: {e} ({elapsed:.2f}s)")
                delay = random.uniform(0.05, 0.3)
                time.sleep(delay)
                log(f"  ✅ {q}: {sol_bal:.4f} SOL (+{delay:.2f}s)")
            elif q == 'sigs':
                start = time.time()
                sigs = []
                for attempt in range(3):
                    try:
                        sigs = client.get_signatures_for_address(pubkey, limit=random.randint(105, 150)).value
                        elapsed = time.time() - start
                        log(f"  🌐 solanaRPC ({elapsed:.2f}s)")
                        break
                    except Exception as e:
                        if attempt < 2:
                            time.sleep(random.uniform(0.5, 2.0))
                            continue
                        elapsed = time.time() - start
                        log(f"  ❌ Error: {e} ({elapsed:.2f}s)")
                today = datetime.combine(_now().date(), dt_time.min)
                txs = sum(1 for tx in sigs if ((datetime.utcfromtimestamp(tx.block_time) + timedelta(hours=3)) if tx.block_time else _now()) >= today)
                delay = random.uniform(0.05, 0.3)
                time.sleep(delay)
                log(f"  ✅ {q}: {txs} TX (+{delay:.2f}s)")
            elif q == 'skr':
                skr_bal = get_skr_balance(address, ua)
                delay = random.uniform(0.05, 0.3)
                time.sleep(delay)
                log(f"  ✅ {q}: {skr_bal:.2f} SKR (+{delay:.2f}s)")
            elif q == 'stake':
                payload = {"jsonrpc": "2.0", "id": 1, "method": "getProgramAccounts",
                         "params": ["Stake11111111111111111111111111111111111111",
                                  {"encoding": "jsonParsed", "filters": [{"memcmp": {"offset": 12, "bytes": address}}]}]}
                st_res = _rpc_with_retry(payload, ua)
                if st_res and "result" in st_res and st_res["result"]:
                    stake_sol = sum(acc["account"]["lamports"] for acc in st_res["result"]) / 10**9
                    delay = random.uniform(0.05, 0.3)
                    time.sleep(delay)
                    log(f"  ✅ {q}: {stake_sol:.4f} SOL (+{delay:.2f}s)")
        skr_staked, raw_stake_shares = get_skr_staked(address, ua)
        delay = random.uniform(0.05, 0.3)
        time.sleep(delay)
        log(f"  ✅ stake_skr: {skr_staked:.2f} (raw: {raw_stake_shares}) (+{delay:.2f}s)")
        return sol_bal, skr_bal, stake_sol, skr_staked, raw_stake_shares, txs
    except Exception as e:
        log(f"  ❌ Error: {e}")
        return 0.0, 0.0, 0.0, 0.0, 0, 0

def get_txs_only(address, wallet_agents, log_callback=None):
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
    ua = wallet_agents.get(address, UserAgent().random)
    log(f"🔄 {address[:8]}... UA: {ua[:40]}...")
    delay = random.uniform(0.05, 1.5)
    time.sleep(delay)
    log(f"  ⏳ старт (+{delay:.2f}s)")
    try:
        pubkey = Pubkey.from_string(address)
        start = time.time()
        sigs = []
        for attempt in range(3):
            try:
                sigs = client.get_signatures_for_address(pubkey, limit=random.randint(105, 150)).value
                elapsed = time.time() - start
                log(f"  🌐 solanaRPC ({elapsed:.2f}s)")
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(random.uniform(0.5, 2.0))
                    continue
                elapsed = time.time() - start
                log(f"  ❌ Error: {e} ({elapsed:.2f}s)")
        today = datetime.combine(_now().date(), dt_time.min)
        txs = sum(1 for tx in sigs if ((datetime.utcfromtimestamp(tx.block_time) + timedelta(hours=3)) if tx.block_time else _now()) >= today)
        log(f"  ✅ TX: {txs}")
        return txs
    except Exception as e:
        log(f"  ❌ Error: {e}")
        return 0

def get_skr_data(address, wallet_agents, saved, log_callback=None):
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
    ua = wallet_agents.get(address, UserAgent().random)
    log(f"🔄 {address[:8]}... UA: {ua[:40]}...")
    delay = random.uniform(0.05, 1.5)
    time.sleep(delay)
    log(f"  ⏳ старт (+{delay:.2f}s)")
    try:
        skr_bal = get_skr_balance(address, ua)
        delay = random.uniform(0.05, 0.3)
        time.sleep(delay)
        log(f"  ✅ skr: {skr_bal:.2f} SKR (+{delay:.2f}s)")
        skr_staked, raw_stake_shares = get_skr_staked(address, ua)
        delay = random.uniform(0.05, 0.3)
        time.sleep(delay)
        log(f"  ✅ stake_skr: {skr_staked:.2f} (raw: {raw_stake_shares}) (+{delay:.2f}s)")
        old = saved.get(address, {})
        return skr_bal, skr_staked, raw_stake_shares, old.get("SOL", 0), old.get("stake_sol", 0), old.get("txs", 0)
    except Exception as e:
        log(f"  ❌ Error: {e}")
        old = saved.get(address, {})
        return 0.0, 0.0, 0, old.get("SOL", 0), old.get("stake_sol", 0), old.get("txs", 0)

def color_transactions(val):
    t = st.session_state
    if isinstance(val, str):
        val = int(val.split()[0])
    if val == 0:
        return 'background-color: #ff4b4b; color: white'
    elif 1 <= val < t.th_tx_green:
        return 'background-color: #ffa500; color: black'
    elif t.th_tx_green <= val <= t.th_tx_yellow:
        return 'background-color: #ffff00; color: black'
    elif t.th_tx_yellow < val <= t.th_tx_fire:
        return 'background-color: #90ee90; color: black'
    else:
        return 'background-color: #28a745; color: white'

def color_balance(val):
    t = st.session_state
    if val < t.th_sol_low:
        return 'background-color: #600000; color: #ffffff; font-weight: bold'
    elif t.th_sol_low <= val < t.th_sol_mid:
        return 'background-color: #ffa500; color: black'
    elif t.th_sol_mid <= val < t.th_sol_high:
        return 'background-color: #90ee90; color: black'
    elif t.th_sol_high <= val < t.th_sol_top:
        return 'background-color: #28a745; color: white'
    elif val >= t.th_sol_top:
        return 'background-color: #add8e6; color: black; font-weight: bold'
    return ''

def color_stake_skr(val):
    t = st.session_state
    if isinstance(val, str):
        val = float(val.replace(',', ''))
    if val < t.th_stakeskr_low:
        return 'background-color: #ffa500; color: black'
    elif val < t.th_stakeskr_mid:
        return 'background-color: #ffff00; color: black'
    elif val < t.th_stakeskr_high:
        return 'background-color: #90ee90; color: black'
    elif val < t.th_stakeskr_top:
        return 'background-color: #28a745; color: white'
    elif val < t.th_stakeskr_max:
        return 'background-color: #87cefa; color: black'
    else:
        return 'background-color: #4169e1; color: white'

def color_stake_sol(val):
    t = st.session_state
    if isinstance(val, str):
        val = float(val.replace(',', ''))
    if val < t.th_stakesol_low:
        return 'background-color: #ffa500; color: black'
    elif val < t.th_stakesol_mid:
        return 'background-color: #ffff00; color: black'
    elif val < t.th_stakesol_high:
        return 'background-color: #90ee90; color: black'
    else:
        return 'background-color: #28a745; color: white'

def color_skr(val):
    t = st.session_state
    if isinstance(val, str):
        val = float(val.replace(',', ''))
    try:
        val = float(val)
    except (ValueError, TypeError):
        return ''
    if val == t.th_skr_zero:
        return 'background-color: #ffff00; color: black'
    elif val <= t.th_skr_low:
        return 'background-color: #90ee90; color: black'
    elif val <= t.th_skr_mid:
        return 'background-color: #28a745; color: white'
    else:
        return 'background-color: #87cefa; color: black'

st.title("📲")

try:
    if os.path.exists(PRICES_FILE):
        with open(PRICES_FILE) as f:
            pc = json.load(f)
        if not st.session_state.get("last_full"):
            st.session_state.last_full = pc.get("last_full", "")
        if not st.session_state.get("last_fast"):
            st.session_state.last_fast = pc.get("last_fast", "")
        if "cached_sol_price" not in st.session_state:
            st.session_state.cached_sol_price = pc.get("sol", 0) or None
            st.session_state.cached_skr_price = pc.get("skr", 0) or None
except Exception as e:
    print(f"⚠️ [load PRICES_FILE]: {e}", file=sys.stderr)
if not st.session_state.get("cached_sol_price") and "p" in st.query_params:
    try:
        _qp_p = json.loads(st.query_params["p"])
        if not st.session_state.get("last_full"):
            st.session_state.last_full = _qp_p.get("last_full", "")
        if not st.session_state.get("last_fast"):
            st.session_state.last_fast = _qp_p.get("last_fast", "")
        if "cached_sol_price" not in st.session_state:
            st.session_state.cached_sol_price = _qp_p.get("sol", 0) or None
            st.session_state.cached_skr_price = _qp_p.get("skr", 0) or None
    except Exception as e:
        print(f"⚠️ [load query params p]: {e}", file=sys.stderr)

with st.sidebar:
    st.image("media/logo.webp", use_container_width=True)
    st.markdown("<h2 style='text-align:center;margin-bottom:0'>  Панель управления</h2>", unsafe_allow_html=True)
    st.markdown("---")

    def _ago(ts):
        if not ts:
            return None
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
            return (_now() - dt).total_seconds()
        except Exception:
            return None

    def _color(secs):
        if secs is None:
            return "#6b7280"
        if secs < 1800:
            return "#22c55e"
        if secs < 3600:
            return "#eab308"
        return "#ef4444"

    def _rel(secs):
        if secs is None:
            return "—"
        if secs < 60:
            return "только что"
        if secs < 3600:
            return f"{int(secs/60)} мин назад"
        if secs < 86400:
            return f"{int(secs/3600)} ч назад"
        return f"{int(secs/86400)} дн назад"

    if st.button("📡 Полное обновление", type="primary", use_container_width=True):
        st.session_state.refresh_mode = "full"
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
        st.rerun()
    sf = _ago(st.session_state.get("last_full"))
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(
            f'📚 Все данные: <span style="color:{_color(sf)}">{_rel(sf)}</span>',
            unsafe_allow_html=True,
        )
    with c2:
        st.checkbox("Авто", value=st.session_state.get("auto_full", False), key="auto_full",
                    help="Приоритет полного обновления над быстрым")

    if st.button("🔄 Быстрое обновление", type="primary", use_container_width=True):
        st.session_state.refresh_mode = "fast"
        st.rerun()
    ss = _ago(st.session_state.get("last_fast"))
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(
            f'⚡️ TX и цены: <span style="color:{_color(ss)}">{_rel(ss)}</span>',
            unsafe_allow_html=True,
        )
    with c2:
        mins = st.session_state.get("auto_interval", 30*60000) // 60000
        auto_full_on = st.session_state.get("auto_full", False)
        st.checkbox(f"Авто (~{mins} мин)", value=st.session_state.get("auto_refresh", True) and not auto_full_on,
                    key="auto_refresh", disabled=auto_full_on)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔐 Сменить UA", use_container_width=True):
            if os.path.exists(UA_FILE):
                os.remove(UA_FILE)
            st.rerun()
    with c2:
        blurred = st.session_state.get("blur_table", False)
        if st.button("👁️ Скрыть" if not blurred else "👁️ Показать", use_container_width=True):
            st.session_state.blur_table = not blurred
            st.rerun()

    if blurred:
        st.markdown("""
        <style>
            .blurcol { display: none; }
        </style>
        """, unsafe_allow_html=True)

    st.markdown("---")

def is_valid_solana_address(address: str) -> bool:
    try:
        if len(address) < 32 or len(address) > 44:
            return False
        Pubkey.from_string(address)
        return True
    except Exception:
        return False

try:
    wallets = None
    try:
        wallets = st.secrets.get("wallets")
    except Exception:
        pass
    if not wallets:
        with open(WALLETS_FILE, "r") as f:
            raw_wallets = [line.strip().split(":")[-1] for line in f if line.strip()]
        wallets = [addr for addr in raw_wallets if is_valid_solana_address(addr)]
        invalid = set(raw_wallets) - set(wallets)
        if invalid:
            st.warning(f"⚠️ Пропущено невалидных адресов: {len(invalid)}")
    elif not isinstance(wallets, list):
        wallets = [wallets]
except FileNotFoundError:
    st.error("Файл wallets.txt не найден!")
    wallets = []

data = []
total_tx = 0
gas_sol = 0.0
price_val = None
skr_price = None
df = pd.DataFrame()

if wallets:
    wallet_agents = init_agents(wallets)
    saved_data = load_data()
    if not saved_data and "d" in st.query_params:
        try:
            _qp_d = json.loads(st.query_params["d"])
            if isinstance(_qp_d, dict):
                for addr, entry in _qp_d.items():
                    if addr in wallets:
                        sol = entry.get("SOL", 0)
                        skr = entry.get("SKR", 0)
                        stake_skr = entry.get("stake_skr", 0)
                        stake_sol = entry.get("stake_sol", 0)
                        txs = entry.get("txs", 0)
                        prev = entry.get("prev_total", skr + stake_skr)
                        rss = entry.get("raw_stake_shares", 0)
                        saved_data[addr] = {
                            "SOL": sol, "SKR": skr, "stake_skr": stake_skr,
                            "stake_sol": stake_sol, "txs": txs,
                            "prev_total": prev, "raw_stake_shares": rss,
                            "delta_skr": round((skr + stake_skr) - prev, 1),
                            "wallet": addr,
                            "device": f"{wallets.index(addr)+1:02d}",
                        }
        except Exception as e:
            print(f"⚠️ [load query params d]: {e}", file=sys.stderr)
    data = []
    progress_text = st.empty()
    progress_bar = st.progress(0)
    
    refresh_mode = st.session_state.get("refresh_mode", "")
    price = st.session_state.get("cached_sol_price")
    skr_price = st.session_state.get("cached_skr_price")

    if refresh_mode == "full":
        price = get_sol_price()
        skr_price = get_skr_price()
        st.session_state.cached_sol_price = price
        st.session_state.cached_skr_price = skr_price
        try:
            os.makedirs(os.path.dirname(PRICES_FILE), exist_ok=True)
            with open(PRICES_FILE, "w") as f:
                json.dump({"sol": price, "skr": skr_price, "last_full": _now().strftime("%Y-%m-%d %H:%M"), "last_fast": _now().strftime("%Y-%m-%d %H:%M")}, f)
        except Exception as e:
            print(f"⚠️ [save PRICES_FILE full]: {e}", file=sys.stderr)
        if not check_rpc_health():
            st.stop()
        st.caption("📡 Полное обновление данных")
        prev_totals = {}
        for addr in wallets:
            p = saved_data.get(addr, {})
            if p:
                prev_totals[addr] = p.get("prev_total", p.get("SKR", 0) + p.get("stake_skr", 0))
        with st.spinner('📡 Обновление всех данных и их кеширование...'):
            with ThreadPoolExecutor(max_workers=random.randint(1, 4)) as executor:
                futures = {executor.submit(get_data, addr, wallet_agents): (i, addr) for i, addr in enumerate(wallets)}

                completed = 0
                for future in as_completed(futures):
                    completed += 1
                    idx, addr = futures[future]
                    progress_text.text(f'Обработка кошелька {completed} из {len(wallets)}...')
                    progress_bar.progress(int(completed / len(wallets) * 100))

                    s, k, ss, skr_staked, rss, t = future.result()
                    data.append({
                        "wallet": addr,
                        "device": f"{idx+1:02d}",
                        "SOL": s,
                        "SKR": k,
                        "stake_skr": round(skr_staked, 2),
                        "stake_sol": ss,
                        "txs": t,
                        "raw_stake_shares": rss,
                    })

        saved_data = load_data()
        for item in data:
            addr = item["wallet"]
            curr_total = item["SKR"] + item["stake_skr"]
            prev = prev_totals.get(addr, curr_total)
            item["delta_skr"] = round(curr_total - prev, 1)
            item["prev_total"] = curr_total
            saved_data[addr] = item
        save_data(saved_data)
        try:
            st.query_params["d"] = json.dumps({addr: {k: d[k] for k in ("SOL", "SKR", "stake_skr", "stake_sol", "txs", "prev_total", "raw_stake_shares")} for addr, d in saved_data.items()}, default=str)
            st.query_params["p"] = json.dumps({"sol": price, "skr": skr_price, "last_full": _now().strftime("%Y-%m-%d %H:%M"), "last_fast": _now().strftime("%Y-%m-%d %H:%M")})
        except Exception as e:
            print(f"⚠️ [set query params d full]: {e}", file=sys.stderr)
        st.session_state.last_full = _now().strftime("%Y-%m-%d %H:%M")
        st.session_state.last_fast = st.session_state.last_full
    elif refresh_mode == "skr":
        st.session_state.cached_skr_price = skr_price
        st.caption("🔧 Пересчёт SKR и стейкинга")
        with st.spinner('Обновление SKR...'):
            with ThreadPoolExecutor(max_workers=random.randint(1, 4)) as executor:
                futures = {executor.submit(get_skr_data, addr, wallet_agents, saved_data): (i, addr) for i, addr in enumerate(wallets)}

                completed = 0
                for future in as_completed(futures):
                    completed += 1
                    idx, addr = futures[future]
                    progress_text.text(f'SKR {completed} из {len(wallets)}...')
                    progress_bar.progress(int(completed / len(wallets) * 100))

                    k, skr_staked, rss, s, ss, t = future.result()
                    data.append({
                        "wallet": addr,
                        "device": f"{idx+1:02d}",
                        "SOL": s,
                        "SKR": k,
                        "stake_skr": round(skr_staked, 2),
                        "stake_sol": ss,
                        "txs": t,
                        "raw_stake_shares": rss,
                    })

        saved_data = load_data()
        prev_totals = {}
        for addr in wallets:
            p = saved_data.get(addr, {})
            if p:
                prev_totals[addr] = p.get("prev_total", p.get("SKR", 0) + p.get("stake_skr", 0))
        for item in data:
            addr = item["wallet"]
            curr_total = item["SKR"] + item["stake_skr"]
            prev = prev_totals.get(addr, curr_total)
            item["delta_skr"] = round(curr_total - prev, 1)
            item["prev_total"] = curr_total
            saved_data[addr] = item
        save_data(saved_data)
        try:
            st.query_params["d"] = json.dumps({addr: {k: d[k] for k in ("SOL", "SKR", "stake_skr", "stake_sol", "txs", "prev_total", "raw_stake_shares")} for addr, d in saved_data.items()}, default=str)
        except Exception as e:
            print(f"⚠️ [set query params d skr]: {e}", file=sys.stderr)
        st.session_state.last_fast = _now().strftime("%Y-%m-%d %H:%M")
    elif refresh_mode == "fast":
        price = get_sol_price()
        skr_price = get_skr_price()
        st.session_state.cached_sol_price = price
        st.session_state.cached_skr_price = skr_price
        try:
            os.makedirs(os.path.dirname(PRICES_FILE), exist_ok=True)
            with open(PRICES_FILE, "w") as f:
                json.dump({"sol": price, "skr": skr_price, "last_full": st.session_state.get("last_full", ""), "last_fast": _now().strftime("%Y-%m-%d %H:%M")}, f)
            st.query_params["p"] = json.dumps({"sol": price, "skr": skr_price, "last_full": st.session_state.get("last_full", ""), "last_fast": _now().strftime("%Y-%m-%d %H:%M")})
        except Exception as e:
            print(f"⚠️ [save PRICES_FILE fast]: {e}", file=sys.stderr)
        if not check_rpc_health():
            st.stop()
        st.caption("🔄 Режим быстрого обновления (только транзакции)")
        with st.spinner('Проверка транзакций...'):
            with ThreadPoolExecutor(max_workers=random.randint(1, 4)) as executor:
                futures = {executor.submit(get_txs_only, addr, wallet_agents): (i, addr) for i, addr in enumerate(wallets)}

                completed = 0
                for future in as_completed(futures):
                    completed += 1
                    idx, addr = futures[future]
                    progress_text.text(f'Проверка {completed} из {len(wallets)}...')
                    progress_bar.progress(int(completed / len(wallets) * 100))

                    t = future.result()
                    saved = saved_data.get(addr, {})
                    data.append({
                        "wallet": addr,
                        "device": f"{idx+1:02d}",
                        "SOL": saved.get("SOL", 0),
                        "SKR": saved.get("SKR", 0),
                        "stake_skr": saved.get("stake_skr", 0),
                        "stake_sol": saved.get("stake_sol", 0),
                        "txs": t,
                        "raw_stake_shares": saved.get("raw_stake_shares", 0),
                    })

        for item in data:
            if item["wallet"] in saved_data:
                saved_data[item["wallet"]]["txs"] = item["txs"]
        save_data(saved_data)
        st.session_state.last_fast = _now().strftime("%Y-%m-%d %H:%M")
    else:
        data = [saved_data[addr] for addr in wallets if addr in saved_data]

    if refresh_mode:
        st.session_state.refresh_mode = ""
        st.rerun()
    
    data.sort(key=lambda x: int(x["device"]))

    total_tx = sum(item["txs"] for item in data)
    
    new_green_addrs, new_yellow_addrs, new_fire_addrs = check_threshold(data)
    
    for item in data:
        if item["wallet"] in new_fire_addrs:
            item["badge"] = "🔥"
        elif item["wallet"] in new_yellow_addrs:
            item["badge"] = "⭐"
        elif item["wallet"] in new_green_addrs:
            item["badge"] = "🌱"
        else:
            item["badge"] = ""
    
    progress_text.empty()
    progress_bar.empty()
    df = pd.DataFrame(data)
    
    gas_sol = total_tx * 0.000005
    price_val = price if price and price > 0 else None
    gas_usd = gas_sol * price_val if price_val else 0
    
with st.sidebar:
    gas_help = f"${gas_usd:.2f} USD" if price_val else None
    c1, c2 = st.columns(2)
    c1.metric("📊 Всего TX", total_tx)
    c2.metric("💸 Затраты на газ", f"{gas_sol:.6f} SOL", help=gas_help)
def _rgba(style_str):
    if not style_str:
        return ""
    import re as _re
    def _hex_to_rgba(m):
        h = m.group(1)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},0.7)"
    return _re.sub(r'#([0-9a-fA-F]{6})', _hex_to_rgba, style_str)

def _cell_style(style_str):
    return f'style="{style_str}"'

headers = ["device", "wallet", "SOL", "SKR", "stake_skr", "delta_skr", "stake_sol", "txs"]
headers_short = {"wallet": "W", "stake_skr": "st.skr", "delta_skr": "delta", "stake_sol": "st.sol"}
palette = ["#1a2332", "#243447", "#2d4659", "#3a5068", "#4a5c6e", "#5a6d80", "#6b7f94", "#7d91a6", "#8fa3b8", "#a8bacc"]
rows_html = ""
for i, item in enumerate(data):
    cells = ""
    row_color = st.session_state.get("row_bg", "#7d91a6")
    for h in headers:
        val = item.get(h, "")
        if h == "wallet":
            val = val[-3:]
        row_tx_val = st.session_state.get("row_tx", "#000000")
        if h == "device":
            cs = f"background-color: {row_color}; color: {row_tx_val}"
        elif h == "wallet":
            cs = f"background-color: {row_color}; color: {row_tx_val}"
        elif h == "SOL":
            cs = color_balance(val)
        elif h == "SKR":
            cs = color_skr(val)
        elif h == "stake_skr":
            cs = color_stake_skr(val)
        elif h == "stake_sol":
            cs = color_stake_sol(val)
        elif h == "txs":
            cs = color_transactions(val)
            val = f"{val} {item.get('badge', '')}"
        elif h == "delta_skr":
            cs = ""
            try:
                dv = float(val)
                if dv > 0:
                    cs = "background-color: #90ee90; color: black"
                elif dv < 0:
                    cs = "background-color: #ff6b6b; color: black"
            except (ValueError, TypeError):
                pass
        blur_class = ' class="blurcol"' if h not in ("device", "txs") else ""
        cells += f'<td{blur_class} {_cell_style(_rgba(cs)) if cs else ""}>{val}</td>'
    rows_html += f"<tr>{cells}</tr>"

st.markdown(
    f"""
    <table class="seekertable" style="width:100%;border-collapse:separate;border-spacing:0;background:transparent;color:#cfe6e4;overflow:hidden;border-radius:12px;box-shadow:0 0 20px rgba(107,127,148,0.3),0 0 40px rgba(107,127,148,0.1)">
        <thead>
            <tr style="background:rgba(0,0,0,0.4)">{"".join(f'<th class="{"blurcol" if h not in ("device", "txs") else ""}" style="border-radius:{"12px 0 0 0" if i==0 else "0 12px 0 0" if i==len(headers)-1 else "0"};text-align:center;text-transform:uppercase">{headers_short.get(h, h)}</th>' for i, h in enumerate(headers))}</tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
    """,
    unsafe_allow_html=True,
)

if new_fire_addrs:
    try:
        for _ in range(5):
            subprocess.Popen(['afplay', '/System/Library/Sounds/Glass.aiff'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
    except Exception:
        pass
elif new_yellow_addrs:
    try:
        for _ in range(5):
            subprocess.Popen(['afplay', '/System/Library/Sounds/Submarine.aiff'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
    except Exception:
        pass
elif new_green_addrs:
    try:
        for _ in range(5):
            subprocess.Popen(['afplay', '/System/Library/Sounds/Blow.aiff'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
    except Exception:
        pass


with st.sidebar:

    def _enforce_order():
        s = st.session_state
        s.th_sol_mid = max(s.th_sol_mid, s.th_sol_low + 0.01)
        s.th_sol_high = max(s.th_sol_high, s.th_sol_mid + 0.01)
        s.th_sol_top = max(s.th_sol_top, s.th_sol_high + 0.01)
        s.th_tx_yellow = max(s.th_tx_yellow, s.th_tx_green + 1)
        s.th_tx_fire = max(s.th_tx_fire, s.th_tx_yellow + 1)
        s.th_stakeskr_mid = max(s.th_stakeskr_mid, s.th_stakeskr_low + 1000)
        s.th_stakeskr_high = max(s.th_stakeskr_high, s.th_stakeskr_mid + 1000)
        s.th_stakeskr_top = max(s.th_stakeskr_top, s.th_stakeskr_high + 1000)
        s.th_stakeskr_max = max(s.th_stakeskr_max, s.th_stakeskr_top + 1000)
        s.th_stakesol_mid = max(s.th_stakesol_mid, s.th_stakesol_low + 0.1)
        s.th_stakesol_high = max(s.th_stakesol_high, s.th_stakesol_mid + 0.1)
        s.th_skr_mid = max(s.th_skr_mid, s.th_skr_low + 1000)

    def _save_config():
        s = st.session_state
        for k in DEFAULTS:
            if f"wg_{k}" in s:
                s[k] = s[f"wg_{k}"]
        _enforce_order()
        cfg = {}
        for k in DEFAULTS:
            cfg[k] = s[k]
        cfg["hide_bg_video"] = s.get("hide_bg_video", False)
        cfg["row_bg"] = s.get("row_bg", "#7d91a6")
        cfg["row_tx"] = s.get("row_tx", "#000000")
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f)
        try:
            for k, v in cfg.items():
                st.query_params[k] = str(v)
        except Exception as e:
            print(f"⚠️ [set query params config]: {e}", file=sys.stderr)

    lskr = df['SKR'].sum() if 'SKR' in df.columns else 0
    sskr = df['stake_skr'].sum() if 'stake_skr' in df.columns else 0
    lsol = df['SOL'].sum() if 'SOL' in df.columns else 0
    ssol = df['stake_sol'].sum() if 'stake_sol' in df.columns else 0
    total_skr = lskr + sskr
    total_sol = lsol + ssol
    liquid_skr = lskr
    staked_skr = sskr
    liquid_sol = lsol
    staked_sol = ssol
    total_sol_usd = total_sol * price_val if price_val else 0
    total_skr_usd = total_skr * skr_price if skr_price and skr_price > 0 else 0
    liquid_skr_usd = liquid_skr * skr_price if skr_price and skr_price > 0 else 0
    staked_skr_usd = staked_skr * skr_price if skr_price and skr_price > 0 else 0
    liquid_sol_usd = liquid_sol * price_val if price_val else 0
    staked_sol_usd = staked_sol * price_val if price_val else 0

    c1, c2 = st.columns(2)
    skr_usd_help = f"${round(total_skr_usd, 2)}" if skr_price and skr_price > 0 else None
    skr_liq_title = f' title="${round(liquid_skr_usd, 2)}"' if skr_price and skr_price > 0 else ""
    skr_stk_title = f' title="${round(staked_skr_usd, 2)}"' if skr_price and skr_price > 0 else ""
    with c1:
        st.metric("💎 Всего SKR", f"{round(total_skr, 1)}", help=skr_usd_help)
        st.markdown(f"<div style='line-height:1.2;margin-top:-12px'><span{skr_liq_title}>┣ Ликв: {round(liquid_skr, 1)}</span><br><span{skr_stk_title}>┗ Стейк: {round(staked_skr, 1)}</span></div>", unsafe_allow_html=True)

    sol_usd_help = f"${round(total_sol_usd, 2)}" if price_val else None
    sol_liq_title = f' title="${round(liquid_sol_usd, 2)}"' if price_val else ""
    sol_stk_title = f' title="${round(staked_sol_usd, 2)}"' if price_val else ""
    with c2:
        st.metric("🧂 Всего SOL", f"{round(total_sol, 3)}", help=sol_usd_help)
        st.markdown(f"<div style='line-height:1.2;margin-top:-12px'><span{sol_liq_title}>┣ Ликв: {round(liquid_sol, 3)}</span><br><span{sol_stk_title}>┗ Стейк: {round(staked_sol, 3)}</span></div>", unsafe_allow_html=True)

    total_delta = sum(d.get("delta_skr", 0) for d in data)
    if total_delta:
        st.caption("")
        st.metric("📈 Прирост SKR", f"{total_delta:+.1f}")

    st.markdown("---")
    with st.expander("🔐 Управление кошельками", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            new_addr = st.text_input("Добавить", placeholder="Адрес...", key="new_wallet")
            if st.button("➕ Добавить") and new_addr:
                new_addr = new_addr.strip()
                if new_addr in wallets:
                    st.warning("⚠️ Этот адрес уже в списке")
                elif is_valid_solana_address(new_addr):
                    with open(WALLETS_FILE, "a") as f:
                        f.write(new_addr + "\n")
                    st.success(f"✅ {new_addr[:8]}... добавлен")
                    st.session_state.refresh_mode = "full"
                    if os.path.exists(DATA_FILE):
                        os.remove(DATA_FILE)
                    st.rerun()
                else:
                    st.error("❌ Невалидный адрес")
        with c2:
            try:
                _from_secrets = bool(st.secrets.get("wallets"))
            except Exception:
                _from_secrets = False
            if _from_secrets:
                st.caption("☁️ На Cloud редактирование через Secrets")
            else:
                remove_addr = st.selectbox("Удалить", options=[""] + wallets, key="remove_wallet")
                if st.button("➖ Удалить") and remove_addr:
                    with open(WALLETS_FILE, "r") as f:
                        lines = f.readlines()
                    with open(WALLETS_FILE, "w") as f:
                        for line in lines:
                            if line.strip() != remove_addr:
                                f.write(line)
                    st.success(f"✅ {remove_addr[:8]}... удалён")
                    st.session_state.refresh_mode = "full"
                    if os.path.exists(DATA_FILE):
                        os.remove(DATA_FILE)
                    st.rerun()

    raw_first = data[0].get("raw_stake_shares", 0) if data else 0
    if raw_first > 0:
        with st.expander("🔧 Калибровка множителя стейкинга", expanded=False):
            st.caption("Введи точную сумму застейканных SKR для первого кошелька — множитель пересчитается, сохранится в .env и запустит полное обновление")
            default_stake = data[0].get("stake_skr", 0) if data else 0.0
            actual_val = st.number_input("SKR в стейкинге (01)", value=float(default_stake), step=1.0, key="cal_actual")
            _skr_int = int(SKR_DIVISOR)
            st.markdown(
                f'<p style="font-size:0.85rem;color:#6b7280;margin-bottom:8px">'
                f'<a href="https://share.streamlit.io" '
                f'style="color:#3a9e91" target="_blank">Streamlit Cloud → Settings → Secrets</a>'
                f'</p>',
                unsafe_allow_html=True,
            )
            st.code(f"skr_divisor = {_skr_int}", language="toml")
            if actual_val > 0:
                new_div = raw_first / actual_val
                cal_col1, cal_col2 = st.columns([1, 1])
                with cal_col1:
                        st.caption(f"Новый множитель: {new_div:,.0f}")
                with cal_col2:
                    if st.button("💾 Сохранить множитель", use_container_width=True):
                        try:
                            st.query_params["skr_divisor"] = str(int(new_div))
                        except Exception as e:
                            print(f"⚠️ [set query params skr_divisor]: {e}", file=sys.stderr)
                        try:
                            _app_path = os.path.join(BASE_DIR, "app.py")
                            with open(_app_path, "r") as f:
                                _app_code = f.read()
                            _app_code = re.sub(r'SKR_DIVISOR\s*=\s*[\d.]+', f'SKR_DIVISOR = {int(new_div)}', _app_code)
                            with open(_app_path, "w") as f:
                                f.write(_app_code)
                        except Exception as e:
                            print(f"⚠️ [save SKR_DIVISOR to app.py]: {e}", file=sys.stderr)
                        st.toast(f"✅ Множитель: {int(new_div)}. Чтобы работал на всех устройствах, добавь `skr_divisor = {int(new_div)}` в Secrets на share.streamlit.io")
                        st.session_state.refresh_mode = "skr"
                        st.rerun()

    with st.expander("ℹ️ Легенда", expanded=False):

        def _k(v):
            return f"{v/1000:.0f}k" if v >= 1000 else str(int(v))

        edit = st.session_state.get("edit_legend", False)
        t = st.session_state

        if edit:
            _enforce_order()

        if not edit:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.info("**Баланс SOL**")
                st.markdown(f"🔴 < {t.th_sol_low:.2f}<br>🟠 < {t.th_sol_mid:.2f}<br>🟢 < {t.th_sol_high:.2f}<br>🌲 < {t.th_sol_top:.2f}<br>💎 ≥ {t.th_sol_top:.2f}", unsafe_allow_html=True)
            with c2:
                st.info("**Активность**")
                st.markdown(f"🔴 0<br>🟠 1-{t.th_tx_green-1}<br>🟡 {t.th_tx_green}-{t.th_tx_yellow}<br>🟢 {t.th_tx_yellow+1}-{t.th_tx_fire}<br>🌲 >{t.th_tx_fire}", unsafe_allow_html=True)
            with c3:
                st.info("**Бейджи**")
                st.markdown(f"🌱 >{t.th_badge_green} TX<br>⭐ >{t.th_badge_yellow} TX<br>🔥 >{t.th_badge_fire} TX", unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3)
            with c1:
                st.info("**Staked SKR**")
                st.markdown(f"🟠 < {_k(t.th_stakeskr_low)}<br>🟡 < {_k(t.th_stakeskr_mid)}<br>🟢 < {_k(t.th_stakeskr_high)}<br>🌲 < {_k(t.th_stakeskr_top)}<br>🔵 < {_k(t.th_stakeskr_max)}<br>💎 ≥ {_k(t.th_stakeskr_max)}", unsafe_allow_html=True)
            with c2:
                st.info("**Staked SOL**")
                st.markdown(f"🟠 < {t.th_stakesol_low:.1f}<br>🟡 < {t.th_stakesol_mid:.1f}<br>🟢 < {t.th_stakesol_high:.1f}<br>🌲 ≥ {t.th_stakesol_high:.1f}", unsafe_allow_html=True)
            with c3:
                st.info("**SKR баланс**")
                st.markdown(f"🟡 = {int(t.th_skr_zero)}<br>🟢 ≤ {_k(t.th_skr_low)}<br>🌲 ≤ {_k(t.th_skr_mid)}<br>🔵 > {_k(t.th_skr_mid)}", unsafe_allow_html=True)
        else:
            if any(f"wg_{k}" not in st.session_state for k in DEFAULTS):
                for k, v in DEFAULTS.items():
                    st.session_state[f"wg_{k}"] = st.session_state.get(k, v)

            c1, c2, c3 = st.columns(3)
            with c1:
                st.info("**Баланс (SOL)**")
                st.number_input("🔴 <", key="wg_th_sol_low", value=t.th_sol_low, step=0.01, format="%.2f")
                st.number_input("🟠 <", key="wg_th_sol_mid", value=t.th_sol_mid, step=0.01, format="%.2f")
                st.number_input("🟢 <", key="wg_th_sol_high", value=t.th_sol_high, step=0.01, format="%.2f")
                st.number_input("🌲 <", key="wg_th_sol_top", value=t.th_sol_top, step=0.01, format="%.2f")
            with c2:
                st.info("**Активность**")
                st.number_input("🟠 <", key="wg_th_tx_green", value=t.th_tx_green, step=1, format="%d")
                st.number_input("🟡 ≤", key="wg_th_tx_yellow", value=t.th_tx_yellow, step=1, format="%d")
                st.number_input("🟢 ≤", key="wg_th_tx_fire", value=t.th_tx_fire, step=1, format="%d")
            with c3:
                st.info("**Бейджи**")
                st.number_input("🌱 >", key="wg_th_badge_green", value=t.th_badge_green, step=1, format="%d")
                st.number_input("⭐ >", key="wg_th_badge_yellow", value=t.th_badge_yellow, step=1, format="%d")
                st.number_input("🔥 >", key="wg_th_badge_fire", value=t.th_badge_fire, step=1, format="%d")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.info("**Staked SKR**")
                st.number_input("🟠 <", key="wg_th_stakeskr_low", value=t.th_stakeskr_low, step=1000, format="%d")
                st.number_input("🟡 <", key="wg_th_stakeskr_mid", value=t.th_stakeskr_mid, step=1000, format="%d")
                st.number_input("🟢 <", key="wg_th_stakeskr_high", value=t.th_stakeskr_high, step=1000, format="%d")
                st.number_input("🌲 <", key="wg_th_stakeskr_top", value=t.th_stakeskr_top, step=1000, format="%d")
                st.number_input("🔵 <", key="wg_th_stakeskr_max", value=t.th_stakeskr_max, step=1000, format="%d")
            with c2:
                st.info("**Staked SOL**")
                st.number_input("🟠 <", key="wg_th_stakesol_low", value=t.th_stakesol_low, step=0.1, format="%.1f")
                st.number_input("🟡 <", key="wg_th_stakesol_mid", value=t.th_stakesol_mid, step=0.1, format="%.1f")
                st.number_input("🟢 <", key="wg_th_stakesol_high", value=t.th_stakesol_high, step=0.1, format="%.1f")
            with c3:
                st.info("**SKR баланс**")
                st.number_input("🟡 =", key="wg_th_skr_zero", value=t.th_skr_zero, step=1, format="%d")
                st.number_input("🟢 ≤", key="wg_th_skr_low", value=t.th_skr_low, step=1000, format="%d")
                st.number_input("🌲 ≤", key="wg_th_skr_mid", value=t.th_skr_mid, step=1000, format="%d")

        c1, c2 = st.columns(2)
        with c1:
            if not edit:
                if st.button("✏️ Редактировать", key="start_edit", use_container_width=True):
                    st.session_state.edit_legend = True
                    for k in DEFAULTS:
                        st.session_state.pop(f"wg_{k}", None)
                    st.rerun()
            else:
                if st.button("💾 Сохранить", key="save_th", use_container_width=True):
                    _save_config()
                    st.session_state.edit_legend = False
                    st.rerun()
        with c2:
            if st.button("↺ Сбросить", key="reset_th", use_container_width=True):
                for k, v in HARD_DEFAULTS.items():
                    st.session_state[k] = v
                    st.session_state.pop(f"wg_{k}", None)
                _save_config()
                st.rerun()

    with st.expander("🎨 Оформление", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.color_picker("Фон строк", "#7d91a6", key="row_bg")
        with col2:
            st.color_picker("Текст", "#000000", key="row_tx")
        hide_vid = st.session_state.get("hide_bg_video", False)
        if st.button("🎬 Фон OFF" if not hide_vid else "🎬 Фон ON", key="toggle_bg"):
            new_val = not hide_vid
            st.session_state.hide_bg_video = new_val
            _save_config()
            st.rerun()

    st.markdown("---")
    st.caption("📦 Версия 4.1.0")
