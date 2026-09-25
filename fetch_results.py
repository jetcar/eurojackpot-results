"""
Fetch Eurojackpot draw results from the Eesti Loto API and merge them into
data/eurojackpot_results.json.

Source page: https://www.eestiloto.ee/tulemused?game=eurojackpot
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request

API_BASE = "https://api.eestiloto.ee/api/v1"
GAME_CODE = "EUROJACKPOT"
PAGE_SIZE = 30  # API caps page size at 30

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "eurojackpot_results.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; eurojackpot-results/1.0)",
    "Accept": "application/json",
}


def get_json(path: str, params: dict | None = None, retries: int = 3, delay: float = 2.0):
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001
            print(f"  Attempt {attempt}/{retries} failed for {url}: {exc}", file=sys.stderr)
            if attempt < retries:
                time.sleep(delay)
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def find_game_id() -> str:
    for game in get_json("/games"):
        if (game.get("gameCode") or "").upper() == GAME_CODE:
            return game["id"]
    raise RuntimeError(f"Game {GAME_CODE} not found in /games")


def list_completed_draws(game_id: str, known_ids: set[str]) -> list[dict]:
    """List completed draws newest first; stop at the first page with nothing new."""
    draws: list[dict] = []
    page = 1
    while True:
        data = get_json("/draws", {
            "status": "DRAW_COMPLETED",
            "gameId": game_id,
            "page": page,
            "size": PAGE_SIZE,
            "sort": "dateTime:desc",
        })
        content = data.get("content") or []
        new = [d for d in content if d["id"] not in known_ids]
        draws.extend(new)
        total_pages = (data.get("page") or {}).get("totalPages") or 1
        if not new or page >= total_pages:
            return draws
        page += 1


def stage_numbers(results: dict, code: str) -> list[int]:
    for stage in results.get("stages") or []:
        if stage.get("code") == code:
            return stage.get("winningNumbers") or []
    return []


def normalize(detail: dict) -> dict:
    results = detail.get("results") or {}
    prize_classes = []
    for wc in results.get("winningClasses") or []:
        prize = (wc.get("prizes") or [{}])[0]
        prize_classes.append({
            "code": wc.get("code"),
            "name": wc.get("name"),
            "amount_cents": prize.get("amount"),
            "currency": prize.get("currency"),
            "winners": wc.get("totalWinningCombinationCount"),
        })
    return {
        "id": detail["id"],
        "number": detail.get("number"),
        "date_time": detail.get("dateTime"),
        "main_numbers": stage_numbers(results, "MAIN-NUMBERS"),
        "euro_numbers": stage_numbers(results, "ADDITIONAL-NUMBERS"),
        "prize_classes": prize_classes,
        "info": (detail.get("metadata") or {}).get("info"),
    }


def load_existing() -> list[dict]:
    if not os.path.exists(OUTPUT_FILE):
        return []
    with open(OUTPUT_FILE, encoding="utf-8") as fh:
        return json.load(fh).get("draws") or []


def save(draws: list[dict]) -> None:
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    draws.sort(key=lambda d: d["date_time"] or "", reverse=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"total_draws": len(draws), "draws": draws}, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def main() -> None:
    existing = load_existing()
    known_ids = {d["id"] for d in existing}
    game_id = find_game_id()
    listed = list_completed_draws(game_id, known_ids)
    print(f"Existing draws: {len(existing)}, new draws: {len(listed)}")

    new_draws = []
    for item in listed:
        detail = get_json(f"/draws/{item['id']}")
        if not detail.get("published", True):
            continue
        draw = normalize(detail)
        if not draw["main_numbers"]:
            continue
        new_draws.append(draw)
        print(f"  #{draw['number']} {draw['date_time']}: {draw['main_numbers']} + {draw['euro_numbers']}")

    if new_draws or not os.path.exists(OUTPUT_FILE):
        save(existing + new_draws)


if __name__ == "__main__":
    main()
