-- PostgreSQL design for persistent, confirmed season-long starting-XI data.
CREATE TABLE IF NOT EXISTS season_matches (
 match_id TEXT PRIMARY KEY, competition_id TEXT NOT NULL, season_id TEXT NOT NULL,
 kickoff_utc TIMESTAMPTZ NOT NULL, home_team_id TEXT NOT NULL, away_team_id TEXT NOT NULL,
 status TEXT NOT NULL, CHECK(home_team_id <> away_team_id)
);
CREATE INDEX IF NOT EXISTS season_matches_group ON season_matches(season_id,competition_id,kickoff_utc);

CREATE TABLE IF NOT EXISTS season_official_lineups (
 match_id TEXT NOT NULL REFERENCES season_matches(match_id) ON DELETE CASCADE,
 team_id TEXT NOT NULL, source_name TEXT NOT NULL,
 source_reference TEXT NOT NULL, verified_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(match_id,team_id)
);
CREATE TABLE IF NOT EXISTS season_starters (
 match_id TEXT NOT NULL, team_id TEXT NOT NULL, player_id TEXT NOT NULL,
 player_name TEXT NOT NULL, position_code TEXT, jersey_number INTEGER,
 PRIMARY KEY(match_id,team_id,player_id),
 FOREIGN KEY(match_id,team_id) REFERENCES season_official_lineups(match_id,team_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS season_starters_lookup ON season_starters(team_id,player_id);
-- A historical lineup is accepted only when it has exactly 11 distinct starters.
-- The importer validates BOTH teams before writing anything to the database.
CREATE OR REPLACE VIEW season_complete_xi AS
SELECT match_id,team_id FROM season_starters GROUP BY match_id,team_id HAVING COUNT(*)=11;
-- For display, denominator = all finished fixtures, not merely available lineups.
CREATE OR REPLACE VIEW season_finished_fixtures AS
 SELECT match_id,season_id,competition_id,home_team_id AS team_id
 FROM season_matches WHERE status='finished'
 UNION ALL
 SELECT match_id,season_id,competition_id,away_team_id AS team_id
 FROM season_matches WHERE status='finished';
