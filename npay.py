import requests as reqs
import asyncio
import time
import uuid
from curl_cffi import requests
from loguru import logger
from fake_useragent import UserAgent
from utils.banner import banner
from colorama import Fore, Style, init
from datetime import datetime

init()

PING_INTERVAL = 60
MAX_ACTIVE_PROXIES = 3
RETRIES = 60
TOKEN_FILE = 'tokens.txt'
PROXY_FILE = 'proxy.txt'
DOMAIN_API = {
    "SESSION": "http://api.nodepay.ai/api/auth/session",
    "PING": "https://nw.nodepay.org/api/network/ping",
    "DAILY_CLAIM": "https://api.nodepay.org/api/mission/complete-mission"
}

CONNECTION_STATES = {
    "CONNECTED": 1,
    "DISCONNECTED": 2,
    "NONE_CONNECTION": 3
}

status_connect = CONNECTION_STATES["NONE_CONNECTION"]
browser_id = None
account_info = {}
last_ping_time = {}

def uuidv4():
    return str(uuid.uuid4())

def show_banner():
    print(Fore.MAGENTA + banner + Style.RESET_ALL)

def show_copyright():
    print(Fore.MAGENTA + Style.BRIGHT + banner + Style.RESET_ALL)

def valid_resp(resp):
    if not resp or "code" not in resp or resp["code"] < 0:
        raise ValueError("Invalid response")
    return resp

def load_tokens_from_file(filename):
    try:
        with open(filename, 'r') as file:
            tokens = file.read().splitlines()
        return tokens
    except Exception as e:
        logger.error(f"Failed to load tokens: {e}")
        raise SystemExit("Exiting due to failure in loading tokens")

def load_proxies(proxy_file):
    try:
        with open(proxy_file, 'r') as file:
            proxies = file.read().splitlines()
        return proxies
    except Exception as e:
        logger.error(f"Failed to load proxies: {e}")
        raise SystemExit("Exiting due to failure in loading proxies")

def dailyclaim(token):
    url = DOMAIN_API["DAILY_CLAIM"]
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Origin": "https://app.nodepay.ai",
        "Referer": "https://app.nodepay.ai/",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    data = {"mission_id": "1"}

    try:
        response = requests.post(url, headers=headers, json=data, timeout=15)
        if response.status_code != 200:
            log_message("Daily Claim FAILED, maybe it's already claimed?", Fore.RED)
            return False

        response_json = response.json()
        if response_json.get("success"):
            log_message("Daily Claim SUCCESSFUL", Fore.GREEN)
            return True
        else:
            log_message("Daily Claim FAILED, maybe it's already claimed?", Fore.RED)
            return False
    except Exception as e:
        log_message(f"Error in dailyclaim: {e}", Fore.RED)
        return False

async def call_api(url, data, proxy, token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Origin": "chrome-extension://lgmpfmgeabnnlemejacfljbmonaomfmm",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        response = requests.post(
            url,
            json=data,
            headers=headers,
            impersonate="safari15_5",
            proxies={"http": proxy, "https": proxy},
            timeout=15
        )
        response.raise_for_status()
        return valid_resp(response.json())

    except requests.HTTPError as http_err:
        if response.status_code == 403:
            log_message(f"HTTP 403: Access denied for proxy {proxy} or token {token}.", Fore.RED)
            return {"blocked": True}  # Mark as blocked
        log_message(f"HTTP error for proxy {proxy}: {http_err}", Fore.RED)
        raise

    except Exception as e:
        log_message(f"Error during API call to {url} via proxy {proxy}: {e}", Fore.RED)
        raise ValueError(f"Failed API call to {url}")

async def render_profile_info(proxy, token):
    global browser_id, account_info

    try:
        browser_id = uuidv4()
        response = await call_api(DOMAIN_API["SESSION"], {}, proxy, token)
        valid_resp(response)
        account_info = response["data"]
        if account_info.get("uid"):
            log_message(f"Profile info loaded for proxy {proxy}.", Fore.GREEN)
            return True
        else:
            log_message(f"Failed to load profile info for proxy {proxy}.", Fore.RED)
            return None
    except Exception as e:
        log_message(f"Error in render_profile_info for proxy {proxy}: {e}", Fore.RED)
        return "blocked"

async def main():
    all_proxies = load_proxies(PROXY_FILE)
    failed_proxies = set()
    failed_tokens = set()

    tokens = load_tokens_from_file(TOKEN_FILE)
    if not tokens:
        log_message("Token file is empty. Exiting the program.", Fore.RED)
        exit()
    if not all_proxies:
        log_message("Proxy file is empty. Exiting the program.", Fore.RED)
        exit()

    for token in tokens:
        if token in failed_tokens:
            continue  # Skip failed tokens
        log_message(f"Performing daily claim with token {token}...", Fore.YELLOW)
        if not dailyclaim(token):
            log_message(f"Token {token} failed during daily claim.", Fore.RED)
            failed_tokens.add(token)

    while True:
        active_proxies = [
            proxy for proxy in all_proxies if proxy not in failed_proxies][:MAX_ACTIVE_PROXIES]

        if not active_proxies:
            log_message("No active proxies available. Exiting the program.", Fore.RED)
            exit()

        tasks = {asyncio.create_task(render_profile_info(proxy, token)): proxy for proxy in active_proxies for token in tokens if token not in failed_tokens}

        done, _ = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            proxy = tasks[task]
            try:
                result = task.result()
                if result == "blocked":
                    log_message(f"Proxy {proxy} or token caused a block. Removing it.", Fore.RED)
                    failed_proxies.add(proxy)
                elif result is None:
                    log_message(f"Proxy {proxy} failed. Removing it.", Fore.RED)
                    failed_proxies.add(proxy)
            except Exception as e:
                log_message(f"Error with proxy {proxy}: {e}", Fore.RED)
                failed_proxies.add(proxy)

        all_proxies = [proxy for proxy in all_proxies if proxy not in failed_proxies]
        tokens = [token for token in tokens if token not in failed_tokens]

        if not all_proxies or not tokens:
            log_message("No valid proxies or tokens left. Exiting.", Fore.RED)
            exit()

        await asyncio.sleep(3)

def log_message(message, color):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(color + f"[{timestamp}] {message}" + Style.RESET_ALL)

if __name__ == '__main__':
    show_copyright()
    log_message("RUNNING WITH PROXIES", Fore.WHITE)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log_message("Program terminated by user.", Fore.RED)
