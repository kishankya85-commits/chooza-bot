import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
import requests

API = "https://graph.facebook.com/v21.0"


def get_tokens() -> list[str]:
    multi = os.environ.get("IG_TOKENS", "")
    single = os.environ.get("IG_TOKEN", "")
    raw = f"{multi},{single}"
    tokens = []
    for t in raw.split(","):
        t = t.strip()
        if t and t not in tokens:
            tokens.append(t)
    return tokens


TOKENS = get_tokens()
TOKEN_INDEX = 0
TOKEN = TOKENS[0] if TOKENS else ""

IG_ID = os.environ.get("IG_USER_ID", "17841475497080173")
MY_NAME = os.environ.get("IG_USERNAME", "kishan_ku_2k").lower()

DELAY_SEC = int(os.environ.get("REPLY_DELAY_MIN", "25")) * 60
MAX_REPLIES = int(os.environ.get("MAX_REPLIES_PER_RUN", "15"))
REPLY_TO_OLD = False

MAX_MEDIA = int(os.environ.get("MAX_MEDIA", "30"))
MAX_PAGES = int(os.environ.get("MAX_PAGES", "25"))
PAGE_SLEEP = float(os.environ.get("PAGE_SLEEP", "1.5"))

STATE_FILE = "state.json"

IST = timezone(timedelta(hours=5, minutes=30))
KING_AFTER_TXT = os.environ.get("KING_AFTER", "2026-11-24 23:59")
KING_AFTER = datetime.strptime(KING_AFTER_TXT, "%Y-%m-%d %H:%M").replace(tzinfo=IST).timestamp()

RANKS = [(4, "जाइंट"), (3, "रोबोट"), (2, "स्नाइपर"), (1, "सैनिक")]

JOIN_LINES = [
    "आपको हमने रैंक कर दिया है। एक बार हममें नहीं थे वक़्त पूरा तमाम बन लो।",
    "आपको हमने रैंक कर दिया है। हमारे यहाँ से परिवार सेना/हुना है, इसे एक बार पहचान कर लो।",
    "आपको हमने रैंक कर दिया है। यहाँ में आकर तुम ध्यान उन लो और सुरक्षित रहो।",
]


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(f"{code}: {msg}")
        self.code = code


def rotate_token() -> bool:
    global TOKEN_INDEX, TOKEN
    if len(TOKENS) <= 1:
        return False
    TOKEN_INDEX = (TOKEN_INDEX + 1) % len(TOKENS)
    TOKEN = TOKENS[TOKEN_INDEX]
    print(f"Switched to token #{TOKEN_INDEX + 1}")
    return True


def _check(r):
    try:
        j = r.json()
    except Exception:
        raise ApiError(-1, r.text[:200])
    if "error" in j:
        raise ApiError(j["error"].get("code", -1), j["error"].get("message", ""))
    return j


def api_get(url, params=None):
    global TOKEN
    attempts = max(1, len(TOKENS))
    for i in range(attempts):
        p = dict(params or {})
        p["access_token"] = TOKEN
        try:
            return _check(requests.get(url, params=p, timeout=30))
        except ApiError as e:
            if e.code in (4, 17, 32, 190, 613) and i < attempts - 1:
                rotate_token()
                continue
            raise


def api_post(url, data):
    global TOKEN
    attempts = max(1, len(TOKENS))
    for i in range(attempts):
        d = dict(data)
        d["access_token"] = TOKEN
        try:
            return _check(requests.post(url, data=d, timeout=30))
        except ApiError as e:
            if e.code in (4, 17, 32, 190, 613) and i < attempts - 1:
                rotate_token()
                continue
            raise


def paged(path, params, max_pages):
    url = f"{API}/{path}"
    p = dict(params or {})
    for _ in range(max_pages):
        j = api_get(url, p)
        for item in j.get("data", []):
            yield item
        paging = j.get("paging", {})
        nxt = paging.get("next")
        if not nxt:
            return
        url = nxt
        p = {}
        time.sleep(PAGE_SLEEP)


def base_rank(n):
    for th, name in RANKS:
        if n >= th:
            return name
    return "सैनिक"


def top_user(st):
    if not st["counts"]:
        return None
    return max(st["counts"].items(), key=lambda kv: (kv[1], -st["last"].get(kv[0], 0)))[0]


def is_final(now):
    return now >= KING_AFTER


def rank_for(st, user, now):
    if is_final(now) and user == top_user(st):
        return "किंग"
    return base_rank(st["counts"].get(user, 0))


def make_reply(st, user, now):
    n = st["counts"].get(user, 1)
    rank = rank_for(st, user, now)
    base_msg = random.choice(JOIN_LINES)
    if rank == "किंग":
        return f"@{user} {base_msg} | कुल कमेंट: {n} | रैंक: किंग 👑"
    return f"@{user} {base_msg} | कुल कमेंट: {n}"


def parse_ts(s):
    if not s:
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return 0.0


def load():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            st = json.load(f)
        if not isinstance(st, dict):
            st = {}
        st.setdefault("init", False)
        st.setdefault("seen", {})
        st.setdefault("counts", {})
        st.setdefault("last", {})
        st.setdefault("pending", [])
        return st
    except Exception:
        return {"init": False, "seen": {}, "counts": {}, "last": {}, "pending": []}


def save(st):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, separators=(",", ":"))


def scan(st, now):
    first = not st["init"]
    media_limit_pages = max(1, (MAX_MEDIA + 24) // 25)
    media = list(paged(f"{IG_ID}/media", {"fields": "id,timestamp", "limit": 25}, media_limit_pages))[:MAX_MEDIA]
    new_count = 0

    for m in media:
        try:
            for c in paged(f"{m['id']}/comments", {"fields": "id,text,username,timestamp", "limit": 100}, MAX_PAGES):
                cid = str(c.get("id") or "").strip()
                user = str(c.get("username") or "").strip().lower()
                if not cid or not user or user == MY_NAME:
                    continue

                ts = parse_ts(c.get("timestamp"))

                # अगर कोई पुराना कमेंट पहले seen में नहीं है या काउंट में नहीं गिना गया है, तो जोड़ें
                already_seen = cid in st["seen"]
                if not already_seen:
                    st["seen"][cid] = {"u": user, "t": ts}
                    st["counts"][user] = st["counts"].get(user, 0) + 1
                    st["last"][user] = max(st["last"].get(user, 0), ts)
                    new_count += 1

                    if first and not REPLY_TO_OLD:
                        continue

                    st["pending"].append({"id": cid, "u": user, "due": now + DELAY_SEC, "tries": 0})
                else:
                    # सुरक्षा: यदि seen में है पर last अपडेट नहीं हुआ है
                    st["last"][user] = max(st["last"].get(user, 0), ts)

        except ApiError as e:
            if e.code == 190 and not rotate_token():
                raise
            print("Scan skip media / rate limit:", m.get("id"), e)
            save(st)
            time.sleep(2)
            break

    st["init"] = True
    save(st)
    return new_count


def send_due(st, now):
    due = [p for p in st["pending"] if p.get("due", 0) <= now]
    if not due:
        return 0

    # हर यूज़र के लिए सबसे नया due कमेंट चुनें, लेकिन दूसरे due आइटम्स को गलत तरीके से न काटें
    latest_by_user = {}
    for p in due:
        u = p.get("u")
        if not u:
            continue
        t = st["seen"].get(p.get("id"), {}).get("t", 0)
        if u not in latest_by_user or t >= st["seen"].get(latest_by_user[u].get("id"), {}).get("t", 0):
            latest_by_user[u] = p

    sent = 0
    sent_ids = set()
    drop_ids = set()

    for p in sorted(latest_by_user.values(), key=lambda x: x.get("due", 0)):
        if sent >= MAX_REPLIES:
            break
        pid = p.get("id")
        try:
            api_post(f"{API}/{pid}/replies", {"message": make_reply(st, p["u"], now)})
            sent_ids.add(pid)
            sent += 1
            time.sleep(1.5)
        except ApiError as e:
            if e.code == 190 and not rotate_token():
                raise
            print("reply fail:", pid, e)
            p["tries"] = p.get("tries", 0) + 1
            if p["tries"] >= 3 or e.code in (100, 109005):
                drop_ids.add(pid)
            if e.code in (4, 17, 32, 613):
                break

    if sent_ids or drop_ids:
        st["pending"] = [p for p in st["pending"] if p.get("id") not in (sent_ids | drop_ids)]

    save(st)
    return sent


def write_board(st, now):
    final = is_final(now)
    king = top_
    
