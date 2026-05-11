import json
import httpx


playoff_url = "https://api-web.nhle.com/v1/playoff-bracket/2026"
team_url = "https://api-web.nhle.com/v1/standings/now"


def get_playoff_data(url):
    response = httpx.get(url)
    data = response.json()
    with open("bracket.json", "w") as f:
        f.write(json.dumps(data, indent=2))


def get_team_season_data(url):
    response = httpx.get(url, follow_redirects=True)
    data = response.json()
    print(response.status_code)
    with open("team.json", "w") as f:
        f.write(json.dumps(data, indent=2))


if __name__ == "__main__":
    get_playoff_data(playoff_url)
    get_team_season_data(team_url)
