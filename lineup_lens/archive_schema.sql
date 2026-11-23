-- Lineup Lens: independent historical 11footy (CC BY-NC 4.0) data namespace.
-- Run only against the separately identified Lineup Lens Neon project.
CREATE TABLE IF NOT EXISTS archive_players (
 player_id INTEGER PRIMARY KEY,
 player_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS archive_teams (
 team_id INTEGER PRIMARY KEY,
 team_name TEXT NOT NULL,
 country TEXT
);
CREATE TABLE IF NOT EXISTS archive_matches (
 match_id INTEGER PRIMARY KEY, season_year INTEGER NOT NULL,
 competition_code TEXT NOT NULL, kickoff_utc TIMESTAMPTZ NOT NULL,
 local_date DATE NOT NULL,
 home_team_id INTEGER NOT NULL REFERENCES archive_teams(team_id),
 away_team_id INTEGER NOT NULL REFERENCES archive_teams(team_id),
 source_release TEXT NOT NULL, CHECK(home_team_id<>away_team_id)
);
CREATE INDEX IF NOT EXISTS archive_matches_season_idx
 ON archive_matches(season_year,competition_code,local_date);
CREATE TABLE IF NOT EXISTS archive_starters (
 match_id INTEGER NOT NULL REFERENCES archive_matches(match_id) ON DELETE CASCADE,
 team_id INTEGER NOT NULL REFERENCES archive_teams(team_id),
 player_id INTEGER NOT NULL REFERENCES archive_players(player_id),
 position_code TEXT,jersey_number INTEGER,
 PRIMARY KEY(match_id,team_id,player_id)
);
CREATE INDEX IF NOT EXISTS archive_starters_player_idx
 ON archive_starters(team_id,player_id);
CREATE TABLE IF NOT EXISTS archive_import_state (
 source TEXT NOT NULL,release_name TEXT NOT NULL,competition_code TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('complete')),
 imported_matches INTEGER NOT NULL,last_match_date DATE,
 completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(source,release_name,competition_code)
);
