import json
import httpx


url = "https://api-web.nhle.com/v1/playoff-bracket/2026"


def get_playoff_data(url):
    response = httpx.get(url)
    data = response.json()
    with open("bracket.json", "w") as f:
        f.write(json.dumps(data, indent=2))


if __name__ == "__main__":
    get_playoff_data(url)
