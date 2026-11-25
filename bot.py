import json
import os
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

MAX_MEDIA = int(os.environ.get("MAX_MEDIA", "30"))
MAX_PAGES = int(os.environ.get("MAX_PAGES", "25"))
PAGE_SLEEP = float(os.environ.get("PAGE_SLEEP", "1.5"))

STATE_FILE = "state.json"
BOARD_MD = "leaderboard.md"
BOARD_JSON = "leaderboard.json"

IST = timezone(timedelta(hours=5, minutes=30))
KING_AFTER_TXT = os.environ.get("KING_AFTER", "2026-11-24 00:00")
KING_AFTER = datetime.strptime(KING_AFTER_TXT, "%Y-%m-%d %H:%M").replace(tzinfo=IST).timestamp()

RANKS = [(4, "जाइंट"), (3, "रोबोट"), (2, "स्नाइपर"), (1, "सैनिक")]


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
    attempts = max(1, len(TOKENS))
    for i in range(attempts):
        p = dict(params or {})
        p["access_token"] = TOKEN
        for retry in range(3):
            try:
                resp = requests.get(url, params=p, timeout=60)
                return _check(resp)
            except requests.exceptions.RequestException as e:
                if retry < 2:
                    wait = 3 * (retry + 1)
                    print(f"Network/Timeout retry ({retry + 1}/3) after {wait}s: {e}")
                    time.sleep(wait)
                    continue
                raise ApiError(-2, f"Network timeout/error: {e}")
            except ApiError as e:
                if e.code in (4, 17, 32, 190, 613) and i < attempts - 1:
                    rotate_token()
                    break
                raise


def paged(path, params, max_pages):
    url = f"{API}/{path}"
    p = dict(params or {})
    for _ in range(max_pages):
        j = api_get(url, p)
        for item in j.get("data", []):
            yield item
        nxt = j.get("paging", {}).get("next")
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


def scan(st):
    media_limit_pages = max(1, (MAX_MEDIA + 24) // 25)
    media = list(paged(f"{IG_ID}/media", {"fields": "id,timestamp", "limit": 25}, media_limit_pages))[:MAX_MEDIA]
    new_count = 0

    for m in media:
        try:
            for c in paged(f"{m['id']}/comments", {"fields": "id,text,username,timestamp", "limit": 100}, MAX_PAGES):
                cid = str(c.get("id") or "").strip()
                user = str(c.get("username") or "").strip().lower()
                if cid and not user:
                    print("no username:", cid)
                if not cid or not user or user == MY_NAME:
                    continue

                ts = parse_ts(c.get("timestamp"))

                if cid not in st["seen"]:
                    st["seen"][cid] = {"u": user, "t": ts}
                    st["counts"][user] = st["counts"].get(user, 0) + 1
                    new_count += 1
                st["last"][user] = max(st["last"].get(user, 0), ts)

        except ApiError as e:
            print("Scan error on media", m.get("id"), e)
            if e.code == 190 and not rotate_token():
                st["init"] = True
                save(st)
                raise
            save(st)
            time.sleep(2)
            continue

    st["init"] = True
    save(st)
    return new_count


def write_board(st, now):
    final = is_final(now)
    king = top_user(st)
    rows = sorted(
        st["counts"].items(),
        key=lambda kv: (-kv[1], st["last"].get(kv[0], 0)),
    )

    data = []
    for user, n in rows:
        rank = "किंग" if (final and user == king) else base_rank(n)
        data.append({"user": user, "comments": n, "rank": rank})
    with open(BOARD_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    lines = ["# 🏆 चूज़ा सेना लीडरबोर्ड", ""]
    if final and king:
        lines.append(f"🏆 **फाइनल KING: @{king}** ({st['counts'][king]} कमेंट)")
        lines.append("")
    lines.append("| # | यूज़रनेम | कमेंट | रैंक |")
    lines.append("|---|---|---|---|")
    for i, d in enumerate(data, 1):
        lines.append(f"| {i} | @{d['user']} | {d['comments']} | {d['rank']} |")
    with open(BOARD_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    if not TOKENS:
        raise SystemExit("IG_TOKEN / IG_TOKENS नहीं मिला")
    now = time.time()
    st = load()
    st["pending"] = []
    new_count = scan(st)
    write_board(st, now)
    save(st)
    print(f"नए कमेंट: {new_count} | कुल यूज़र: {len(st['counts'])}")


if __name__ == "__main__":
    main()
