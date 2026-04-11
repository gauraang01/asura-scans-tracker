from curl_cffi import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, render_template_string
from dotenv import load_dotenv
import threading
import os
import time
import datetime

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
NEXT_RUN_TIME = 0  # Tracks the exact timestamp of the next automated sweep

# --- 🌐 FLASK WEB SERVER & UI ---
app = Flask(__name__)

HTML_TEMPLATE = HTML_TEMPLATE = HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Asura Tracker</title>
    <link rel="icon" type="image/png" href="/static/favicon.ico">
    <script src="https://cdn.tailwindcss.com"></script>
    <style> 
        body { background-color: #13111A; color: white; } 
        .loader {
            border-top-color: #913FE2;
            animation: spinner 1.5s linear infinite;
        }
        @keyframes spinner {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body class="p-4 sm:p-8 font-sans relative min-h-screen">
    
    <div id="loadingOverlay" class="fixed inset-0 bg-black/90 z-50 hidden flex-col items-center justify-center backdrop-blur-sm transition-opacity">
        <div class="loader rounded-full border-4 border-t-4 border-white/10 h-12 w-12 mb-4"></div>
        <h2 id="loadingText" class="text-lg font-semibold text-white tracking-widest animate-pulse text-center px-4">Processing...</h2>
    </div>

    <div class="max-w-4xl mx-auto">
        
        <div class="flex flex-col md:flex-row justify-between items-center gap-4 mb-8 pt-4">
            <h1 class="text-3xl font-bold text-[#913FE2] text-center md:text-left">Asura Tracker</h1>
            
            <div class="flex flex-col items-center md:items-end w-full md:w-auto">
                <button id="sweepBtn" onclick="runManualSweep()" class="w-full md:w-auto bg-[#2b2931] hover:bg-[#3a3842] border border-white/20 px-6 py-3 md:py-2 rounded font-bold transition-all flex items-center justify-center gap-2 shadow-lg">
                    <span>🔄</span> 
                    <span>Run Sweep Now</span>
                </button>
                <span id="countdownDisplay" class="text-xs sm:text-sm text-white/40 mt-2 font-mono tracking-widest">Next scan in: --:--</span>
            </div>
        </div>
        
        <div class="bg-[#1C1924] p-5 sm:p-6 rounded-lg mb-8 shadow-lg border border-white/10">
            <h2 class="text-lg sm:text-xl font-semibold mb-4">Add New Comic</h2>
            <form id="addForm" class="flex flex-col sm:flex-row gap-3">
                <input type="text" id="comicName" placeholder="Name (e.g. Nano Machine)" required class="w-full sm:flex-1 bg-[#13111A] border border-white/10 rounded p-3 text-white outline-none focus:border-[#913FE2] transition-colors">
                <input type="url" id="comicUrl" placeholder="Asura Scans URL" required class="w-full sm:flex-1 bg-[#13111A] border border-white/10 rounded p-3 text-white outline-none focus:border-[#913FE2] transition-colors">
                <button type="submit" class="w-full sm:w-auto bg-[#913FE2] hover:bg-[#7c35c2] px-8 py-3 rounded font-bold transition-colors">Add</button>
            </form>
        </div>

        <div class="bg-[#1C1924] p-0 sm:p-6 rounded-lg shadow-lg border border-white/10 sm:border-white/10 mb-8 overflow-hidden">
            <div class="p-5 sm:p-0 border-b border-white/10 sm:border-0 flex justify-between items-center sm:block">
                <h2 class="text-lg sm:text-xl font-semibold">Currently Tracking</h2>
                <span class="sm:hidden text-xs bg-white/10 px-2 py-1 rounded text-white/60 font-mono" id="mobileCount">0</span>
            </div>
            
            <div class="w-full">
                <table class="w-full text-left border-collapse block sm:table">
                    <thead class="hidden sm:table-header-group">
                        <tr class="border-b border-white/10 text-white/50">
                            <th class="p-3 font-medium">Name</th>
                            <th class="p-3 font-medium">Latest Chapter</th>
                            <th class="p-3 font-medium text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="comicList" class="block sm:table-row-group">
                        </tbody>
                </table>
            </div>
        </div>

        <div class="bg-red-900/10 p-5 sm:p-6 rounded-lg border border-red-500/20 text-center sm:text-left mb-12">
            <h2 class="text-lg sm:text-xl font-semibold mb-2 text-red-400">Danger Zone</h2>
            <p class="text-sm text-white/50 mb-4">This will delete all tracked comics from the cloud.</p>
            <button onclick="clearData()" class="w-full sm:w-auto bg-red-500/10 text-red-400 hover:bg-red-600 hover:text-white border border-red-500/30 px-6 py-3 md:py-2 rounded font-bold transition-colors">Clear All Data</button>
        </div>
    </div>

    <script>
        const overlay = document.getElementById('loadingOverlay');
        const loadingText = document.getElementById('loadingText');
        let nextRunTimestamp = 0; 

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
                
                const count = Object.keys(comics).length;
                document.getElementById('mobileCount').innerText = count;

                if (count === 0) {
                    tbody.innerHTML = `<tr class="block sm:table-row"><td colspan="3" class="p-8 text-center text-white/40 italic block sm:table-cell">No comics being tracked. Add one above!</td></tr>`;
                    return;
                }

                for (const [name, data] of Object.entries(comics)) {
                    // Responsive Row Generation
                    tbody.innerHTML += `
                        <tr class="block sm:table-row border-b border-white/5 hover:bg-white/5 transition-colors p-4 sm:p-0">
                            
                            <td class="block sm:table-cell p-0 sm:p-3 mb-2 sm:mb-0">
                                <span class="sm:hidden text-xs text-white/40 uppercase tracking-widest font-bold block mb-1">Comic Name</span>
                                <a href="${data.url}" target="_blank" class="hover:text-[#913FE2] font-semibold sm:font-medium text-[15px] sm:text-base leading-tight inline-block transition-colors">${name}</a>
                            </td>
                            
                            <td class="flex sm:table-cell justify-between items-center sm:p-3 mb-4 sm:mb-0 bg-black/20 sm:bg-transparent p-2 rounded sm:rounded-none">
                                <span class="sm:hidden text-xs text-white/40 uppercase tracking-widest font-bold">Latest</span>
                                <span class="text-green-400 font-medium text-sm sm:text-base">${data.latest || '<span class="text-yellow-400 animate-pulse">Scanning...</span>'}</span>
                            </td>
                            
                            <td class="block sm:table-cell p-0 sm:p-3 text-right">
                                <button onclick="removeComic('${name}')" class="w-full sm:w-auto text-red-400/80 hover:text-white text-sm font-semibold transition-colors bg-red-500/10 hover:bg-red-500 py-3 sm:py-1 sm:px-3 rounded border border-red-500/20 sm:border-0">Remove Comic</button>
                            </td>
                        </tr>
                    `;
                }
            } catch (e) { console.error("Failed to load comics", e); }
        }

        async function fetchTimerStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                nextRunTimestamp = data.next_run;
            } catch (e) { console.error("Failed to fetch timer status"); }
        }

        function updateCountdownDisplay() {
            if (!nextRunTimestamp) return;
            const now = Date.now() / 1000; 
            const timeDiff = Math.max(0, nextRunTimestamp - now);

            if (timeDiff === 0) {
                document.getElementById('countdownDisplay').innerHTML = '<span class="text-[#913FE2] animate-pulse">Sweeping now...</span>';
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
            
            document.activeElement.blur(); // Hide mobile keyboard
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
            showLoader('Scanning all tracked sites...');
            try {
                await fetch('/api/sweep', { method: 'POST' });
                await loadComics(); 
            } catch (error) { alert("Sweep failed."); } 
            finally { hideLoader(); }
        }

        // Initialize App
        loadComics();
        fetchTimerStatus();
        setInterval(fetchTimerStatus, 30000); 
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

@app.route('/api/status', methods=['GET'])
def api_get_status():
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
    
    NEXT_RUN_TIME = time.time() + 3
    time.sleep(3) 
    
    while True:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting automatic sweep...")
        perform_sweep(is_manual=False)
        
        NEXT_RUN_TIME = time.time() + CHECK_INTERVAL_SECONDS
        print(f"💤 Sweep complete. Sleeping for {CHECK_INTERVAL_SECONDS // 60} minutes.")
        time.sleep(CHECK_INTERVAL_SECONDS)


# --- 🚀 MAIN EXECUTION ---
if __name__ == "__main__":
    if not DISCORD_WEBHOOK_URL: print("WARNING: DISCORD_WEBHOOK_URL is empty!\n")
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID: print("WARNING: JSONBIN credentials missing!\n")
        
    print("Fetching existing data from JSONBin...")
    DB_CACHE = load_data_from_cloud()
    
    # Schema Migration (Clean up old string-based data if any still exists)
    keys_to_delete = [name for name, data in DB_CACHE.items() if isinstance(data, str)]
    if keys_to_delete:
        for key in keys_to_delete: del DB_CACHE[key]
        print("Cleaned up old data schema from JSONBin.")
        save_data_to_cloud(DB_CACHE)

    # Start the scraper in a background thread
    threading.Thread(target=scraping_loop, daemon=True).start()
    
    # Start the Flask UI
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)