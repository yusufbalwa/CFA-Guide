import os, json, datetime, re
from zoneinfo import ZoneInfo
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
import anthropic

IST = ZoneInfo("Asia/Kolkata")

# ====== EDIT THESE: your 2 groups ======
GROUPS = [
    {"id": "g1", "name": "CFA L1 Online 2025/2026", "chat": -1003692335693},
    {"id": "g2", "name": "SSEI",  "chat": -1001456537902},
]
# =======================================

API_ID  = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION  = os.environ["TG_SESSION"]
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
    }
    os.makedirs("docs", exist_ok=True)
    with open("docs/briefing.json", "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=2)
    print("Wrote docs/briefing.json")

main()
