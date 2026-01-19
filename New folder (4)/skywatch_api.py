import sqlite3
import feedparser
import threading
import time
import schedule
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI

app = Flask(__name__)
CORS(app)

DB_NAME = "skywatch_v2.db"

# --- CONFIGURATION ---
# PASTE YOUR NEW OPENAI KEY HERE
OPENAI_API_KEY = "YOUR_OPENAI_KEY_HERE" 

# Initialize AI Client
try:
    client = OpenAI(api_key=OPENAI_API_KEY)
except:
    client = None

# --- SOURCE LIBRARY ---
SOURCE_LIBRARY = {
    "AIR_FORCE": [
        {"id": "janes_air", "name": "Janes Air Platforms", "url": "https://www.janes.com/feeds/news", "enabled": True},
        {"id": "flight_global", "name": "FlightGlobal Defense", "url": "https://www.flightglobal.com/rss/defence", "enabled": True},
    ],
    "NAVAL": [
        {"id": "naval_news", "name": "Naval News", "url": "https://www.navalnews.com/feed/", "enabled": True},
    ],
    "CYBER_INTEL": [
        {"id": "hacker_news", "name": "The Hacker News", "url": "https://thehackernews.com/feeds/posts/default", "enabled": True},
        {"id": "threat_post", "name": "ThreatPost", "url": "https://threatpost.com/feed/", "enabled": True},
    ],
    "GEOPOLITICS": [
        {"id": "def_one", "name": "Defense One", "url": "https://www.defenseone.com/rss/all/", "enabled": True},
        {"id": "breaking_def", "name": "Breaking Defense", "url": "https://breakingdefense.com/feed/", "enabled": True},
    ],
    "REGIONAL": [
        {"id": "asia_def", "name": "Asia Pacific Defense", "url": "https://www.asiapacificdefensejournal.com/feeds/posts/default", "enabled": True},
        {"id": "global_times", "name": "Global Times (Mil)", "url": "https://www.globaltimes.cn/rss/military.xml", "enabled": True},
    ]
}

USER_KEYWORDS = ["J-35", "Pakistan", "Stealth", "Cyber", "Drone", "Nuclear", "PAF"]

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS intel (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_name TEXT,
        category TEXT,
        title TEXT UNIQUE,
        link TEXT,
        summary TEXT,
        matched_keyword TEXT,
        timestamp TEXT
    )''')
    conn.commit()
    conn.close()

# --- ENGINE ---
def scan_feed(source_config, category):
    if not source_config['enabled']:
        return
    try:
        feed = feedparser.parse(source_config['url'])
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        for entry in feed.entries:
            text_blob = (entry.title + " " + entry.get('summary', '')).lower()
            for keyword in USER_KEYWORDS:
                if keyword.lower() in text_blob:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    try:
                        c.execute('''INSERT INTO intel (source_name, category, title, link, summary, matched_keyword, timestamp)
                                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                  (source_config['name'], category, entry.title, entry.link, entry.get('summary', '')[:200], keyword, now))
                        conn.commit()
                        print(f"[+] Match: {keyword} -> {entry.title[:30]}...")
                    except sqlite3.IntegrityError:
                        pass 
                    break 
        conn.close()
    except Exception as e:
        print(f"Error scanning {source_config['name']}: {e}")

def run_full_scan():
    print("--- Starting Global Scan ---")
    with ThreadPoolExecutor(max_workers=10) as executor:
        for category, sources in SOURCE_LIBRARY.items():
            for source in sources:
                executor.submit(scan_feed, source, category)

def scheduler_loop():
    schedule.every(10).minutes.do(run_full_scan)
    run_full_scan()
    while True:
        schedule.run_pending()
        time.sleep(1)

# --- API ENDPOINTS ---
@app.route('/api/intel', methods=['GET'])
def get_intel():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM intel ORDER BY id DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    data = []
    for r in rows:
        data.append({"id": r[0], "source": r[1], "category": r[2], "title": r[3], "link": r[4], "summary": r[5], "keyword": r[6], "time": r[7]})
    return jsonify(data)

@app.route('/api/config', methods=['GET', 'POST'])
def manage_config():
    global USER_KEYWORDS, SOURCE_LIBRARY
    if request.method == 'POST':
        data = request.json
        if 'keywords' in data: USER_KEYWORDS = data['keywords']
        if 'sources' in data:
            incoming = data['sources']
            for cat in SOURCE_LIBRARY:
                for src in SOURCE_LIBRARY[cat]:
                    if src['id'] in incoming: src['enabled'] = incoming[src['id']]
        return jsonify({"status": "updated"})
    return jsonify({"keywords": USER_KEYWORDS, "sources": SOURCE_LIBRARY})

@app.route('/api/scan', methods=['POST'])
def trigger_scan():
    threading.Thread(target=run_full_scan).start()
    return jsonify({"status": "scan_started"})

@app.route('/api/generate_post', methods=['POST'])
def generate_post():
    data = request.json
    title = data.get('title')
    summary = data.get('summary')

    if not client:
        return jsonify({"error": "API Key missing"}), 500

    prompt = (
        f"Act as a defense analyst. Rewrite this news into a viral LinkedIn/Twitter post. "
        f"Make it engaging, professional, and exciting. Use bullet points if needed. "
        f"Include 3 relevant hashtags. \n\n"
        f"News Title: {title}\n"
        f"Summary: {summary}"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150
        )
        return jsonify({"content": response.choices[0].message.content.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    init_db()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    print("SKYWATCH API LIVE ON PORT 5000")
    app.run(port=5000)