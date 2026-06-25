import os, json, datetime, re, base64
from zoneinfo import ZoneInfo
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
import anthropic
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

IST = ZoneInfo("Asia/Kolkata")

# ====== EDIT THESE: your 2 groups ======
GROUPS = [
    {"id": "g1", "name": "CFA L1 Online 2025/2026", "icon": "", "chat": -1003692335693},
    {"id": "g2", "name": "SSEI", "icon": "", "chat": -1001456537902},
]
# =======================================

API_ID   = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION  = os.environ["TG_SESSION"]
PIN      = os.environ["BRIEFING_PIN"]
ai = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

PROMPT = """You are summarizing messages from an admin-only study group.
Every message is important (class material, homework, announcements).
Return ONLY valid JSON, no prose, no markdown fences, exactly this shape:
{{
  "highlights": [{{"rank": 1, "text": "...", "tag": "Important|Update|Material"}}],
  "actions":    [{{"text": "what to do/submit", "due": "short e.g. Tomorrow / Jun 29 / Mon", "urgent": true}}],
  "links":      [{{"label": "human label", "url": "the link or # if it was a file"}}]
}}
Rank highlights most-important first. Mark a deadline within ~24h as urgent:true.
Group name: {name}
Messages (oldest first):
{messages}"""

def summarize(name, msgs):
    if not msgs:
        return {"highlights": [], "actions": [], "links": []}
    joined = "\n".join(f"[{m['time']}] {m['text']}" for m in msgs)
    r = ai.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": PROMPT.format(name=name, messages=joined)}],
    )
    text = r.content[0].text.strip()
    text = re.sub(r"^```json|^```|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except Exception:
        return {"highlights": [], "actions": [], "links": []}

def encrypt(text, passphrase):
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200000)
    key = kdf.derive(passphrase.encode())
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, text.encode(), None)
    return {
        "salt": base64.b64encode(salt).decode(),
        "iv":   base64.b64encode(iv).decode(),
        "data": base64.b64encode(ct).decode(),
    }

NEWS_PROMPT = """Search the web for the most important and recent financial and economic news from the last 24 hours, covering both India and the world (markets, economy, policy, major companies, RBI/Fed, etc.).
Pick the top 6-8 stories. For each, write a 1-2 sentence summary in your OWN words (do not copy article text).
Score each 1-10 on:
- virality: how widely it is being discussed/shared right now
- credibility: reliability of the reporting sources
- importance: real financial/economic significance
Set overall = average of the three, one decimal.
Return ONLY a JSON object (no prose, no markdown fences), sorted by overall descending:
{"news":[{"headline":"...","summary":"...","region":"India or World","source":"e.g. Reuters","url":"https://...","scores":{"virality":8,"credibility":9,"importance":7},"overall":8.0}]}"""

def fetch_news():
    try:
        r = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
            messages=[{"role": "user", "content": NEWS_PROMPT}],
        )
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
        i, j = text.find("{"), text.rfind("}")
        return json.loads(text[i:j+1]).get("news", [])
    except Exception as e:
        print("News fetch failed:", e)
        return []

def main():
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    out_groups = []
    with TelegramClient(StringSession(SESSION), API_ID, API_HASH) as client:
        for g in GROUPS:
            msgs = []
            for m in client.iter_messages(g["chat"], limit=300):
                if m.date < since:
                    break
                if m.text:
                    msgs.append({"time": m.date.astimezone(IST).strftime("%-I:%M %p"),
                                 "text": m.text})
            msgs.reverse()
            s = summarize(g["name"], msgs)
            out_groups.append({
                "id": g["id"], "name": g["name"], "icon": g["icon"],
                "msgCount": len(msgs),
                "highlights": s.get("highlights", []),
                "actions": s.get("actions", []),
                "links": s.get("links", []),
                "log": msgs,
            })

    now = datetime.datetime.now(IST)
    briefing = {
        "generatedAt": now.strftime("%-I:%M %p"),
        "dateLabel": now.strftime("%A, %B %-d"),
        "groups": out_groups,
        "news": fetch_news(),
    }
    payload = encrypt(json.dumps(briefing, ensure_ascii=False), PIN)
    os.makedirs("docs", exist_ok=True)
    with open("docs/briefing.json", "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print("Wrote encrypted docs/briefing.json")

main()
