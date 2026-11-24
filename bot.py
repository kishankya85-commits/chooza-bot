import os
import json
import random
import time
from datetime import datetime, timezone, timedelta
import requests

API = "https://graph.facebook.com/v21.0"
TOKEN = os.environ["IG_TOKEN"]
IG_ID = os.environ.get("IG_USER_ID", "17841475497060173")
MY_NAME = os.environ.get("IG_USERNAME", "kishan_ku_2k").lower()

DELAY_SEC = int(os.environ.get("REPLY_DELAY_MIN", "25")) * 60
MAX_REPLIES = int(os.environ.get("MAX_REPLIES_PER_RUN", "15"))
REPLY_TO_OLD = False

# सुरक्षित लिमिट्स ताकि Rate Limit (1-2 घंटे वाला ब्लॉक) न लगे
MAX_MEDIA = int(os.environ.get("MAX_MEDIA", "60"))
MAX_PAGES = int(os.environ.get("MAX_PAGES", "60"))
PAGE_SLEEP = float(os.environ.get("PAGE_SLEEP", "1.5"))

STATE_FILE = "state.json"

IST = timezone(timedelta(hours=5, minutes=30))
KING_AFTER_TXT = os.environ.get("KING_AFTER", "2026-11-24 23:59")
KING_AFTER = datetime.strptime(KING_AFTER_TXT, "%Y-%m-%d %H:%M").replace(tzinfo=IST).timestamp()

RANKS = [(4, "जाइंट"), (3, "रोबोट"), (2, "स्नाइपर"), (1, "सैनिक")]

JOIN_LINES = [
    "आपको हमने रैंक कर दिया है। एक बार हमसे बड़ों से याको चूर जवान बन लो।",
    "आपको हमने रैंक कर दिया है। हमारे बड़ों से चौकाया सेना/हुआ है, इसे एक बार पहचान कर लो।",
    "आपको हमने रैंक कर दिया है। बड़ों में आकर तुम ध्यान कर लो और सुरक्षित रहो।"
]


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(f"{code}: {msg}")
        self.code = code


def _check(r):
    try:
        j = r.json()
    except Exception:
        raise ApiError(-1, r.text[:200])
    if "error" in j:
        raise ApiError(j["error"].get("code", -1), j["error"].get("message", ""))
    return j


def api_get(url, params=None):
    p = dict(params or {})
    p["access_token"] = TOKEN
    return _check(requests.get(url, params=p, timeout=30))


def api_post(url, data):
    d = dict(data)
    d["access_token"] = TOKEN
    return _check(requests.post(url, data=d, timeout=30))


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
        return f"@{user} 👑 {base_msg} | कुल कमेंट: {n} | रैंक: किंग 👑"
    return f"@{user} {base_msg} | कुल कमेंट: {n}"


def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp()


def load():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
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
    new = 0

    for m in media:
        try:
            for c in paged(f"{m['id']}/comments", {"fields": "id,text,username,timestamp", "limit": 100}, MAX_PAGES):
                cid = c.get("id")
                user = (c.get("username") or "").lower()
                if not cid or not user or user == MY_NAME or cid in st["seen"]:
                    continue

                ts = parse_ts(c["timestamp"])
                st["seen"][cid] = {"u": user, "t": ts}

                if ts > KING_AFTER:
                    continue

                st["counts"][user] = st["counts"].get(user, 0) + 1
                st["last"][user] = max(st["last"].get(user, 0), ts)
                new += 1

                if first and not REPLY_TO_OLD:
                    continue

                st["pending"].append({"id": cid, "u": user, "due": now + DELAY_SEC, "tries": 0})
        except ApiError as e:
            if e.code == 190:
                raise
            print("Scan skip media / rate limit:", m.get("id"), e)
            save(st)
            time.sleep(2)
            break

    st["init"] = True
    save(st)
    return new


def send_due(st, now):
    due = [p for p in st["pending"] if p["due"] <= now]
    if not due:
        return 0

    latest = {}
    for p in due:
        t = st["seen"].get(p["id"], {}).get("t", 0)
        if p["u"] not in latest or t > st["seen"].get(latest[p["u"]]["id"], {}).get("t", 0):
            latest[p["u"]] = p

    keep_ids = {p["id"] for p in latest.values()}
    st["pending"] = [p for p in st["pending"] if p["id"] not in {d["id"] for d in due} or p["id"] in keep_ids]

    sent = 0
    for p in sorted(latest.values(), key=lambda x: x["due"]):
        if sent >= MAX_REPLIES:
            break
        try:
            api_post(f"{API}/{p['id']}/replies", {"message": make_reply(st, p["u"], now)})
            st["pending"] = [q for q in st["pending"] if q["id"] != p["id"]]
            sent += 1
            time.sleep(1.5)
        except ApiError as e:
            if e.code == 190:
                raise
            p["tries"] += 1
            print("reply fail:", p["id"], e)
            if p["tries"] >= 3 or e.code in (100, 109005):
                st["pending"] = [q for q in st["pending"] if q["id"] != p["id"]]
            if e.code in (4, 17, 32, 613):
                break

    save(st)
    return sent


def write_board(st, now):
    final = is_final(now)
    king = top_user(st) if final else None
    rows = sorted(st["counts"].items(), key=lambda kv: (-kv[1], st["last"].get(kv[0], 0), kv[0]))
    if final and king in st["counts"]:
        rows = [(king, st["counts"][king])] + [kv for kv in rows if kv[0] != king]

    out = []
    for u, n in rows:
        out.append({"user": u, "comments": n, "rank": rank_for(st, u, now)})

    with open("leaderboard.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    if out:
        header_note = (
            f"**🏆 फाइनल KING: @{out[0]['user']} ({out[0]['comments']} कमेंट)**"
            if final
            else f"KING का फैसला 24 नवंबर रात 12:00 बजे के बाद सबसे ज़्यादा कमेंट वाले पर होगा"
        )
    else:
        header_note = "अभी तक कोई कमेंट दर्ज नहीं हुआ है।"

    lines = [
        "# 🏆 चूज़ा सेना लीडरबोर्ड",
        "",
        header_note,
        "",
        "| # | यूज़रनेम | कमेंट | रैंक |",
        "|---|---|---|---|",
    ]
    for i, e in enumerate(out, 1):
        lines.append(f"| {i} | @{e['user']} | {e['comments']} | {e['rank']} |")

    with open("leaderboard.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    if final and out:
        with open("final_king.txt", "w", encoding="utf-8") as f:
            f.write(f"KING @{out[0]['user']} ({out[0]['comments']} कमेंट)\n")


def main():
    now = datetime.now(timezone.utc).timestamp()
    st = load()
    new = scan(st, now)
    sent = send_due(st, now)
    write_board(st, now)
    save(st)
    print(f"naye comments: {new}, bheje reply: {sent}, pending: {len(st['pending'])}, log: {len(st['counts'])}")


if __name__ == "__main__":
    main()
    
