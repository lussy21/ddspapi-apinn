import os
import requests

API_KEY = os.environ["APINN_API_KEY"]

url = "https://api.apinn.io/api/board"

params = {
    "sport_id": 29,
        "live": 0,
            "with_odds": 1,
                "limit": 10
                }

                headers = {
                    "X-API-Key": API_KEY
                    }

                    response = requests.get(
                        url,
                            headers=headers,
                                params=params,
                                    timeout=30
                                    )

                                    response.raise_for_status()
                                    matches = response.json()

                                    print("=== APINN SOCCER TEST ===")

                                    for match in matches:
                                        odds = match.get("odds") or {}
                                            moneyline = odds.get("moneyline") or {}

                                                print(
                                                        match.get("starts"),
                                                                "|",
                                                                        match.get("runner_home"),
                                                                                "vs",
                                                                                        match.get("runner_away"),
                                                                                                "| 1:",
                                                                                                        moneyline.get("odds1"),
                                                                                                                "| X:",
                                                                                                                        moneyline.get("odds0"),
                                                                                                                                "| 2:",
                                                                                                                                        moneyline.get("odds2"),
                                                                                                                                                "| Event:",
                                                                                                                                                        match.get("event_id")
                                                                                                                                                            )