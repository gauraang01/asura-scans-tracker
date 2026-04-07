from curl_cffi import requests
from bs4 import BeautifulSoup
import json
import os
import time
import datetime
import traceback
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

# --- CONFIGURATION ---
DATA_FILE = "comic_data.json"
CHECK_INTERVAL_SECONDS = 1800 * 2 * 6 # Check every 30 minutes (1800 seconds)


DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")


# List of comics to track. 
COMICS_TO_TRACK = {
    "Eternally Regressing Knight": "https://asurascans.com/comics/eternally-regressing-knight-75e30c62",
    "Pick Me Up, Infinite Gacha": "https://asurascans.com/comics/pick-me-up-infinite-gacha-75e30c62",
    "Nano Machine": "https://asurascans.com/comics/nano-machine-75e30c62",
    "The Extra's Academy Survival Guide": "https://asurascans.com/comics/the-extras-academy-survival-guide-75e30c62",
    "The World After The End": "https://asurascans.com/comics/the-world-after-the-end-75e30c62"
}

# --- HELPER FUNCTIONS ---
def load_data():
    """Loads the saved chapter states from a JSON file."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    """Saves the current chapter states to a JSON file."""
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

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
            "color": 9519074 # A nice purple color
        }]
    }
    
    try:
        # We reuse the curl_cffi requests library here to send the payload
        response = requests.post(DISCORD_WEBHOOK_URL, json=data, impersonate="chrome")
        response.raise_for_status()
        print("   [SUCCESS] Notification sent to Discord!")
    except Exception as e:
        print(f"   [ERROR] Failed to send Discord notification: {e}")

# --- CORE SCRAPING LOGIC ---
def check_comic_update(url, comic_name):
    """Scrapes the comic page and checks if there is a new chapter."""
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Checking {comic_name}...")
    
    try:
        # We use curl_cffi to perfectly impersonate a real Chrome browser
        response = requests.get(url, impersonate="chrome", timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 1. Find the chapter list container
        chapter_list_container = soup.find("div", class_="divide-y")
        
        if not chapter_list_container:
            print(f"   [WARNING] Could not find chapter list for {comic_name}. The site's layout may have changed.")
            return

        # Find the first 'a' (link) tag inside that container
        latest_chapter_link = chapter_list_container.find("a")
        
        if not latest_chapter_link:
            print(f"   [WARNING] Could not find a chapter link inside the container for {comic_name}.")
            return

        # 2. Extract the relative URL and make it absolute
        raw_url = latest_chapter_link.get("href")
        chapter_url = f"https://asurascans.com{raw_url}" if raw_url.startswith("/") else raw_url

        # 3. Extract the title from the inner span
        title_span = latest_chapter_link.find("span", class_="font-medium")
        if not title_span:
            print(f"   [WARNING] Could not find the chapter title text for {comic_name}.")
            return
            
        # get_text(strip=True) safely ignores the hidden in the HTML
        chapter_title = title_span.get_text(strip=True) 

        # 4. Check against saved data
        data = load_data()
        saved_chapter = data.get(comic_name, "")

        if chapter_title != saved_chapter:
            # --- TERMINAL NOTIFICATION ---
            print(f"\n==================================================")
            print(f"[NEW CHAPTER] {comic_name} - {chapter_title}!")
            print(f"Read it here: {chapter_url}")
            print(f"==================================================\n")
            
            # --- DISCORD NOTIFICATION ---
            send_discord_notification(comic_name, chapter_title, chapter_url)
            
            # Update our saved data
            data[comic_name] = chapter_title
            save_data(data)
        else:
            print(f"   - No new chapters. Latest is still {chapter_title}.")

    except Exception as e:
        print(f"   [ERROR] Error checking {comic_name}: {e}")
        traceback.print_exc()

# --- MAIN EXECUTION LOOP ---
if __name__ == "__main__":
    print("Starting Comic Scraper (Discord + Multi-Tracker Edition)...")
    
    if not DISCORD_WEBHOOK_URL:
        print("WARNING: DISCORD_WEBHOOK_URL is empty! Notifications will only print to the terminal.\n")
    
    while True:
        for name, url in COMICS_TO_TRACK.items():
            check_comic_update(url, name)
            # Polite pause between checking different sites
            time.sleep(5) 
            
        print(f"\nAll checks complete. Sleeping for {CHECK_INTERVAL_SECONDS // 60} minutes...\n")
        time.sleep(CHECK_INTERVAL_SECONDS)