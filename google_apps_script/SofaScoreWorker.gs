/**
 * SofaScore Google worker for the "Προτζεκτ" spreadsheet.
 *
 * IMPORTANT:
 * - Isolated from Render/APINN/Pinnacle code.
 * - No paid fallback.
 * - No automatic trigger is installed until installSofaDailyTrigger() is run.
 * - Daily worker writes only:
 *     PINNACLE!N (Sofa favorite %)
 *     SOFA CACHE!A:E (APINN <-> Sofa event mapping)
 *     ALERT STATS!O2/P2 (status)
 */

const SOFA_CFG = {
  tz: 'Europe/Athens',
  apiBase: 'https://api.sofascore.com/api/v1',
  spreadsheetId: '1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM',
  pinnacleSheet: 'PINNACLE',
  cacheSheet: 'SOFA CACHE',
  controlSheet: 'ALERT STATS',
  testEventId: 16362020, // Celtic - Rangers; known-good event from our cache
  requestHeaders: {
    'Accept': 'application/json, text/plain, */*',
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36'
  }
};

function sofaFetchJson_(path) {
  const url = SOFA_CFG.apiBase + path;
  const response = UrlFetchApp.fetch(url, {
    method: 'get',
    muteHttpExceptions: true,
    followRedirects: true,
    headers: SOFA_CFG.requestHeaders
  });
  const code = response.getResponseCode();
  const text = response.getContentText();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch (e) {}
  return { url: url, code: code, text: text, json: json };
}

function nowStamp_() {
  return Utilities.formatDate(new Date(), SOFA_CFG.tz, 'yyyy-MM-dd HH:mm:ss');
}

function todayKey_() {
  return Utilities.formatDate(new Date(), SOFA_CFG.tz, 'yyyy-MM-dd');
}

function ss_() {
  return SpreadsheetApp.openById(SOFA_CFG.spreadsheetId);
}

function controlSheet_() {
  return ss_().getSheetByName(SOFA_CFG.controlSheet);
}

function setControl_(cell, value) {
  controlSheet_().getRange(cell).setValue(value);
}

/**
 * First safety test. Does NOT touch PINNACLE or SOFA CACHE.
 * Writes only ALERT STATS!O2.
 */
function testSofaGoogleConnection() {
  const started = nowStamp_();
  setControl_('O2', 'RUNNING ' + started);

  try {
    const result = sofaFetchJson_('/event/' + SOFA_CFG.testEventId);
    const event = result.json && result.json.event ? result.json.event : null;
    if (result.code === 200 && event && Number(event.id) === SOFA_CFG.testEventId) {
      const home = event.homeTeam && event.homeTeam.name ? event.homeTeam.name : '';
      const away = event.awayTeam && event.awayTeam.name ? event.awayTeam.name : '';
      setControl_(
        'O2',
        'OK ' + nowStamp_() + ' | HTTP 200 | ' + home + ' - ' + away
      );
      return true;
    }

    setControl_(
      'O2',
      'FAILED ' + nowStamp_() + ' | HTTP ' + result.code
    );
    return false;
  } catch (err) {
    setControl_(
      'O2',
      'ERROR ' + nowStamp_() + ' | ' + String(err).slice(0, 120)
    );
    return false;
  }
}

/**
 * Separate discovery test. Does NOT write any match data.
 * Writes only ALERT STATS!P2.
 */
function testSofaScheduleToday() {
  const date = todayKey_();
  setControl_('P2', 'TESTING SCHEDULE ' + date);

  try {
    const result = sofaFetchJson_('/sport/football/scheduled-events/' + date);
    const events = result.json && Array.isArray(result.json.events)
      ? result.json.events
      : [];

    if (result.code === 200 && events.length) {
      setControl_(
        'P2',
        'SCHEDULE OK ' + nowStamp_() + ' | events=' + events.length
      );
      return true;
    }

    setControl_(
      'P2',
      'SCHEDULE FAILED ' + nowStamp_() +
      ' | HTTP ' + result.code + ' | events=' + events.length
    );
    return false;
  } catch (err) {
    setControl_(
      'P2',
      'SCHEDULE ERROR ' + nowStamp_() + ' | ' + String(err).slice(0, 120)
    );
    return false;
  }
}

function ascii_(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const SOFA_ALIASES = {
  'olympiakos': 'olympiacos',
  'olympiakos ii': 'olympiacos b',
  'inter miami cf': 'inter miami',
  'paris saint germain': 'psg',
  'saint truidense': 'sint truidense',
  'hacken': 'bk hacken',
  'caykur rizespor': 'rizespor',
  'bodo glimt': 'bodo glimt'
};

function normTeam_(value) {
  let text = ascii_(value);
  if (SOFA_ALIASES[text]) text = SOFA_ALIASES[text];

  const drop = {
    'fc': true, 'cf': true, 'sc': true, 'afc': true,
    'fk': true, 'ac': true, 'club': true
  };
  text = text.split(' ').filter(t => !drop[t]).join(' ').trim();
  if (SOFA_ALIASES[text]) text = SOFA_ALIASES[text];
  return text;
}

function levenshtein_(a, b) {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;

  const prev = Array.from({length: b.length + 1}, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      cur[j] = Math.min(
        cur[j - 1] + 1,
        prev[j] + 1,
        prev[j - 1] + cost
      );
    }
    for (let j = 0; j < cur.length; j++) prev[j] = cur[j];
  }
  return prev[b.length];
}

function teamScore_(a, b) {
  a = normTeam_(a);
  b = normTeam_(b);
  if (!a || !b) return 0;
  if (a === b) return 1;
  if (a.indexOf(b) >= 0 || b.indexOf(a) >= 0) return 0.96;

  const maxLen = Math.max(a.length, b.length);
  const editScore = maxLen ? 1 - (levenshtein_(a, b) / maxLen) : 0;

  const ta = new Set(a.split(' '));
  const tb = new Set(b.split(' '));
  let inter = 0;
  ta.forEach(t => { if (tb.has(t)) inter++; });
  const union = new Set([...ta, ...tb]).size || 1;
  const jaccard = inter / union;

  return Math.max(editScore, jaccard);
}

function findFixture_(home, away, fixtures) {
  let best = null;
  let bestScore = 0;

  fixtures.forEach(item => {
    const sh = item.homeTeam && item.homeTeam.name ? item.homeTeam.name : '';
    const sa = item.awayTeam && item.awayTeam.name ? item.awayTeam.name : '';
    const hs = teamScore_(home, sh);
    const as = teamScore_(away, sa);
    if (hs < 0.68 || as < 0.68) return;

    const score = (hs + as) / 2;
    if (score > bestScore) {
      bestScore = score;
      best = item;
    }
  });

  return bestScore >= 0.76 ? best : null;
}

function favoritePct_(payload, favoriteSide) {
  if (!payload) return null;
  const root = payload.vote || payload.votes || payload;
  if (!root || typeof root !== 'object') return null;

  const num = function(keys) {
    for (let i = 0; i < keys.length; i++) {
      const value = root[keys[i]];
      if (value === undefined || value === null || value === '') continue;
      const n = Number(value);
      if (Number.isFinite(n)) return n;
    }
    return 0;
  };

  const vote1 = num(['vote1', 'home', 'homeVotes', 'voteHome']);
  const voteX = num(['voteX', 'draw', 'drawVotes', 'voteDraw']);
  const vote2 = num(['vote2', 'away', 'awayVotes', 'voteAway']);
  const total = vote1 + voteX + vote2;
  if (total <= 0) return null;

  const favVotes = favoriteSide === 'H' ? vote1 : vote2;
  return Math.round((favVotes * 100) / total);
}

function loadCache_() {
  const ss = ss_();
  const sheet = ss.getSheetByName(SOFA_CFG.cacheSheet);
  const lastRow = Math.max(sheet.getLastRow(), 1);
  const values = lastRow >= 2
    ? sheet.getRange(2, 1, lastRow - 1, 5).getValues()
    : [];

  const byApinn = {};
  values.forEach((row, idx) => {
    const apinnId = String(row[0] || '').trim();
    const sofaId = Number(row[1] || 0);
    if (apinnId && sofaId) {
      byApinn[apinnId] = {
        sofaId: sofaId,
        row: idx + 2
      };
    }
  });
  return { sheet: sheet, byApinn: byApinn };
}

function appendCache_(cacheSheet, apinnId, sofaId, home, away, dateKey) {
  cacheSheet.appendRow([
    String(apinnId),
    Number(sofaId),
    home,
    away,
    dateKey
  ]);
}

/**
 * Daily worker.
 *
 * Safety:
 * - Never calls Apify or any paid API.
 * - Never modifies odds, turnover, alerts or results.
 * - Only writes PINNACLE column N and SOFA CACHE mapping rows.
 * - If schedule discovery fails, it stops cleanly.
 */
function runSofaDaily() {
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(1000)) return;

  try {
    const dateKey = todayKey_();
    setControl_('P2', 'RUNNING ' + nowStamp_());

    // Two predictable, low-cost calls instead of scanning many tournaments.
    // Include early next-day matches before the daily 12:30 snapshot.
    const nextDay = Utilities.formatDate(
      new Date(Date.now()+24*60*60*1000), SOFA_CFG.tz, 'yyyy-MM-dd'
    );
    const fixtureMap = {};
    let firstHttp = 0, availableDays = 0;
    [dateKey, nextDay].forEach((day, index) => {
      let schedule = sofaFetchJson_('/sport/football/scheduled-events/' + day);
      if (schedule.code !== 200) {
        const backupUrl = 'https://www.sofascore.com/api/v1/sport/football/scheduled-events/' + day;
        const backup = UrlFetchApp.fetch(backupUrl, {
          method: 'get', muteHttpExceptions: true, followRedirects: true,
          headers: SOFA_CFG.requestHeaders
        });
        let json = null;
        try { json = JSON.parse(backup.getContentText()); } catch (ignore) {}
        if (backup.getResponseCode()===200 && json) {
          schedule={code:200,json:json};
        } else {
          if (index===0) firstHttp = schedule.code || backup.getResponseCode();
          Logger.log('SOFASCORE SCHEDULE ' + day + ' HTTP ' +
            schedule.code + '/' + backup.getResponseCode());
          return;
        }
      }
      if (!schedule.json || !Array.isArray(schedule.json.events)) return;
      availableDays++;
      schedule.json.events.forEach(event => {
        if (event && event.id && !fixtureMap[event.id]) fixtureMap[event.id]=event;
      });
    });
    const horizon=Date.now()+24*60*60*1000;
    const fixtures=Object.keys(fixtureMap).map(k=>fixtureMap[k])
      .filter(e=>Number(e.startTimestamp||0)*1000 > Date.now() &&
        Number(e.startTimestamp||0)*1000 <= horizon);

    if (!availableDays || !fixtures.length) {
      setControl_('P2','STOPPED '+nowStamp_()+
        ' | Sofa schedule HTTP '+firstHttp+
        ' | availableDays='+availableDays+' | events='+fixtures.length);
      return;
    }

    const ss = ss_();
    const pinnacle = ss.getSheetByName(SOFA_CFG.pinnacleSheet);
    const lastRow = pinnacle.getLastRow();
    if (lastRow < 3) {
      setControl_('P2', 'DONE ' + nowStamp_() + ' | no rows');
      return;
    }

    const rows = pinnacle.getRange(3, 1, lastRow - 2, 77).getValues();
    const cache = loadCache_();
    const nowMs=Date.now(),cutoff=nowMs+24*60*60*1000;
    setControl_('P2','FETCHED '+nowStamp_()+' | events='+fixtures.length);

    let matched = 0;
    let written = 0;
    let cached = 0;
    let voteErrors = 0;

    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      const rowNumber = i + 3;
      const home = String(row[1] || '').trim();
      const away = String(row[2] || '').trim();
      const favoriteSide = String(row[3] || '').trim().toUpperCase();
      const resultValue = String(row[15] || '').trim();
      const apinnId = String(row[17] || '').trim();

      if (!home || !away || !apinnId) continue;
      if (favoriteSide !== 'H' && favoriteSide !== 'A') continue;
      if (resultValue) continue; // historical match; do not touch
      const kickoffMs=new Date(row[76]).getTime();
      if (!Number.isFinite(kickoffMs)||kickoffMs<=nowMs||kickoffMs>cutoff) continue;

      let sofaId = cache.byApinn[apinnId]
        ? cache.byApinn[apinnId].sofaId
        : null;

      if (!sofaId) {
        const fixture = findFixture_(home, away, fixtures);
        if (!fixture || !fixture.id) continue;

        sofaId = Number(fixture.id);
        appendCache_(
          cache.sheet, apinnId, sofaId, home, away, dateKey
        );
        cache.byApinn[apinnId] = { sofaId: sofaId };
        cached++;
      }

      matched++;

      let votesResult;
      try {
        votesResult = sofaFetchJson_('/event/' + sofaId + '/votes');
      } catch (e) {
        voteErrors++;
        continue;
      }

      if (votesResult.code !== 200 || !votesResult.json) {
        voteErrors++;
        if (votesResult.code===403 || votesResult.code===429) {
          setControl_('P2','PARTIAL '+nowStamp_()+
            ' | Sofa votes HTTP '+votesResult.code+' | wrote='+written);
          return; // Stop immediately; do not hammer a blocked provider.
        }
        continue;
      }

      const votesPayload =
        votesResult.json.vote ||
        votesResult.json.votes ||
        votesResult.json;

      const pct = favoritePct_(votesPayload, favoriteSide);
      if (pct === null) {
        voteErrors++;
        continue;
      }

      const cell=pinnacle.getRange(rowNumber,14); // N only
      cell.setValue(pct);
      cell.setNumberFormat('0"%"');
      written++;
    }

    setControl_(
      'P2',
      (written>0?'DONE ':'PARTIAL ') + nowStamp_() +
      ' | schedule=' + fixtures.length +
      ' | matched=' + matched +
      ' | cache+=' + cached +
      ' | wrote=' + written +
      ' | vote_errors=' + voteErrors
    );
  } catch (err) {
    setControl_(
      'P2',
      'ERROR ' + nowStamp_() + ' | ' + String(err).slice(0, 140)
    );
    throw err;
  } finally {
    lock.releaseLock();
  }
}

/**
 * Run manually ONCE after both tests are green.
 * Installs one daily trigger near 12:30 Europe/Athens.
 */
function installSofaDailyTrigger() {
  ScriptApp.getProjectTriggers().forEach(trigger => {
    if (trigger.getHandlerFunction() === 'runSofaDaily') {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  ScriptApp.newTrigger('runSofaDaily')
    .timeBased()
    .atHour(12)
    .nearMinute(30)
    .everyDays(1)
    .inTimezone(SOFA_CFG.tz)
    .create();

  setControl_('P2', 'INSTALLED ' + nowStamp_() + ' | daily near 12:30');
}

/**
 * Emergency stop for the Google worker only.
 */
function removeSofaDailyTrigger() {
  let removed = 0;
  ScriptApp.getProjectTriggers().forEach(trigger => {
    if (trigger.getHandlerFunction() === 'runSofaDaily') {
      ScriptApp.deleteTrigger(trigger);
      removed++;
    }
  });
  setControl_('P2', 'TRIGGER REMOVED ' + nowStamp_() + ' | count=' + removed);
}
