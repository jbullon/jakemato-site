import json
from datetime import date, datetime, timedelta
from pathlib import Path

SOURCE = Path("tools/movies/data/movies.json")
OUTPUT_ROOT = Path("stremio/movies")
POSTER_BASE = "https://image.tmdb.org/t/p/w185"

TYPE_NAMES = {
    1: "Premiere",
    2: "Limited theatrical",
    3: "Theatrical",
    4: "Digital",
    5: "Physical",
    6: "TV",
}

MANIFEST = {
    "id": "com.jakemato.movie-releases",
    "version": "1.1.0",
    "name": "Jakemato Movie Releases",
    "description": "Recent US movie releases, Jake's Picks, and upcoming movies with trailers.",
    "resources": ["catalog"],
    "types": ["movie"],
    "idPrefixes": ["tt"],
    "catalogs": [
        {
            "type": "movie",
            "id": "recent",
            "name": "Jakemato - Recent Releases",
        },
        {
            "type": "movie",
            "id": "jakes-picks",
            "name": "Jakemato - Jake's Picks",
        },
        {
            "type": "movie",
            "id": "upcoming-trailers",
            "name": "Jakemato - Upcoming with Trailers",
        },
    ],
    "behaviorHints": {
        "adult": False,
        "p2p": False,
    },
}


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def pretty_date(iso_date):
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%B %-d, %Y")


def is_stremio_eligible(movie):
    imdb_id = movie.get("imdb_id") or ""
    return (
        imdb_id.startswith("tt")
        and bool(movie.get("poster_path"))
        and bool(movie.get("title"))
    )


def rating_fields(movie):
    rating = movie.get("imdb_rating")
    return {"imdbRating": f"{rating:.1f}"} if rating is not None else {}


def trailer_fields(movie):
    trailer = movie.get("trailer_youtube_key")
    if not trailer:
        return {}
    return {
        "trailers": [
            {
                "source": trailer,
                "type": "Trailer",
            }
        ]
    }


def make_release_meta(movie, event):
    release_types = [
        TYPE_NAMES[type_id]
        for type_id in event.get("types", [])
        if type_id in TYPE_NAMES
    ]
    release_label = " / ".join(release_types) if release_types else "US release"
    certification = event.get("certification") or "NR"
    release_date = event["date"]
    rating = movie.get("imdb_rating")
    rating_text = f" • IMDb {rating:.1f}" if rating is not None else ""

    meta = {
        "id": movie["imdb_id"],
        "type": "movie",
        "name": movie["title"],
        "poster": f"{POSTER_BASE}{movie['poster_path']}",
        "posterShape": "poster",
        "genres": movie.get("genres", []),
        "releaseInfo": release_date[:4],
        "description": (
            f"US release: {pretty_date(release_date)} • "
            f"{release_label} • {certification}{rating_text}"
        ),
    }
    meta.update(rating_fields(movie))
    meta.update(trailer_fields(movie))
    return meta


def make_pick_meta(movie):
    seed_matches = movie.get("seed_matches") or []
    seed_text = ", ".join(seed_matches[:3])
    rating = movie.get("imdb_rating")
    rating_text = f" • IMDb {rating:.1f}" if rating is not None else ""
    description = "Jake's Picks"
    if seed_text:
        description += f" • Adjacent to: {seed_text}"
    description += rating_text

    meta = {
        "id": movie["imdb_id"],
        "type": "movie",
        "name": movie["title"],
        "poster": f"{POSTER_BASE}{movie['poster_path']}",
        "posterShape": "poster",
        "genres": movie.get("genres", []),
        "description": description,
    }
    if movie.get("primary_release_date"):
        meta["releaseInfo"] = movie["primary_release_date"][:4]
    meta.update(rating_fields(movie))
    return meta


def build_release_catalog(movies, event_filter, reverse=False):
    candidates = []

    for movie in movies:
        if not is_stremio_eligible(movie):
            continue

        for event in movie.get("events", []):
            if event_filter(movie, event):
                candidates.append((event["date"], movie["title"].lower(), movie, event))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=reverse)

    metas = []
    seen = set()

    for _, _, movie, event in candidates:
        imdb_id = movie["imdb_id"]
        if imdb_id in seen:
            continue
        seen.add(imdb_id)
        metas.append(make_release_meta(movie, event))

    return {"metas": metas}


def build_picks_catalog(picks):
    metas = [
        make_pick_meta(movie)
        for movie in picks
        if is_stremio_eligible(movie)
    ]
    return {"metas": metas}


def main():
    if not SOURCE.exists():
        raise SystemExit(f"Movie data not found: {SOURCE}")

    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    movies = payload.get("movies", [])
    picks = payload.get("jakes_picks", [])

    today = date.today()
    today_iso = today.isoformat()
    recent_start = (today - timedelta(days=30)).isoformat()
    future_end = (today + timedelta(days=90)).isoformat()

    recent = build_release_catalog(
        movies,
        lambda movie, event: (
            recent_start <= event.get("date", "") <= today_iso
            and any(type_id not in (5, 6) for type_id in event.get("types", []))
        ),
        reverse=True,
    )

    upcoming_trailers = build_release_catalog(
        movies,
        lambda movie, event: (
            today_iso < event.get("date", "") <= future_end
            and any(type_id not in (5, 6) for type_id in event.get("types", []))
            and bool(movie.get("trailer_youtube_key"))
        ),
    )

    jakes_picks = build_picks_catalog(picks)

    write_json(OUTPUT_ROOT / "manifest.json", MANIFEST)
    write_json(OUTPUT_ROOT / "catalog/movie/recent.json", recent)
    write_json(OUTPUT_ROOT / "catalog/movie/jakes-picks.json", jakes_picks)
    write_json(OUTPUT_ROOT / "catalog/movie/upcoming-trailers.json", upcoming_trailers)

    print(
        "Built Stremio catalogs: "
        f"{len(recent['metas'])} recent, "
        f"{len(jakes_picks['metas'])} Jake's Picks, "
        f"{len(upcoming_trailers['metas'])} upcoming with trailers."
    )


if __name__ == "__main__":
    main()
