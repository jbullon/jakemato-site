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
    "version": "1.0.0",
    "name": "Jakemato Movie Releases",
    "description": "Recent and upcoming US movie releases from Jakemato, organized for Stremio.",
    "resources": ["catalog"],
    "types": ["movie"],
    "catalogs": [
        {
            "type": "movie",
            "id": "recent",
            "name": "Jakemato - Recent Releases",
        },
        {
            "type": "movie",
            "id": "upcoming",
            "name": "Jakemato - Upcoming Releases",
        },
        {
            "type": "movie",
            "id": "theatrical",
            "name": "Jakemato - Upcoming Theatrical",
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


def make_meta(movie, event):
    release_types = [
        TYPE_NAMES[type_id]
        for type_id in event.get("types", [])
        if type_id in TYPE_NAMES
    ]
    release_label = " / ".join(release_types) if release_types else "US release"
    certification = event.get("certification") or "NR"
    release_date = event["date"]

    description = f"US release: {pretty_date(release_date)} • {release_label} • {certification}"

    return {
        "id": movie["imdb_id"],
        "type": "movie",
        "name": movie["title"],
        "poster": f"{POSTER_BASE}{movie['poster_path']}",
        "posterShape": "poster",
        "genres": movie.get("genres", []),
        "releaseInfo": release_date[:4],
        "description": description,
    }


def build_catalog(movies, event_filter, reverse=False):
    candidates = []

    for movie in movies:
        if not is_stremio_eligible(movie):
            continue

        for event in movie.get("events", []):
            if event_filter(event):
                candidates.append((event["date"], movie["title"].lower(), movie, event))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=reverse)

    metas = []
    seen = set()

    for _, _, movie, event in candidates:
        imdb_id = movie["imdb_id"]
        if imdb_id in seen:
            continue
        seen.add(imdb_id)
        metas.append(make_meta(movie, event))

    return {"metas": metas}


def main():
    if not SOURCE.exists():
        raise SystemExit(f"Movie data not found: {SOURCE}")

    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    movies = payload.get("movies", [])

    today = date.today()
    today_iso = today.isoformat()
    recent_start = (today - timedelta(days=30)).isoformat()
    future_end = (today + timedelta(days=90)).isoformat()

    recent = build_catalog(
        movies,
        lambda event: recent_start <= event.get("date", "") <= today_iso,
        reverse=True,
    )

    upcoming = build_catalog(
        movies,
        lambda event: today_iso <= event.get("date", "") <= future_end,
    )

    theatrical = build_catalog(
        movies,
        lambda event: (
            today_iso <= event.get("date", "") <= future_end
            and any(type_id in (2, 3) for type_id in event.get("types", []))
        ),
    )

    write_json(OUTPUT_ROOT / "manifest.json", MANIFEST)
    write_json(OUTPUT_ROOT / "catalog/movie/recent.json", recent)
    write_json(OUTPUT_ROOT / "catalog/movie/upcoming.json", upcoming)
    write_json(OUTPUT_ROOT / "catalog/movie/theatrical.json", theatrical)

    print(
        "Built Stremio catalogs: "
        f"{len(recent['metas'])} recent, "
        f"{len(upcoming['metas'])} upcoming, "
        f"{len(theatrical['metas'])} theatrical."
    )


if __name__ == "__main__":
    main()
