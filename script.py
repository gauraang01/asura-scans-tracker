from curl_cffi import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, render_template_string
from dotenv import load_dotenv
import threading
import json
import os
import time
import datetime
import traceback

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
CHECK_INTERVAL_SECONDS = 1800  # 30 minutes

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
JSONBIN_API_KEY = os.getenv("JSONBIN_API_KEY")
JSONBIN_BIN_ID = os.getenv("JSONBIN_BIN_ID")

# In-memory database to prevent spamming JSONBin API limits
# Structure: { "Comic Name": {"url": "...", "latest": "..."} }
DB_CACHE = {} 
db_lock = threading.Lock() # Ensures safe reads/writes between UI and Scraper

# --- 🌐 FLASK WEB SERVER & UI ---
app = Flask(__name__)

# The HTML Frontend (Using Tailwind CSS for styling)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Asura Tracker Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style> body { background-color: #13111A; color: white; } </style>
</head>
<body class="p-8 font-sans">
    <div class="max-w-4xl mx-auto">
        <h1 class="text-3xl font-bold mb-8 text-[#913FE2]">Asura Scans Tracker</h1>
        
        <div class="bg-[#1C1924] p-6 rounded-lg mb-8 shadow-lg border border-white/10">
            <h2 class="text-xl font-semibold mb-4">Add New Comic</h2>
            <form id="addForm" class="flex gap-4">
                <input type="text" id="comicName" placeholder="Comic Name (e.g. Nano Machine)" required class="flex-1 bg-[#13111A] border border-white/20 rounded p-2 text-white outline-none focus:border-[#913FE2]">
                <input type="url" id="comicUrl" placeholder="Asura Scans URL" required class="flex-1 bg-[#13111A] border border-white/20 rounded p-2 text-white outline-none focus:border-[#913FE2]">
                <button type="submit" class="bg-[#913FE2] hover:bg-[#7c35c2] px-6 py-2 rounded font-bold transition-colors">Add</button>
            </form>
        </div>

        <div class="bg-[#1C1924] p-6 rounded-lg shadow-lg border border-white/10 mb-8">
            <h2 class="text-xl font-semibold mb-4">Currently Tracking</h2>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="border-b border-white/10 text-white/50">
                            <th class="p-2 font-medium">Name</th>
                            <th class="p-2 font-medium">Latest Chapter</th>
                            <th class="p-2 font-medium text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="comicList">
                        </tbody>
                </table>
            </div>
        </div>

        <div class="bg-red-900/20 p-6 rounded-lg border border-red-500/30">
            <h2 class="text-xl font-semibold mb-2 text-red-400">Danger Zone</h2>
            <p class="text-sm text-white/50 mb-4">This will delete all tracked comics and chapter history from the cloud.</p>
            <button onclick="clearData()" class="bg-red-600 hover:bg-red-700 px-4 py-2 rounded font-bold transition-colors">Clear All Data</button>
        </div>
    </div>

    <script>
        // Fetch and display comics
        async function loadComics() {
            const res = await fetch('/api/comics');
            const comics = await res.json();
            const tbody = document.getElementById('comicList');
            tbody.innerHTML = '';
            
            for (const [name, data] of Object.entries(comics)) {
                tbody.innerHTML += `
                    <tr class="border-b border-white/5 hover:bg-white/5">
                        <td class="p-2"><a href="${data.url}" target="_blank" class="hover:text-[#913FE2] transition-colors">${name}</a></td>
                        <td class="p-2 text-green-400">${data.latest || 'Scanning...'}</td>
                        <td class="p-2 text-right">
                            <button onclick="removeComic('${name}')" class="text-red-400 hover:text-red-300 text-sm font-semibold">Remove</button>
                        </td>
                    </tr>
                `;
            }
        }

        // Add a new comic
        document.getElementById('addForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = document.getElementById('comicName').value;
            const url = document.getElementById('comicUrl').value;
            
            await fetch('/api/comics', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name, url })
            });
            
            document.getElementById('addForm').reset();
            loadComics();
        });

        // Remove a comic
        async function removeComic(name) {
            if(confirm(`Stop tracking ${name}?`)) {
                await fetch(`/api/comics/${encodeURIComponent(name)}`, { method: 'DELETE' });
                loadComics();
            }
        }

        // Clear all data
        async function clearData() {
            if(confirm('Are you absolutely sure you want to delete all tracking data?')) {
                await fetch('/api/clear', { method: 'POST' });
                loadComics();
            }
        }

        // Initial load
        loadComics();
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/comics', methods=['GET'])
def api_get_comics():
    with db_lock:
        return jsonify(DB_CACHE)

@app.route('/api/comics', methods=['POST'])
def api_add_comic():
    data = request.json
    name, url = data.get('name'), data.get('url')
    
    with db_lock:
        DB_CACHE[name] = {"url": url, "latest": ""}
        save_data_to_cloud(DB_CACHE)
    return jsonify({"status": "success"})

@app.route('/api/comics/<name>', methods=['DELETE'])
def api_delete_comic(name):
    with db_lock:
        if name in DB_CACHE:
            del DB_CACHE[name]
            save_data_to_cloud(DB_CACHE)
    return jsonify({"status": "success"})

@app.route('/api/clear', methods=['POST'])
def api_clear_data():
    with db_lock:
        DB_CACHE.clear()
        save_data_to_cloud(DB_CACHE)
    return jsonify({"status": "success"})


# --- ☁️ CLOUD STORAGE (JSONBin) ---
def load_data_from_cloud():
    """Fetches the DB from JSONBin on startup."""
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID: return {}
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
    try:
        response = requests.get(url, headers={"X-Master-Key": JSONBIN_API_KEY})
        return response.json().get("record", {})
    except Exception as e:
        print(f"[ERROR] Failed to load from JSONBin: {e}")
        return {}

def save_data_to_cloud(data):
    """Pushes the updated DB to JSONBin."""
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID: return
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
    headers = {"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"}
    try:
        requests.put(url, json=data, headers=headers)
    except Exception as e:
        print(f"[ERROR] Failed to save to JSONBin: {e}")


# --- 🔔 NOTIFICATIONS ---
def send_discord_notification(comic_name, chapter_title, chapter_url):
    if not DISCORD_WEBHOOK_URL: return
    data = {
        "username": "Asura Tracker",
        "embeds": [{"title": f"🚨 {comic_name} Updated! 🚨", "description": f"**{chapter_title}** has just been released!\n\n[Click here to read it]({chapter_url})", "color": 9519074}]
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data, impersonate="chrome")
    except Exception:
        pass


# --- 🕷️ CORE SCRAPING LOGIC ---
def scrape_comic(comic_name, url, current_latest):
    """Scrapes a single comic and returns the new chapter title if updated."""
    try:
        response = requests.get(url, impersonate="chrome", timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        
        chapter_list = soup.find("div", class_="divide-y")
        if not chapter_list: return None
        
        latest_link = chapter_list.find("a")
        if not latest_link: return None
        
        title_span = latest_link.find("span", class_="font-medium")
        if not title_span: return None
            
        chapter_title = title_span.get_text(strip=True) 
        
        if chapter_title != current_latest:
            raw_url = latest_link.get("href")
            chapter_url = f"https://asurascans.com{raw_url}" if raw_url.startswith("/") else raw_url
            
            print(f"🎉 NEW CHAPTER: {comic_name} - {chapter_title}")
            send_discord_notification(comic_name, chapter_title, chapter_url)
            return chapter_title
            
    except Exception as e:
        print(f"❌ Error checking {comic_name}: {e}")
    return None

def scraping_loop():
    """The infinite loop that runs in the background."""
    print("Starting Background Scraper...")
    time.sleep(3) # Let Flask boot up
    
    while True:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting sweep...")
        data_changed = False
        
        # We copy the keys to a list so the dictionary doesn't change size during iteration
        with db_lock:
            comics_to_check = list(DB_CACHE.keys())
            
        for name in comics_to_check:
            with db_lock:
                # Safely get the URL and current latest chapter
                if name not in DB_CACHE: continue
                url = DB_CACHE[name].get("url")
                current_latest = DB_CACHE[name].get("latest")
                
            new_chapter = scrape_comic(name, url, current_latest)
            
            if new_chapter:
                with db_lock:
                    DB_CACHE[name]["latest"] = new_chapter
                data_changed = True
                
            time.sleep(5) # Polite pause between site pings
            
        # If any chapters updated during this sweep, save the memory cache to the cloud
        if data_changed:
            with db_lock:
                save_data_to_cloud(DB_CACHE)
                
        print(f"💤 Sweep complete. Sleeping for {CHECK_INTERVAL_SECONDS // 60} minutes.")
        time.sleep(CHECK_INTERVAL_SECONDS)


# --- 🚀 MAIN EXECUTION ---
if __name__ == "__main__":
    if not DISCORD_WEBHOOK_URL:
        print("WARNING: DISCORD_WEBHOOK_URL is empty! Notifications will only print to the terminal.\n")
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID:
        print("WARNING: JSONBIN credentials missing! State will not be saved.\n")
        
    # 1. Initialize the memory cache from the cloud
    print("Fetching existing data from JSONBin...")
    DB_CACHE = load_data_from_cloud()
    
    # --- 🛠️ SCHEMA MIGRATION FIX ---
    # Remove old string-based data from previous script versions
    keys_to_delete = [name for name, data in DB_CACHE.items() if isinstance(data, str)]
    for key in keys_to_delete:
        del DB_CACHE[key]
        
    # Auto-populate the database with your hardcoded COMICS_TO_TRACK
    db_changed = False
    for name, url in COMICS_TO_TRACK.items():
        if name not in DB_CACHE:
            DB_CACHE[name] = {"url": url, "latest": ""}
            db_changed = True
            
    # Save the corrected data back to JSONBin
    if keys_to_delete or db_changed:
        print("Updating JSONBin with new data schema...")
        save_data_to_cloud(DB_CACHE)
    # -------------------------------

    # 2. Start the scraper in a background thread
    scraper_thread = threading.Thread(target=scraping_loop, daemon=True)
    scraper_thread.start()
    
    # 3. Start the Flask UI
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)