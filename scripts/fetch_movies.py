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
JAKE_PICKS_CONFIG = Path("tools/movies/config/jakes-picks.json")
MANDY_PICKS_CONFIG = Path("tools/movies/config/mandys-picks.json")
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
        "primary_release_date": details.get("release_date") or "",
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


def load_picks_config(config_path, profile_name):
    if not config_path.exists():
        raise RuntimeError(f"{profile_name} config not found: {config_path}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not config.get("seeds"):
        raise RuntimeError(f"{profile_name} config has no seeds.")
    return config


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
        {"append_to_response": "external_ids,keywords", "language": "en-US"},
    )
    if details.get("adult"):
        return None

    keyword_payload = details.get("keywords", {})
    keyword_items = keyword_payload.get("keywords", []) or keyword_payload.get("results", [])

    return {
        "tmdb_id": details["id"],
        "title": details.get("title") or details.get("original_title") or "Untitled",
        "original_title": details.get("original_title") or "",
        "original_language": details.get("original_language") or "",
        "primary_release_date": details.get("release_date") or "",
        "poster_path": details.get("poster_path"),
        "genres": [genre.get("name") for genre in details.get("genres", []) if genre.get("name")]
        or [genre_map.get(gid) for gid in details.get("genre_ids", []) if genre_map.get(gid)],
        "runtime": details.get("runtime") or None,
        "vote_average": details.get("vote_average") or 0,
        "vote_count": details.get("vote_count") or 0,
        "imdb_id": details.get("external_ids", {}).get("imdb_id") or details.get("imdb_id"),
        "_keywords": [
            keyword.get("name", "").strip()
            for keyword in keyword_items
            if keyword.get("name")
        ],
    }


def pick_exclusion_reason(movie, config):
    title_text = " ".join(
        [
            movie.get("title") or "",
            movie.get("original_title") or "",
        ]
    ).casefold()

    min_year = config.get("min_year")
    release_year = None
    primary_release_date = movie.get("primary_release_date") or ""
    if len(primary_release_date) >= 4 and primary_release_date[:4].isdigit():
        release_year = int(primary_release_date[:4])

    if min_year and release_year and release_year < int(min_year):
        exception = config.get("pre_min_year_exception") or {}
        min_old_rating = float(exception.get("min_tmdb_rating", 8.0))
        min_old_votes = int(exception.get("min_tmdb_votes", 1000))
        if (
            float(movie.get("vote_average") or 0) < min_old_rating
            or int(movie.get("vote_count") or 0) < min_old_votes
        ):
            return (
                f"released before {min_year} without meeting classic-film "
                f"exception ({min_old_rating}+ TMDB, {min_old_votes}+ votes)"
            )

    min_tmdb_rating = config.get("min_tmdb_rating")
    if (
        min_tmdb_rating is not None
        and float(movie.get("vote_average") or 0) < float(min_tmdb_rating)
    ):
        return f"TMDB rating below {min_tmdb_rating}"

    min_tmdb_votes = config.get("min_tmdb_votes")
    if (
        min_tmdb_votes is not None
        and int(movie.get("vote_count") or 0) < int(min_tmdb_votes)
    ):
        return f"TMDB vote count below {min_tmdb_votes}"

    for phrase in config.get("exclude_title_contains", []):
        phrase = str(phrase).strip().casefold()
        if phrase and phrase in title_text:
            return f"title contains '{phrase}'"

    keywords = [keyword.casefold() for keyword in movie.get("_keywords", [])]
    for phrase in config.get("exclude_keywords", []):
        phrase = str(phrase).strip().casefold()
        if phrase and any(phrase in keyword for keyword in keywords):
            return f"keyword '{phrase}'"

    excluded_genres = {
        str(genre).strip().casefold()
        for genre in config.get("exclude_genres", [])
        if str(genre).strip()
    }
    if excluded_genres:
        movie_genres = {
            str(genre).strip().casefold()
            for genre in movie.get("genres", [])
            if str(genre).strip()
        }
        overlap = excluded_genres & movie_genres
        if overlap:
            return f"excluded genre '{sorted(overlap)[0]}'"

    return None


def pick_rotation_bucket(config):
    today = date.today()
    rotation = str(config.get("rotation", "daily")).strip().casefold()

    if rotation == "weekly":
        iso_year, iso_week, _ = today.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if rotation == "monthly":
        return today.strftime("%Y-%m")
    return today.isoformat()


def build_profile_picks(movies, genre_map, config_path, profile_name, random_namespace):
    config = load_picks_config(config_path, profile_name)
    limit = int(config.get("limit", 40))
    candidate_scan_limit = int(config.get("candidate_scan_limit", max(limit * 4, limit)))
    recommendations_per_seed = int(config.get("recommendations_per_seed", 20))
    default_seed_cap = int(config.get("default_max_picks_per_seed", 6))

    seed_ids = set()
    seed_caps = {}
    candidate_scores = defaultdict(float)
    candidate_seed_scores = defaultdict(dict)
    candidate_genres = defaultdict(set)

    for seed_config in config.get("seeds", []):
        seed_title = str(seed_config.get("title") or "").strip()
        seed_year = seed_config.get("year")
        seed_weight = max(0.0, float(seed_config.get("weight", 1.0)))
        seed_cap = max(0, int(seed_config.get("max_picks", default_seed_cap)))

        if not seed_title or not seed_year or seed_weight <= 0 or seed_cap <= 0:
            continue

        try:
            seed = resolve_seed_movie(seed_title, seed_year)
        except (HTTPError, URLError, TimeoutError, ConnectionResetError) as exc:
            print(f"{profile_name} seed failed: {seed_title}: {exc}")
            continue

        if not seed:
            print(f"{profile_name} seed not found: {seed_title} ({seed_year})")
            continue

        seed_id = seed["id"]
        seed_ids.add(seed_id)
        seed_caps[seed_title] = seed_cap

        try:
            recs = tmdb_get(
                f"/movie/{seed_id}/recommendations",
                {"language": "en-US", "page": 1},
            ).get("results", [])
        except (HTTPError, URLError, TimeoutError, ConnectionResetError, TMDBNotFound) as exc:
            print(f"{profile_name} recommendations failed for {seed_title}: {exc}")
            continue

        for rank, recommendation in enumerate(
            recs[:recommendations_per_seed],
            start=1,
        ):
            candidate_id = recommendation.get("id")
            if not candidate_id or recommendation.get("adult"):
                continue

            rank_score = max(1, recommendations_per_seed + 4 - rank)
            contribution = rank_score * seed_weight
            candidate_scores[candidate_id] += contribution
            candidate_seed_scores[candidate_id][seed_title] = (
                candidate_seed_scores[candidate_id].get(seed_title, 0.0)
                + contribution
            )
            for genre_id in recommendation.get("genre_ids", []):
                genre_name = genre_map.get(genre_id)
                if genre_name:
                    candidate_genres[candidate_id].add(genre_name)

    for seed_id in seed_ids:
        candidate_scores.pop(seed_id, None)
        candidate_seed_scores.pop(seed_id, None)

    rng = random.Random(
        f"{random_namespace}-{pick_rotation_bucket(config)}"
    )
    weighted_candidates = []

    preferred_genres = {
        str(name): float(multiplier)
        for name, multiplier in (config.get("preferred_genres") or {}).items()
    }

    for movie_id, base_score in candidate_scores.items():
        seed_count = len(candidate_seed_scores[movie_id])
        overlap_bonus = 1 + (0.5 * max(0, seed_count - 1))

        genre_multiplier = 1.0
        for genre_name in candidate_genres.get(movie_id, set()):
            genre_multiplier = max(
                genre_multiplier,
                preferred_genres.get(genre_name, 1.0),
            )

        effective_weight = max(
            0.001,
            base_score * overlap_bonus * genre_multiplier,
        )
        random_key = rng.random() ** (1.0 / effective_weight)
        weighted_candidates.append((random_key, movie_id))

    weighted_candidates.sort(reverse=True)

    picks = []
    seed_usage = defaultdict(int)
    excluded_count = 0
    scanned = 0

    for _, movie_id in weighted_candidates:
        if len(picks) >= limit or scanned >= candidate_scan_limit:
            break

        scanned += 1
        seed_scores = candidate_seed_scores[movie_id]
        eligible_seeds = [
            seed_title
            for seed_title, _ in sorted(
                seed_scores.items(),
                key=lambda item: item[1],
                reverse=True,
            )
            if seed_usage[seed_title] < seed_caps.get(seed_title, default_seed_cap)
        ]
        if not eligible_seeds:
            continue

        try:
            pick = fetch_pick_detail(movie_id, genre_map)
        except (HTTPError, URLError, TimeoutError, ConnectionResetError, TMDBNotFound) as exc:
            print(f"Skipping {profile_name} candidate {movie_id}: {exc}")
            continue

        if not pick or not pick.get("poster_path") or not (pick.get("imdb_id") or "").startswith("tt"):
            continue

        exclusion_reason = pick_exclusion_reason(pick, config)
        if exclusion_reason:
            excluded_count += 1
            print(
                f"{profile_name} excluded {pick.get('title')} "
                f"({movie_id}): {exclusion_reason}."
            )
            continue

        primary_seed = eligible_seeds[0]
        seed_usage[primary_seed] += 1

        pick.pop("_keywords", None)
        pick["primary_seed"] = primary_seed
        pick["seed_matches"] = [
            seed_title
            for seed_title, _ in sorted(
                seed_scores.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ]
        pick["recommendation_score"] = round(candidate_scores[movie_id], 2)
        picks.append(pick)

    usage_summary = ", ".join(
        f"{seed}: {count}"
        for seed, count in sorted(seed_usage.items())
        if count
    )
    print(
        f"Built {len(picks)} {profile_name} movies from {len(seed_caps)} resolved seeds; "
        f"{excluded_count} candidates excluded by taste filters. "
        f"Seed usage: {usage_summary or 'none'}."
    )
    return picks

def previous_imdb_ratings():
    if not OUTPUT.exists():
        return {}

    try:
        old = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    ratings = {}
    old_rating_movies = (
        list(old.get("movies", []))
        + list(old.get("jakes_picks", []))
        + list(old.get("mandys_picks", []))
    )
    for movie in old_rating_movies:
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


def attach_imdb_ratings(movies, *pick_groups):
    all_movies = list(movies)
    for pick_group in pick_groups:
        all_movies.extend(list(pick_group))

    fallback = previous_imdb_ratings()
    target_ids = {
        movie.get("imdb_id")
        for movie in all_movies
        if (movie.get("imdb_id") or "").startswith("tt")
    }

    current = fetch_imdb_ratings(target_ids)

    for movie in all_movies:
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

    jakes_picks = build_profile_picks(
        movies,
        genre_map,
        JAKE_PICKS_CONFIG,
        "Jake's Picks",
        "jakes-picks",
    )
    mandys_picks = build_profile_picks(
        movies,
        genre_map,
        MANDY_PICKS_CONFIG,
        "Mandys Picks",
        "mandys-picks",
    )
    attach_imdb_ratings(movies, jakes_picks, mandys_picks)

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
        "mandys_picks": mandys_picks,
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
