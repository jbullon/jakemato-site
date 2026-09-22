import json
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://api.themoviedb.org/3"
REGION = "US"
DAYS_BACK = 180
DAYS_FORWARD = 90
OUTPUT = Path("tools/movies/data/movies.json")
TOKEN = os.environ.get("TMDB_API_TOKEN", "").strip()

TYPE_NAMES = {
    1: "Premiere",
    2: "Limited theatrical",
    3: "Theatrical",
    4: "Digital",
    5: "Physical",
    6: "TV",
}

RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 5

if not TOKEN:
    raise SystemExit("TMDB_API_TOKEN is not set.")


class TMDBNotFound(Exception):
    pass


def tmdb_get(path, params=None):
    params = params or {}
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urlencode(params)

    for attempt in range(1, MAX_RETRIES + 1):
        req = Request(
            url,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "accept": "application/json",
                "User-Agent": "jakemato-movie-selector/1.0",
            },
        )

        try:
            with urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 404:
                raise TMDBNotFound(path) from exc

            if exc.code not in RETRYABLE_HTTP_CODES or attempt == MAX_RETRIES:
                raise

            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = float(retry_after) if retry_after else min(2 ** (attempt - 1), 16)
            except ValueError:
                delay = min(2 ** (attempt - 1), 16)

            print(
                f"TMDB returned HTTP {exc.code} for {path}; "
                f"retrying in {delay:g}s ({attempt}/{MAX_RETRIES})"
            )
            time.sleep(delay)
        except (URLError, TimeoutError, ConnectionResetError) as exc:
            if attempt == MAX_RETRIES:
                raise

            delay = min(2 ** (attempt - 1), 16)
            print(
                f"TMDB connection error for {path}: {exc}; "
                f"retrying in {delay}s ({attempt}/{MAX_RETRIES})"
            )
            time.sleep(delay)

    raise RuntimeError(f"TMDB request unexpectedly exhausted retries: {path}")


def fetch_genres():
    data = tmdb_get("/genre/movie/list", {"language": "en-US"})
    return {item["id"]: item["name"] for item in data.get("genres", [])}


def discover_candidates(start_date, end_date):
    ids = set()
    page = 1
    while True:
        payload = tmdb_get(
            "/discover/movie",
            {
                "include_adult": "false",
                "include_video": "false",
                "language": "en-US",
                "page": page,
                "region": REGION,
                "release_date.gte": start_date.isoformat(),
                "release_date.lte": end_date.isoformat(),
                "sort_by": "primary_release_date.asc",
                "with_release_type": "1|2|3|4|5|6",
            },
        )
        for movie in payload.get("results", []):
            ids.add(movie["id"])
        total_pages = min(int(payload.get("total_pages", 1)), 500)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.05)
    return sorted(ids)


def normalize_date(value):
    if not value:
        return None
    return value[:10]


def build_movie(movie_id, genre_map, start_date, end_date):
    details = tmdb_get(
        f"/movie/{movie_id}",
        {"append_to_response": "release_dates,external_ids", "language": "en-US"},
    )

    us_results = []
    release_dates = details.get("release_dates", {}).get("results", [])
    for region in release_dates:
        if region.get("iso_3166_1") == REGION:
            us_results = region.get("release_dates", [])
            break

    by_date = defaultdict(lambda: {"types": set(), "certifications": []})
    for release in us_results:
        release_date = normalize_date(release.get("release_date"))
        release_type = release.get("type")
        if not release_date or release_type not in TYPE_NAMES:
            continue
        if release_date < start_date.isoformat() or release_date > end_date.isoformat():
            continue
        by_date[release_date]["types"].add(release_type)
        certification = (release.get("certification") or "").strip()
        if certification:
            by_date[release_date]["certifications"].append(certification)

    events = []
    for event_date, event in sorted(by_date.items()):
        certifications = event["certifications"]
        certification = certifications[0] if certifications else "NR"
        events.append(
            {
                "date": event_date,
                "types": sorted(event["types"]),
                "certification": certification,
            }
        )

    if not events:
        return None

    return {
        "tmdb_id": details["id"],
        "title": details.get("title") or details.get("original_title") or "Untitled",
        "original_title": details.get("original_title") or "",
        "poster_path": details.get("poster_path"),
        "genres": [genre.get("name") for genre in details.get("genres", []) if genre.get("name")]
        or [genre_map.get(gid) for gid in details.get("genre_ids", []) if genre_map.get(gid)],
        "runtime": details.get("runtime") or None,
        "vote_average": details.get("vote_average") or 0,
        "vote_count": details.get("vote_count") or 0,
        "imdb_id": details.get("external_ids", {}).get("imdb_id") or details.get("imdb_id"),
        "events": events,
    }


def main():
    today = date.today()
    start_date = today - timedelta(days=DAYS_BACK)
    end_date = today + timedelta(days=DAYS_FORWARD)
    genre_map = fetch_genres()
    candidate_ids = discover_candidates(start_date, end_date)

    movies = []
    skipped_not_found = 0
    skipped_errors = 0

    print(f"Found {len(candidate_ids)} candidate movies.")

    for index, movie_id in enumerate(candidate_ids, start=1):
        try:
            movie = build_movie(movie_id, genre_map, start_date, end_date)
        except TMDBNotFound:
            skipped_not_found += 1
            print(f"Skipping TMDB movie {movie_id}: details returned 404.")
            continue
        except (HTTPError, URLError, TimeoutError, ConnectionResetError) as exc:
            skipped_errors += 1
            print(f"Skipping TMDB movie {movie_id} after retries: {exc}")
            continue

        if movie:
            movies.append(movie)

        if index % 35 == 0:
            time.sleep(0.25)

        if index % 250 == 0:
            print(
                f"Processed {index}/{len(candidate_ids)} candidates; "
                f"{len(movies)} releases retained."
            )

    movies.sort(key=lambda movie: (movie["events"][0]["date"], movie["title"].lower()))
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "days_back": DAYS_BACK,
            "days_forward": DAYS_FORWARD,
            "region": REGION,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "movie_count": len(movies),
        "skipped_not_found": skipped_not_found,
        "skipped_errors": skipped_errors,
        "movies": movies,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(movies)} movies to {OUTPUT} "
        f"({skipped_not_found} missing, {skipped_errors} transient failures skipped)."
    )


if __name__ == "__main__":
    main()
