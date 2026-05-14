import json
import httpx
from datetime import datetime, timedelta

current_day = datetime.now().strftime("%Y-%m-%d")
yesterday = datetime.now() - timedelta(days=1)
yesterday = yesterday.strftime("%Y-%m-%d")

BASE = "https://api-web.nhle.com/v1/"
URLS = {
    "playoff": f"{BASE}playoff-bracket/2026",
    "teams": f"{BASE}standings/now",
    "schedule": f"{BASE}schedule/2026-05-11", 
    "scoreboard": f"{BASE}scoreboard/now",
    "today_scores": f"{BASE}score/{current_day}",
    "yesterday_scores": f"{BASE}score/{yesterday}"
}

def get_data(url, filename):
    response = httpx.get(url, follow_redirects=True)
    data = response.json()
    with open(f"{filename}.json", "w") as f:
        f.write(json.dumps(data, indent=2))

if __name__ == "__main__":
    for filename, url in URLS.items():
        get_data(url, filename)
