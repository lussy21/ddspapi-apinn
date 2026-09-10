import os
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import gspread
import requests
from google.oauth2.service_account import Credentials


GREECE_TZ = ZoneInfo("Europe/Athens")
UTC_TZ = ZoneInfo("UTC")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SHEET_KEY = "1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM"
SHEET_NAME = "PINNACLE"
GOOGLE_CREDS = "/etc/secrets/google-credentials.json"

APINN_BOARD_URL = "https://api.apinn.io/api/board"

APIFY_FIXTURES_URL = (
    "https://api.apify.com/v2/acts/"
    "incognito_mode~sofascore-live-scores-scraper/"
    "run-sync-get-dataset-items"
)

APIFY_MATCH_URL = (
    "https://api.apify.com/v2/acts/"
    "incognito_mode~sofascore-match-analytics-scraper/"
    "run-sync-get-dataset-items"
)


# APINN league id -> Sofascore uniqueTournamentId
APINN_TO_SOFA_TOURNAMENT = {
    1980: 17,      # England - Premier League
    1842: 35,      # Germany - Bundesliga
    2036: 34,      # France - Ligue 1
    2081: 185,     # Greece - Super League
    2436: 23,      # Italy - Serie A
    2196: 8,       # Spain - La Liga
    1817: 38,      # Belgium - Pro League
    1913: 39,      # Denmark - Superliga
    2333: 20,      # Norway - Eliteserien
    1928: 37,      # Netherlands - Eredivisie
    2592: 52,      # Turkey - Super League
    1834: 325,     # Brazil - Serie A
    210697: 155,   # Argentina - Liga Profesional
    1728: 40,      # Sweden - Allsvenskan
    2663: 242,     # USA - MLS
    2627: 7,       # UEFA - Champions League
}


LEAGUE_NAME_TO_SOFA_TOURNAMENT = {
    "england - premier league": 17,
    "germany - bundesliga": 35,
    "france - ligue 1": 34,
    "greece - super league": 185,
    "italy - serie a": 23,
    "spain - la liga": 8,
    "belgium - pro league": 38,
    "denmark - superliga": 39,
    "norway - eliteserien": 20,
    "netherlands - eredivisie": 37,
    "turkey - super league": 52,
    "turkey - super lig": 52,
    "brazil - serie a": 325,
    "argentina - liga profesional": 155,
    "sweden - allsvenskan": 40,
    "usa - mls": 242,
    "mls": 242,
    "uefa - champions league": 7,
    "finland - veikkausliiga": 41,
    "scotland - premiership": 36,
    "uefa - europa league": 679,
    "uefa - conference league": 17015,
}


DROP_TOKENS = {
    "fc", "cf", "afc", "sc", "fk", "sk", "vfb", "ac",
}


ALIASES = {
    "man utd": "manchester united",
    "man united
