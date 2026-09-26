# Personalized Picks profiles

`jakes-picks.json` controls **Jake's Picks** and `amandas-picks.json` controls **Amanda's Picks**. Both use the same automated recommendation engine.

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


## Amanda's Picks

Amanda's profile currently uses equal seed weights and a maximum of 3 selected movies per primary seed to keep the catalog mixed across broad comedy, psychological horror/drama, romance, prestige drama, action, and science fiction.

"The Stand" was not included as a seed because the well-known versions are television miniseries and this recommendation engine intentionally stays movie-only.
