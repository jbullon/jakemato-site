# Personalized Picks profiles

`jakes-picks.json` controls **Jake's Picks** and `mandys-picks.json` controls **Mandys Picks**. Both use the same automated recommendation engine.

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


## Mandys Picks

Mandy's profile currently uses equal seed weights and a maximum of 3 selected movies per primary seed to keep the catalog mixed across broad comedy, psychological horror/drama, romance, prestige drama, action, and science fiction.

"The Stand" was not included as a seed because the well-known versions are television miniseries and this recommendation engine intentionally stays movie-only.


## Mandys Picks quality rules

Mandy's profile is intentionally stricter than Jake's:

- Prefer movies from 1980 onward.
- Older movies are only allowed when they meet the configured classic-film rating and vote thresholds.
- Candidates below the configured TMDB rating or vote-count floor are rejected before selection.
- Preferred genres can receive a score multiplier. Mandy currently favors Comedy, Romance, Drama, Horror, Thriller, and Science Fiction.
- The Stand (1994) is recorded as a TV taste reference rather than a movie seed. This keeps its apocalyptic/dark-drama influence in the profile notes without feeding TV recommendations into a movie-only Stremio catalog.


## Mandys Picks v3 tuning

Mandy's current profile uses 2000 as a soft era floor.

A pre-2000 candidate is allowed only when either:
- at least two positive Mandy seeds independently recommend it, or
- it clears the configured acclaim threshold (currently TMDB 7.5+ with 2,500+ votes).

This is intended to keep older movies only when there is meaningful evidence that they fit her taste.

Comedy tuning now uses Mean Girls as a strong positive seed. Happy Gilmore and The Help are no longer positive seeds.

The Hot Chick is both an exact title exclusion and a negative seed. Movies that TMDB considers adjacent to The Hot Chick have their score reduced before selection.

Madea-titled and explicitly Tyler Perry-branded titles are excluded by title pattern. This is a style/franchise preference, not a demographic filter.


## Jake's Picks v2

Jake's profile now uses a smaller 25-movie daily catalog designed around confidence rather than volume.

Selection mix:
- 15 high-confidence picks
- 7 adventurous picks
- 3 wildcards

The engine can now use positive TMDB keyword signals, soft keyword/genre penalties, negative movie seeds, a soft era floor, and franchise suppression.

Jake's strongest signals emphasize:
- extreme / bleak / survival horror
- gore, slashers, body horror, psychological horror, disturbing material
- tense films with memorable antagonists
- absurd, offensive, stoner, dark and satirical comedy
- intense drama and misery when the movie still has momentum

Jake's profile intentionally does not treat science fiction as a preferred genre. Alien, Predator and District 9 are individual positive seeds.

The profile uses 1980 as a soft floor. Older films need either multiple positive seed matches or the configured acclaim exception.

Family and Romance are excluded. Anime and musicals are keyword exclusions. Sports and religious material are penalized rather than banned because there are known exceptions.

The Dark Knight remains a weak seed because its tension, bleakness and villain are the relevant signals rather than superhero material.

The Hot Chick is not a negative signal for Jake. Its negative-seed treatment exists only in Mandy's profile.
