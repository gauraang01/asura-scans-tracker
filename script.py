from curl_cffi import requests
from bs4 import BeautifulSoup
from flask import Flask
from dotenv import load_dotenv
import threading
import json
import os
import time
import datetime
import traceback

# Load environment variables from the .env file
load_dotenv()

# --- CONFIGURATION ---
CHECK_INTERVAL_SECONDS = 1800 * 2 * 6  # 6 hours

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
JSONBIN_API_KEY = os.getenv("JSONBIN_API_KEY")
JSONBIN_BIN_ID = os.getenv("JSONBIN_BIN_ID")

# List of comics to track. 
COMICS_TO_TRACK = {
    "Eternally Regressing Knight": "https://asurascans.com/comics/eternally-regressing-knight-75e30c62",
    "Pick Me Up, Infinite Gacha": "https://asurascans.com/comics/pick-me-up-infinite-gacha-75e30c62",
    "Nano Machine": "https://asurascans.com/comics/nano-machine-75e30c62",
    "The Extra's Academy Survival Guide": "https://asurascans.com/comics/the-extras-academy-survival-guide-75e30c62",
    "The World After The End": "https://asurascans.com/comics/the-world-after-the-end-75e30c62"
}

# --- 🌐 FLASK WEB SERVER (For Render + Future UI) ---
app = Flask(__name__)

@app.route('/')
def home():
    # This keeps Render happy and will eventually be where your UI lives!
    return f"""
    <h1>Asura Scans Tracker is Online 🟢</h1>
    <p>Currently tracking {len(COMICS_TO_TRACK)} comics.</p>
    """

def run_flask():
    """Runs the Flask server on the port assigned by Render."""
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)


# --- ☁️ CLOUD STORAGE (JSONBin) ---
def load_data():
    """Loads the saved chapter states from JSONBin."""
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID:
        print("   [WARNING] Missing JSONBin credentials! Returning empty data.")
        return {}
        
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
    headers = {"X-Master-Key": JSONBIN_API_KEY}
    
    try:
        # We can use the same curl_cffi requests object
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get("record", {})
    except Exception as e:
        print(f"   [ERROR] Failed to load data from JSONBin: {e}")
        return {}

def save_data(data):
    """Saves the current chapter states back to JSONBin."""
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID:
        return
        
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
    headers = {
        "X-Master-Key": JSONBIN_API_KEY,
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.put(url, json=data, headers=headers)
        response.raise_for_status()
    except Exception as e:
        print(f"   [ERROR] Failed to save data to JSONBin: {e}")


# --- 🔔 NOTIFICATIONS ---
def send_discord_notification(comic_name, chapter_title, chapter_url):
    """Sends a rich embed message to a Discord Webhook."""
    if not DISCORD_WEBHOOK_URL:
        print("   [WARNING] Discord URL not set, skipping notification.")
        return

    data = {
        "username": "Asura Tracker",
        "embeds": [{
            "title": f"🚨 {comic_name} Updated! 🚨",
            "description": f"**{chapter_title}** has just been released!\n\n[Click here to read it]({chapter_url})",
            "color": 9519074 # Asura Scans Purple
        }]
    }
    
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=data, impersonate="chrome")
        response.raise_for_status()
        print("   [SUCCESS] Notification sent to Discord!")
    except Exception as e:
        print(f"   [ERROR] Failed to send Discord notification: {e}")


# --- 🕷️ CORE SCRAPING LOGIC ---
def check_comic_update(url, comic_name):
    """Scrapes the comic page and checks if there is a new chapter."""
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Checking {comic_name}...")
    
    try:
        response = requests.get(url, impersonate="chrome", timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        chapter_list_container = soup.find("div", class_="divide-y")
        if not chapter_list_container:
            print(f"   [WARNING] Could not find chapter list for {comic_name}. Layout may have changed.")
            return

        latest_chapter_link = chapter_list_container.find("a")
        if not latest_chapter_link:
            print(f"   [WARNING] Could not find a chapter link inside the container for {comic_name}.")
            return

        raw_url = latest_chapter_link.get("href")
        chapter_url = f"https://asurascans.com{raw_url}" if raw_url.startswith("/") else raw_url

        title_span = latest_chapter_link.find("span", class_="font-medium")
        if not title_span:
            print(f"   [WARNING] Could not find the chapter title text for {comic_name}.")
            return
            
        chapter_title = title_span.get_text(strip=True) 

        # Fetch cloud data instead of local file
        data = load_data()
        saved_chapter = data.get(comic_name, "")

        if chapter_title != saved_chapter:
            print(f"\n==================================================")
            print(f"[NEW CHAPTER] {comic_name} - {chapter_title}!")
            print(f"Read it here: {chapter_url}")
            print(f"==================================================\n")
            
            send_discord_notification(comic_name, chapter_title, chapter_url)
            
            data[comic_name] = chapter_title
            save_data(data)
        else:
            print(f"   - No new chapters. Latest is still {chapter_title}.")

    except Exception as e:
        print(f"   [ERROR] Error checking {comic_name}: {e}")
        traceback.print_exc()

def scraping_loop():
    """The infinite loop that runs in the background."""
    print("Starting Background Comic Scraper Loop...")
    
    # Initial pause to let the Flask server boot up properly
    time.sleep(3)
    
    while True:
        for name, url in COMICS_TO_TRACK.items():
            check_comic_update(url, name)
            time.sleep(5) 
            
        print(f"\nAll checks complete. Sleeping for {CHECK_INTERVAL_SECONDS // 3600} hours...\n")
        time.sleep(CHECK_INTERVAL_SECONDS)


# --- 🚀 MAIN EXECUTION ---
if __name__ == "__main__":
    if not DISCORD_WEBHOOK_URL:
        print("WARNING: DISCORD_WEBHOOK_URL is empty! Notifications will only print to the terminal.\n")
    if not JSONBIN_API_KEY or not JSONBIN_BIN_ID:
        print("WARNING: JSONBIN credentials missing! State will not be saved.\n")
        
    # 1. Start the scraping loop in a background thread
    # Daemon=True means this thread will close when the main Flask server closes
    scraper_thread = threading.Thread(target=scraping_loop, daemon=True)
    scraper_thread.start()
    
    # 2. Start the Flask web server on the main thread
    run_flask()