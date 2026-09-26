# Jake's Picks profile

`jakes-picks.json` controls the automated Stremio **Jake's Picks** catalog.

## Main controls

- `limit`: total number of picks.
- `rotation`: `daily`, `weekly`, or `monthly`.
- `recommendations_per_seed`: how many TMDB recommendations to consider from each seed.
- `default_max_picks_per_seed`: diversity cap when a seed does not specify its own cap.
- `candidate_scan_limit`: maximum candidate movies whose details/keywords will be checked.

## Seeds

Each seed supports:

- `title`
- `year`
- `weight`: how strongly the seed influences ranking.
- `max_picks`: maximum number of selected movies primarily attributed to that seed.

A low weight/cap is useful for a movie you love for specific qualities but do not want its broader genre/franchise to dominate. The Dark Knight is intentionally configured this way.

## Exclusions

- `exclude_keywords`: rejects candidates whose TMDB keywords contain one of these phrases.
- `exclude_title_contains`: rejects candidates whose title contains one of these phrases.
- `exclude_genres`: optional exact TMDB genre exclusions.

The current profile suppresses superhero/comic-book material while still allowing The Dark Knight to contribute occasional dark crime/thriller recommendations.
