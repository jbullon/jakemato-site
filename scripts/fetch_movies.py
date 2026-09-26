import gzip
import io
import json
import os
import random
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
IMDB_RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"

TYPE_NAMES = {
    1: "Premiere",
    2: "Limited theatrical",
    3: "Theatrical",
    4: "Digital",
    5: "Physical",
    6: "TV",
}

JAKE_PICK_SEEDS = [
    ("Terrifier", 2016),
    ("No Country for Old Men", 2007),
    ("The Dark Knight", 2008),
    ("The Backrooms", 2022),
    ("The Coffee Table", 2022),
    ("Men Behind the Sun", 1988),
    ("The Dictator", 2012),
    ("Borat", 2006),
]

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
                "User-Agent": "jakemato-movie-selector/2.0",
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


def choose_trailer(videos):
    trailers = [
        video
        for video in videos or []
        if video.get("site") == "YouTube"
        and video.get("type") == "Trailer"
        and video.get("key")
    ]
    if not trailers:
        return None

    trailers.sort(
        key=lambda video: (
            bool(video.get("official")),
            video.get("iso_639_1") == "en",
            video.get("published_at") or "",
        ),
        reverse=True,
    )
    return trailers[0]["key"]


def build_movie(movie_id, genre_map, start_date, end_date):
    details = tmdb_get(
        f"/movie/{movie_id}",
        {
            "append_to_response": "release_dates,external_ids,videos",
            "language": "en-US",
            "include_video_language": "en,null",
        },
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
        "original_language": details.get("original_language") or "",
        "poster_path": details.get("poster_path"),
        "genres": [genre.get("name") for genre in details.get("genres", []) if genre.get("name")]
        or [genre_map.get(gid) for gid in details.get("genre_ids", []) if genre_map.get(gid)],
        "runtime": details.get("runtime") or None,
        "vote_average": details.get("vote_average") or 0,
        "vote_count": details.get("vote_count") or 0,
        "imdb_id": details.get("external_ids", {}).get("imdb_id") or details.get("imdb_id"),
        "trailer_youtube_key": choose_trailer(details.get("videos", {}).get("results", [])),
        "events": events,
    }


def resolve_seed_movie(title, year):
    payload = tmdb_get(
        "/search/movie",
        {
            "query": title,
            "year": year,
            "include_adult": "false",
            "language": "en-US",
            "page": 1,
        },
    )
    results = payload.get("results", [])
    if not results:
        return None

    normalized = title.casefold()
    exact = [
        item
        for item in results
        if (item.get("title") or "").casefold() == normalized
        or (item.get("original_title") or "").casefold() == normalized
    ]
    return (exact or results)[0]


def fetch_pick_detail(movie_id, genre_map):
    details = tmdb_get(
        f"/movie/{movie_id}",
        {"append_to_response": "external_ids", "language": "en-US"},
    )
    if details.get("adult"):
        return None

    return {
        "tmdb_id": details["id"],
        "title": details.get("title") or details.get("original_title") or "Untitled",
        "original_title": details.get("original_title") or "",
        "original_language": details.get("original_language") or "",
        "poster_path": details.get("poster_path"),
        "genres": [genre.get("name") for genre in details.get("genres", []) if genre.get("name")]
        or [genre_map.get(gid) for gid in details.get("genre_ids", []) if genre_map.get(gid)],
        "runtime": details.get("runtime") or None,
        "vote_average": details.get("vote_average") or 0,
        "vote_count": details.get("vote_count") or 0,
        "imdb_id": details.get("external_ids", {}).get("imdb_id") or details.get("imdb_id"),
    }


def build_jakes_picks(movies, genre_map, limit=40):
    existing_by_tmdb = {movie["tmdb_id"]: movie for movie in movies}
    seed_ids = set()
    candidate_scores = defaultdict(float)
    candidate_seed_hits = defaultdict(set)

    for seed_title, seed_year in JAKE_PICK_SEEDS:
        try:
            seed = resolve_seed_movie(seed_title, seed_year)
        except (HTTPError, URLError, TimeoutError, ConnectionResetError) as exc:
            print(f"Jake's Picks seed failed: {seed_title}: {exc}")
            continue

        if not seed:
            print(f"Jake's Picks seed not found: {seed_title} ({seed_year})")
            continue

        seed_id = seed["id"]
        seed_ids.add(seed_id)

        try:
            recs = tmdb_get(
                f"/movie/{seed_id}/recommendations",
                {"language": "en-US", "page": 1},
            ).get("results", [])
        except (HTTPError, URLError, TimeoutError, ConnectionResetError, TMDBNotFound) as exc:
            print(f"Jake's Picks recommendations failed for {seed_title}: {exc}")
            continue

        for rank, recommendation in enumerate(recs[:20], start=1):
            candidate_id = recommendation.get("id")
            if not candidate_id or candidate_id in seed_ids or recommendation.get("adult"):
                continue
            candidate_scores[candidate_id] += max(1, 24 - rank)
            candidate_seed_hits[candidate_id].add(seed_title)

    for seed_id in seed_ids:
        candidate_scores.pop(seed_id, None)
        candidate_seed_hits.pop(seed_id, None)

    rng = random.Random(f"jakes-picks-{date.today().isoformat()}")
    weighted = []
    for movie_id, base_score in candidate_scores.items():
        hit_bonus = 1 + (0.65 * max(0, len(candidate_seed_hits[movie_id]) - 1))
        weight = max(1.0, base_score * hit_bonus)
        random_key = rng.random() ** (1.0 / weight)
        weighted.append((random_key, movie_id))

    weighted.sort(reverse=True)
    selected_ids = [movie_id for _, movie_id in weighted[: max(limit * 2, limit)]]

    picks = []
    for movie_id in selected_ids:
        movie = existing_by_tmdb.get(movie_id)
        if movie:
            pick = {
                key: movie.get(key)
                for key in (
                    "tmdb_id",
                    "title",
                    "original_title",
                    "original_language",
                    "poster_path",
                    "genres",
                    "runtime",
                    "vote_average",
                    "vote_count",
                    "imdb_id",
                )
            }
        else:
            try:
                pick = fetch_pick_detail(movie_id, genre_map)
            except (HTTPError, URLError, TimeoutError, ConnectionResetError, TMDBNotFound) as exc:
                print(f"Skipping Jake's Pick {movie_id}: {exc}")
                continue

        if not pick or not pick.get("poster_path") or not (pick.get("imdb_id") or "").startswith("tt"):
            continue

        pick["seed_matches"] = sorted(candidate_seed_hits[movie_id])
        pick["recommendation_score"] = round(candidate_scores[movie_id], 2)
        picks.append(pick)

        if len(picks) >= limit:
            break

    print(f"Built {len(picks)} Jake's Picks from {len(seed_ids)} resolved seeds.")
    return picks


def previous_imdb_ratings():
    if not OUTPUT.exists():
        return {}

    try:
        old = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    ratings = {}
    for movie in list(old.get("movies", [])) + list(old.get("jakes_picks", [])):
        imdb_id = movie.get("imdb_id")
        if not imdb_id:
            continue
        if movie.get("imdb_rating") is not None:
            ratings[imdb_id] = {
                "rating": movie.get("imdb_rating"),
                "votes": movie.get("imdb_votes") or 0,
            }
    return ratings


def fetch_imdb_ratings(target_ids):
    if not target_ids:
        return {}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = Request(
                IMDB_RATINGS_URL,
                headers={"User-Agent": "jakemato-movie-selector/2.0"},
            )
            with urlopen(req, timeout=90) as response:
                with gzip.GzipFile(fileobj=response) as gz:
                    reader = io.TextIOWrapper(gz, encoding="utf-8")
                    header = next(reader, None)
                    if not header:
                        raise RuntimeError("IMDb ratings dataset was empty.")

                    found = {}
                    remaining = set(target_ids)
                    for line in reader:
                        parts = line.rstrip("\n").split("\t")
                        if len(parts) != 3:
                            continue
                        imdb_id, average_rating, num_votes = parts
                        if imdb_id not in remaining:
                            continue
                        found[imdb_id] = {
                            "rating": float(average_rating),
                            "votes": int(num_votes),
                        }
                        remaining.remove(imdb_id)
                        if not remaining:
                            break

                    print(
                        f"Matched IMDb ratings for {len(found)}/{len(target_ids)} "
                        "catalog titles."
                    )
                    return found
        except (HTTPError, URLError, TimeoutError, ConnectionResetError, OSError, RuntimeError) as exc:
            if attempt == MAX_RETRIES:
                print(f"IMDb ratings download failed after retries: {exc}")
                return {}
            delay = min(2 ** (attempt - 1), 16)
            print(f"IMDb ratings download failed: {exc}; retrying in {delay}s.")
            time.sleep(delay)

    return {}


def attach_imdb_ratings(movies, picks):
    fallback = previous_imdb_ratings()
    target_ids = {
        movie.get("imdb_id")
        for movie in list(movies) + list(picks)
        if (movie.get("imdb_id") or "").startswith("tt")
    }

    current = fetch_imdb_ratings(target_ids)

    for movie in list(movies) + list(picks):
        imdb_id = movie.get("imdb_id")
        rating = current.get(imdb_id) or fallback.get(imdb_id)
        movie["imdb_rating"] = rating["rating"] if rating else None
        movie["imdb_votes"] = rating["votes"] if rating else 0


def validate_before_publish(movies, candidate_count, skipped_errors):
    if not movies:
        raise RuntimeError("Refusing to publish an empty movie catalog.")

    if candidate_count and skipped_errors / candidate_count > 0.10:
        raise RuntimeError(
            f"Refusing to publish: transient TMDB errors affected "
            f"{skipped_errors}/{candidate_count} candidates."
        )

    if OUTPUT.exists():
        try:
            old = json.loads(OUTPUT.read_text(encoding="utf-8"))
            old_count = len(old.get("movies", []))
        except (OSError, json.JSONDecodeError):
            old_count = 0

        if old_count >= 200 and len(movies) < old_count * 0.50:
            raise RuntimeError(
                f"Refusing to publish suspiciously small catalog: "
                f"{len(movies)} movies vs previous {old_count}."
            )


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

    validate_before_publish(movies, len(candidate_ids), skipped_errors)

    jakes_picks = build_jakes_picks(movies, genre_map)
    attach_imdb_ratings(movies, jakes_picks)

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
        "jakes_picks": jakes_picks,
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
