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

# Database & State
DB_CACHE = {} 
db_lock = threading.Lock() 
NEXT_RUN_TIME = 0  # <--- NEW: Tracks the exact timestamp of the next sweep

COMICS_TO_TRACK = {
    "Eternally Regressing Knight": "https://asurascans.com/comics/eternally-regressing-knight-75e30c62",
    "Pick Me Up, Infinite Gacha": "https://asurascans.com/comics/pick-me-up-infinite-gacha-75e30c62",
    "Nano Machine": "https://asurascans.com/comics/nano-machine-75e30c62",
    "The Extra's Academy Survival Guide": "https://asurascans.com/comics/the-extras-academy-survival-guide-75e30c62",
    "The World After The End": "https://asurascans.com/comics/the-world-after-the-end-75e30c62"
}

# --- 🌐 FLASK WEB SERVER & UI ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Asura Tracker Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style> 
        body { background-color: #13111A; color: white; } 
        .loader {
            border-top-color: #913FE2;
            -webkit-animation: spinner 1.5s linear infinite;
            animation: spinner 1.5s linear infinite;
        }
        @keyframes spinner {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body class="p-8 font-sans relative min-h-screen">
    
    <div id="loadingOverlay" class="fixed inset-0 bg-black/80 z-50 hidden flex-col items-center justify-center backdrop-blur-sm transition-opacity">
        <div class="loader ease-linear rounded-full border-4 border-t-4 border-white/20 h-16 w-16 mb-4"></div>
        <h2 id="loadingText" class="text-xl font-semibold text-white tracking-widest animate-pulse">Processing...</h2>
    </div>

    <div class="max-w-4xl mx-auto">
        <div class="flex justify-between items-center mb-8">
            <h1 class="text-3xl font-bold text-[#913FE2]">Asura Scans Tracker</h1>
            
            <div class="flex flex-col items-end">
                <button id="sweepBtn" onclick="runManualSweep()" class="bg-[#2b2931] hover:bg-[#3a3842] border border-white/20 px-4 py-2 rounded font-bold transition-all flex items-center gap-2 shadow-lg">
                    <span>🔄</span> 
                    <span>Run Sweep Now</span>
                </button>
                <span id="countdownDisplay" class="text-sm text-white/40 mt-2 font-mono tracking-widest">Next scan in: --:--</span>
            </div>
        </div>
        
        <div class="bg-[#1C1924] p-6 rounded-lg mb-8 shadow-lg border border-white/10">
            <h2 class="text-xl font-semibold mb-4">Add New Comic</h2>
            <form id="addForm" class="flex gap-4">
                <input type="text" id="comicName" placeholder="Comic Name (e.g. Nano Machine)" required class="flex-1 bg-[#13111A] border border-white/20 rounded p-2 text-white outline-none focus:border-[#913FE2] transition-colors">
                <input type="url" id="comicUrl" placeholder="Asura Scans URL" required class="flex-1 bg-[#13111A] border border-white/20 rounded p-2 text-white outline-none focus:border-[#913FE2] transition-colors">
                <button type="submit" class="bg-[#913FE2] hover:bg-[#7c35c2] px-6 py-2 rounded font-bold transition-colors shadow-lg shadow-[#913FE2]/20">Add</button>
            </form>
        </div>

        <div class="bg-[#1C1924] p-6 rounded-lg shadow-lg border border-white/10 mb-8">
            <h2 class="text-xl font-semibold mb-4">Currently Tracking</h2>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="border-b border-white/10 text-white/50">
                            <th class="p-3 font-medium">Name</th>
                            <th class="p-3 font-medium">Latest Chapter</th>
                            <th class="p-3 font-medium text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="comicList">
                        </tbody>
                </table>
            </div>
        </div>

        <div class="bg-red-900/10 p-6 rounded-lg border border-red-500/20">
            <h2 class="text-xl font-semibold mb-2 text-red-400">Danger Zone</h2>
            <p class="text-sm text-white/50 mb-4">This will delete all tracked comics and chapter history from the cloud.</p>
            <button onclick="clearData()" class="bg-red-500/20 text-red-400 hover:bg-red-600 hover:text-white border border-red-500/50 px-4 py-2 rounded font-bold transition-colors">Clear All Data</button>
        </div>
    </div>

    <script>
        const overlay = document.getElementById('loadingOverlay');
        const loadingText = document.getElementById('loadingText');
        let nextRunTimestamp = 0; // NEW: Holds the target time from the server

        function showLoader(message) {
            loadingText.innerText = message;
            overlay.classList.remove('hidden');
            overlay.classList.add('flex');
        }

        function hideLoader() {
            overlay.classList.add('hidden');
            overlay.classList.remove('flex');
        }

        async function loadComics() {
            try {
                const res = await fetch('/api/comics');
                const comics = await res.json();
                const tbody = document.getElementById('comicList');
                tbody.innerHTML = '';
                
                if (Object.keys(comics).length === 0) {
                    tbody.innerHTML = `<tr><td colspan="3" class="p-4 text-center text-white/40 italic">No comics being tracked. Add one above!</td></tr>`;
                    return;
                }

                for (const [name, data] of Object.entries(comics)) {
                    tbody.innerHTML += `
                        <tr class="border-b border-white/5 hover:bg-white/5 transition-colors">
                            <td class="p-3"><a href="${data.url}" target="_blank" class="hover:text-[#913FE2] font-medium transition-colors">${name}</a></td>
                            <td class="p-3 text-green-400 font-medium">${data.latest || '<span class="text-yellow-400 animate-pulse">Scanning...</span>'}</td>
                            <td class="p-3 text-right">
                                <button onclick="removeComic('${name}')" class="text-red-400/70 hover:text-red-400 text-sm font-semibold transition-colors bg-red-400/10 px-3 py-1 rounded">Remove</button>
                            </td>
                        </tr>
                    `;
                }
            } catch (e) { console.error("Failed to load comics", e); }
        }

        // --- NEW: Timer Logic ---
        async function fetchTimerStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                nextRunTimestamp = data.next_run;
            } catch (e) { console.error("Failed to fetch timer status"); }
        }

        function updateCountdownDisplay() {
            if (!nextRunTimestamp) return;

            // Get current time in seconds (matching Python's time.time())
            const now = Date.now() / 1000; 
            const timeDiff = Math.max(0, nextRunTimestamp - now);

            if (timeDiff === 0) {
                document.getElementById('countdownDisplay').innerHTML = '<span class="text-[#913FE2] animate-pulse">Sweeping now...</span>';
                
                // If the sweep just started, refetch data in 15 seconds to show new chapters
                if (!window.sweepReloadScheduled) {
                    window.sweepReloadScheduled = true;
                    setTimeout(() => {
                        loadComics();
                        fetchTimerStatus();
                        window.sweepReloadScheduled = false;
                    }, 15000);
                }
                return;
            }

            const mins = Math.floor(timeDiff / 60).toString().padStart(2, '0');
            const secs = Math.floor(timeDiff % 60).toString().padStart(2, '0');
            document.getElementById('countdownDisplay').innerText = `Next scan in: ${mins}:${secs}`;
        }

        document.getElementById('addForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = document.getElementById('comicName').value;
            const url = document.getElementById('comicUrl').value;
            showLoader(`Adding ${name}...`);
            try {
                await fetch('/api/comics', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ name, url }) });
                document.getElementById('addForm').reset();
                await loadComics();
                fetch('/api/sweep', { method: 'POST' }).then(() => loadComics());
            } finally { hideLoader(); }
        });

        async function removeComic(name) {
            if(confirm(`Stop tracking ${name}?`)) {
                showLoader(`Removing ${name}...`);
                try {
                    await fetch(`/api/comics/${encodeURIComponent(name)}`, { method: 'DELETE' });
                    await loadComics();
                } finally { hideLoader(); }
            }
        }

        async function clearData() {
            if(confirm('Are you absolutely sure you want to delete ALL tracking data?')) {
                showLoader('Wiping database...');
                try {
                    await fetch('/api/clear', { method: 'POST' });
                    await loadComics();
                } finally { hideLoader(); }
            }
        }

        async function runManualSweep() {
            showLoader('Scanning all tracked sites for new chapters...');
            try {
                await fetch('/api/sweep', { method: 'POST' });
                await loadComics(); 
            } catch (error) { alert("Sweep failed. Check the server logs."); } 
            finally { hideLoader(); }
        }

        // Initialize App
        loadComics();
        fetchTimerStatus();
        
        // Keep syncing timer from server every 30 seconds
        setInterval(fetchTimerStatus, 30000); 
        // Update the visual countdown every 1 second
        setInterval(updateCountdownDisplay, 1000); 
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/comics', methods=['GET'])
def api_get_comics():
    with db_lock: return jsonify(DB_CACHE)

# --- NEW ROUTE: Server Status & Timer ---
@app.route('/api/status', methods=['GET'])
def api_get_status():
    """Returns the Unix timestamp of when the next automated sweep will happen."""
    return jsonify({"next_run": NEXT_RUN_TIME})

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

@app.route('/api/sweep', methods=['POST'])
def api_run_sweep():
    print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] --- MANUAL SWEEP TRIGGERED BY UI ---")
    perform_sweep(is_manual=True)
    return jsonify({"status": "success"})


# --- ☁️ CLOUD STORAGE (JSONBin) ---
def load_data_from_cloud():
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID: return {}
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
    try:
        response = requests.get(url, headers={"X-Master-Key": JSONBIN_API_KEY})
        return response.json().get("record", {})
    except Exception as e: return {}

def save_data_to_cloud(data):
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID: return
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
    headers = {"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"}
    try: requests.put(url, json=data, headers=headers)
    except Exception as e: pass


# --- 🔔 NOTIFICATIONS ---
def send_discord_notification(comic_name, chapter_title, chapter_url):
    if not DISCORD_WEBHOOK_URL: return
    data = {
        "username": "Asura Tracker",
        "embeds": [{"title": f"🚨 {comic_name} Updated! 🚨", "description": f"**{chapter_title}** has just been released!\n\n[Click here to read it]({chapter_url})", "color": 9519074}]
    }
    try: requests.post(DISCORD_WEBHOOK_URL, json=data, impersonate="chrome")
    except Exception: pass


# --- 🕷️ CORE SCRAPING LOGIC ---
def scrape_comic(comic_name, url, current_latest):
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
    except Exception as e: print(f"❌ Error checking {comic_name}: {e}")
    return None

def perform_sweep(is_manual=False):
    data_changed = False
    with db_lock: comics_to_check = list(DB_CACHE.keys())
        
    for name in comics_to_check:
        with db_lock:
            if name not in DB_CACHE: continue
            url = DB_CACHE[name].get("url")
            current_latest = DB_CACHE[name].get("latest")
            
        new_chapter = scrape_comic(name, url, current_latest)
        if new_chapter:
            with db_lock: DB_CACHE[name]["latest"] = new_chapter
            data_changed = True
            
        time.sleep(1 if is_manual else 5) 
        
    if data_changed:
        with db_lock: save_data_to_cloud(DB_CACHE)

def scraping_loop():
    global NEXT_RUN_TIME
    print("Starting Background Scraper...")
    
    # 3 second delay on initial boot up
    NEXT_RUN_TIME = time.time() + 3
    time.sleep(3) 
    
    while True:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting automatic sweep...")
        perform_sweep(is_manual=False)
        
        # Calculate exactly when the next sweep will happen
        NEXT_RUN_TIME = time.time() + CHECK_INTERVAL_SECONDS
        print(f"💤 Sweep complete. Sleeping for {CHECK_INTERVAL_SECONDS // 60} minutes.")
        time.sleep(CHECK_INTERVAL_SECONDS)


# --- 🚀 MAIN EXECUTION ---
if __name__ == "__main__":
    if not DISCORD_WEBHOOK_URL: print("WARNING: DISCORD_WEBHOOK_URL is empty!\n")
        
    print("Fetching existing data from JSONBin...")
    DB_CACHE = load_data_from_cloud()
    
    # Schema Migration / Auto-Populate
    keys_to_delete = [name for name, data in DB_CACHE.items() if isinstance(data, str)]
    for key in keys_to_delete: del DB_CACHE[key]
        
    db_changed = False
    for name, url in COMICS_TO_TRACK.items():
        if name not in DB_CACHE:
            DB_CACHE[name] = {"url": url, "latest": ""}
            db_changed = True
            
    if keys_to_delete or db_changed:
        save_data_to_cloud(DB_CACHE)

    # Start the scraper in a background thread
    threading.Thread(target=scraping_loop, daemon=True).start()
    
    # Start the Flask UI
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)