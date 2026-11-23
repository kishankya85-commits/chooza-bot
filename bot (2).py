"""ChoozaSenaBot - Instagram comment rank bot.
Har run me: naye comments gino -> 25 min baad rank wala reply -> leaderboard update."""
import os, json, random
from datetime import datetime, timezone, timedelta
import requests

API = "https://graph.facebook.com/v21.0"
TOKEN = os.environ["IG_TOKEN"]
IG_ID = os.environ.get("IG_USER_ID", "17841475497869173")
MY_NAME = os.environ.get("IG_USERNAME", "kishan_ku_2k").lower()
DELAY_SEC = int(os.environ.get("REPLY_DELAY_MIN", "25")) * 60
MAX_REPLIES = int(os.environ.get("MAX_REPLIES_PER_RUN", "8"))
REPLY_TO_OLD = os.environ.get("REPLY_TO_OLD", "0") == "1"  # pehli baar purane comments par reply?
MAX_MEDIA = 15      # kitni latest reels/posts dekhni hain
MAX_PAGES = int(os.environ.get("MAX_PAGES", "10"))      # har reel ke comments ke kitne page (100/page)
STATE_FILE = "state.json"

# KING sirf is tareekh/time ke baad (IST) reveal hota hai (sabse zyada comment wala). Tab tak max rank जाइंट, aur board par koi aage nahi dikhta.
IST = timezone(timedelta(hours=5, minutes=30))
KING_AFTER_TXT = os.environ.get("KING_AFTER", "2026-11-24 23:59")
KING_AFTER = datetime.strptime(KING_AFTER_TXT, "%Y-%m-%d %H:%M").replace(tzinfo=IST).timestamp()

# (kam se kam comment, rank) -- upar se neeche check hota hai. 4 ya zyada comment = जाइंट (KING alag se)
RANKS = [(4, "जाइंट"), (3, "रोबोट"), (2, "स्नाइपर"), (1, "सेना")]

LINES = {
    "सेना": ["चूज़ा सेना में स्वागत है! 🐥", "सेना में भर्ती हो गई! 🪖", "पहला कदम रख दिया, जवान! 🐥"],
    "स्नाइपर": ["निशाना सीधा लगा! 🎯", "अब तुम स्नाइपर हो! 🎯", "तेज़ नज़र, पक्का निशाना! 🎯"],
    "रोबोट": ["मशीन की तरह एक्टिव! 🤖", "रोबोट सोल्जर बन गए! 🤖", "पावर बढ़ रही है! 🤖"],
    "जाइंट": ["तुम तो जाइंट मुर्गे निकले! 🐔", "सेना की असली ताकत! 💪", "बड़ा कदम, जाइंट! 🐔"],
    "किंग": ["सेना के KING! 👑", "सलाम करो, राजा आ गया! 👑", "राजा की जय हो! 👑"],
}

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
    p = dict(params or {}); p["access_token"] = TOKEN
    return _check(requests.get(url, params=p, timeout=30))

def api_post(url, data):
    d = dict(data); d["access_token"] = TOKEN
    return _check(requests.post(url, data=d, timeout=30))

def paged(path, params, max_pages):
    url = f"{API}/{path}"
    for _ in range(max_pages):
        j = api_get(url, params)
        for item in j.get("data", []):
            yield item
        nxt = j.get("paging", {}).get("next")
        if not nxt:
            return
        url, params = nxt, None   # next URL me token pehle se hota hai

def base_rank(n):
    for th, name in RANKS:
        if n >= th:
            return name
    return "सेना"

def top_user(st):
    """Sabse zyada comment wala. Barabari ho to jisne pehle us count tak pahunchna (purana last comment) wo aage."""
    if not st["counts"]:
        return None
    return max(st["counts"].items(), key=lambda kv: (kv[1], -st["last"].get(kv[0], 0)))[0]

def is_final(now):
    return now > KING_AFTER

def rank_for(st, user, now):
    if is_final(now) and user == top_user(st):
        return "किंग"
    return base_rank(st["counts"].get(user, 0))

def shown(n, now):
    """Reveal se pehle 4+ comment wale ki asli ginti nahi dikhani (taaki KING pehle se na pata chale)."""
    return str(n) if (is_final(now) or n < 4) else "4+"

def make_reply(st, user, now):
    n = st["counts"].get(user, 1)
    rank = rank_for(st, user, now)
    msg = f"@{user} {random.choice(LINES[rank])}\nतुम्हारा रैंक: {rank} ({shown(n, now)} कमेंट)"
    if rank == "किंग":
        return msg
    nxt = [th for th, _ in RANKS if th > n]
    if nxt:
        name = [nm for th, nm in RANKS if th == min(nxt)][0]
        msg += f"\nअगला रैंक {name} बनने के लिए {min(nxt) - n} कमेंट और!"
    elif not is_final(now):
        msg += f"\nKING का नाम {KING_AFTER_TXT[:10]} को खुलेगा, जिसके सबसे ज़्यादा कमेंट होंगे 👑"
    return msg

def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp()

def load():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
            st.setdefault("last", {})
            return st
    except Exception:
        return {"init": False, "seen": {}, "counts": {}, "last": {}, "pending": []}

def save(st):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, separators=(",", ":"))

def scan(st, now):
    first = not st["init"]
    media = list(paged(f"{IG_ID}/media", {"fields": "id,timestamp", "limit": 25}, 1))[:MAX_MEDIA]
    new = 0
    for m in media:
        for c in paged(f"{m['id']}/comments", {"fields": "id,text,username,timestamp", "limit": 100}, MAX_PAGES):
            cid, user = c["id"], (c.get("username") or "").lower()
            if not user or user == MY_NAME or cid in st["seen"]:
                continue
            ts = parse_ts(c["timestamp"])
            st["seen"][cid] = {"u": user, "t": ts}
            if ts > KING_AFTER:      # last tareekh ke baad ke comment gine nahi jate
                continue
            st["counts"][user] = st["counts"].get(user, 0) + 1
            st["last"][user] = max(st["last"].get(user, 0), ts)
            new += 1
            if first and not REPLY_TO_OLD:
                continue
            st["pending"].append({"id": cid, "u": user, "due": max(ts + DELAY_SEC, now), "tries": 0})
    st["init"] = True
    return new

def send_due(st, now):
    due = [p for p in st["pending"] if p["due"] <= now]
    if not due:
        return 0
    # ek user ke kai pending ho to sirf sabse naye par reply (spam se bachne ke liye)
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
        except ApiError as e:
            if e.code == 190:
                raise                      # token kharab -> workflow fail, GitHub mail bhejega
            p["tries"] += 1
            print("reply fail", p["id"], e)
            if p["tries"] >= 3 or e.code in (100, 1609005):
                st["pending"] = [q for q in st["pending"] if q["id"] != p["id"]]
    return sent

def write_board(st, now):
    final = is_final(now)
    if final:
        rows = sorted(st["counts"].items(), key=lambda kv: (-kv[1], st["last"].get(kv[0], 0), kv[0]))
    else:
        # reveal se pehle: ginti ke hisaab se nahi, sirf rank-tier + A-Z, taaki aage kaun hai pata na chale
        rows = sorted(st["counts"].items(), key=lambda kv: (-min(kv[1], 4), kv[0]))
    out = []
    for u, n in rows:
        out.append({"user": u, "comments": shown(n, now), "rank": rank_for(st, u, now)})
    with open("leaderboard.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    lines = ["# 🏆 चूज़ा सेना लीडरबोर्ड", "",
             ("👑 फ़ाइनल: KING घोषित हो चुका है" if final else f"👑 KING का नाम {KING_AFTER_TXT[:10]} को खुलेगा (जिसके सबसे ज़्यादा कमेंट होंगे)"), "",
             "| # | यूज़रनेम | कमेंट | रैंक |", "|---|---|---|---|"]
    for i, o in enumerate(out[:100], 1):
        lines.append(f"| {i} | @{o['user']} | {o['comments']} | {o['rank']} |")
    with open("leaderboard.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if final and out:
        with open("final_king.txt", "w", encoding="utf-8") as f:
            f.write(f"KING: @{out[0]['user']} ({out[0]['comments']} कमेंट)\n")

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
