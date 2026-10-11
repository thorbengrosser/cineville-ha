#!/usr/bin/env python3
"""Spike: how well can Cineville films be matched to IMDb / Rotten Tomatoes ratings?

Pipeline per Cineville production:
  1. TMDB search by (German) title + releaseYear, scored by title and year, with directors as tiebreaker
  2. TMDB external_ids -> IMDb ID
  3. OMDb by IMDb ID -> imdbRating + Rotten Tomatoes

Reads TMDB_API_KEY / OMDB_API_KEY from .env in the repo root. Stdlib only.
Usage: python3 tools/ratings_spike.py [city] [days]      (defaults: hamburg 7)
"""
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def http_json(url, body=None):
    headers = {"Accept": "application/json", "User-Agent": "cineville-ha-spike"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# Letters that NFKD does not decompose into an ASCII base letter
_TRANSLIT = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ß": "ss",
                           "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ı": "i"})


def norm(title):
    """Lowercase, strip accents/punctuation and a trailing '(2026)'-style year."""
    title = re.sub(r"\s*\(\d{4}\)\s*$", "", title or "").translate(_TRANSLIT)
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def cineville_productions(city, days):
    now = datetime.now(timezone.utc)
    body = {
        "event": {
            "isHidden": {"eq": False},
            "startDate": {"gte": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                          "lt": (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")},
            "venue": {"collection": {"cities": {"in": [city]}}},
        },
        "sort": {"title": "asc"},
        "page": {"limit": 1000},
    }
    data = http_json("https://api.cineville.de/productions/search", body)
    return data["_embedded"]["productions"]


class Tmdb:
    def __init__(self, key):
        self.key = key

    def get(self, path, **params):
        params["api_key"] = self.key
        return http_json(f"https://api.themoviedb.org/3{path}?{urllib.parse.urlencode(params)}")

    def directors(self, movie_id):
        crew = self.get(f"/movie/{movie_id}/credits").get("crew", [])
        return {norm(c["name"]) for c in crew if c.get("job") == "Director"}

    def match(self, title, year, directors):
        """Return (tmdb_movie, reason) or (None, reason)."""
        query = re.sub(r"\s*\(\d{4}\)\s*$", "", title)
        candidates = []
        for params in ({"year": year} if year else None, {}):
            if params is None:
                continue
            res = self.get("/search/movie", query=query, language="de-DE", include_adult="false", **params)
            candidates = res.get("results", [])[:8]
            if candidates:
                break
        if not candidates:
            return None, "no TMDB results"

        want_title, want_dirs = norm(title), {norm(d) for d in directors or []}
        scored = []
        for c in candidates:
            score = 0
            if want_title in (norm(c.get("title")), norm(c.get("original_title"))):
                score += 3
            c_year = int(c["release_date"][:4]) if c.get("release_date") else None
            if year and c_year:
                score += 2 if c_year == year else (1 if abs(c_year - year) == 1 else -2)
            scored.append([score, c])
        scored.sort(key=lambda x: (-x[0], -x[1].get("popularity", 0)))

        # Director check on the top few candidates: confirms a match or breaks a tie
        if want_dirs:
            for entry in scored[:3]:
                if self.directors(entry[1]["id"]) & want_dirs:
                    entry[0] += 3
            scored.sort(key=lambda x: (-x[0], -x[1].get("popularity", 0)))

        best_score, best = scored[0]
        if best_score >= 4:
            return best, f"score {best_score}"
        return None, f"best score {best_score} ({best.get('title')} {best.get('release_date', '')[:4]})"


def main():
    city = sys.argv[1] if len(sys.argv) > 1 else "hamburg"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    env = load_env()
    tmdb = Tmdb(env["TMDB_API_KEY"])
    omdb_key = env["OMDB_API_KEY"]

    productions = cineville_productions(city, days)
    print(f"{len(productions)} productions in {city}, next {days} days\n")

    rows, stats = [], {"matched": 0, "imdb_rating": 0, "rt": 0, "no_match": 0}
    for p in productions:
        attrs = p.get("attributes", {})
        title, year, dirs = p["title"], attrs.get("releaseYear"), attrs.get("directors") or []
        movie, reason = tmdb.match(title, year, dirs)
        row = {"title": title, "year": year, "reason": reason}
        if movie:
            stats["matched"] += 1
            imdb_id = tmdb.get(f"/movie/{movie['id']}/external_ids").get("imdb_id")
            row.update(tmdb=f"{movie.get('original_title')} ({movie.get('release_date', '')[:4]})", imdb=imdb_id)
            if imdb_id:
                o = http_json(f"https://www.omdbapi.com/?i={imdb_id}&apikey={omdb_key}")
                if o.get("imdbRating") not in (None, "N/A"):
                    row["imdbRating"] = o["imdbRating"]
                    stats["imdb_rating"] += 1
                rt = next((r["Value"] for r in o.get("Ratings", []) if r["Source"] == "Rotten Tomatoes"), None)
                if rt:
                    row["rt"] = rt
                    stats["rt"] += 1
        else:
            stats["no_match"] += 1
        rows.append(row)
        mark = "✓" if movie else "✗"
        extra = f"→ {row.get('tmdb')}  {row.get('imdb') or '-'}  IMDb {row.get('imdbRating', '-')}  RT {row.get('rt', '-')}" \
            if movie else f"({reason})"
        print(f"{mark} {title} [{year}]  {extra}")

    n = len(productions) or 1
    print(f"\nTMDB match:        {stats['matched']}/{len(productions)} ({100 * stats['matched'] // n}%)")
    print(f"IMDb rating found: {stats['imdb_rating']}/{len(productions)} ({100 * stats['imdb_rating'] // n}%)")
    print(f"Rotten Tomatoes:   {stats['rt']}/{len(productions)} ({100 * stats['rt'] // n}%)")


if __name__ == "__main__":
    main()
