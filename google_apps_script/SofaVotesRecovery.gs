/**
 * SharpVision | Safe SofaScore votes recovery (2026-11-22).
 *
 * Add as a NEW file in the bound Google Apps Script project (SofaVotesRecovery.gs).
 * This file deliberately defines no automatic triggers and no functions whose
 * names collide with the existing SofaScore workers.
 *
 * Modes:
 * 1. Without a script property: one direct SofaScore API test / cautious recovery.
 * 2. With SV_CRAWLORA_KEY script property: use the Crawlora event-votes endpoint.
 *    This is a separate third-party service: its credits, terms and availability
 *    are independent of the user's Apify subscription.
 *
 * Writes ONLY PINNACLE!N on PRE-KICKOFF rows where N is blank, and
 * ALERT STATS!O2/P2 for progress. Never writes odds, turnover, result P,
 * alerts, SOFA CACHE, or previous Sofa percentages.
 *
 * Run svProbeSofaVotes() first. If it returns 403 or 429, do not run
 * svRecoverSofaVotes() repeatedly; investigate the provider.
 * No cost-incurring Apify actor or Render job is ever started.
 */

var SV_SOFA_RECOVERY = {
  spreadsheetId: '1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM',
  tz: 'Europe/Athens',
  maxCallsPerRun: 10,
  maxCallsPerDay: 60,
  minimumIntervalMs: 1500
};

function svSofaDate_(value) {
  if (value instanceof Date && !isNaN(value.getTime())) {
    return Utilities.formatDate(value, SV_SOFA_RECOVERY.tz, 'yyyy-MM-dd');
  }
  var s = String(value || '').trim();
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10);
  var d = new Date(s);
  return s && !isNaN(d.getTime())
    ? Utilities.formatDate(d, SV_SOFA_RECOVERY.tz, 'yyyy-MM-dd')
    : '';
}

function svSofaKickoff_(value) {
  if (value instanceof Date) return value.getTime();
  var ms = Date.parse(String(value || ''));
  return isNaN(ms) ? null : ms;
}

function svSofaCandidates_() {
  var ss = SpreadsheetApp.openById(SV_SOFA_RECOVERY.spreadsheetId);
  var pin = ss.getSheetByName('PINNACLE');
  var cache = ss.getSheetByName('SOFA CACHE');
  var today = Utilities.formatDate(new Date(), SV_SOFA_RECOVERY.tz, 'yyyy-MM-dd');
  var map = {};
  if (cache.getLastRow() >= 2) {
    cache.getRange(2, 1, cache.getLastRow() - 1, 5).getValues().forEach(function(r) {
      var id = String(r[0] || '').trim();
      var sofaId = Number(r[1] || 0);
      if (id && sofaId && svSofaDate_(r[4]) === today) map[id] = sofaId;
    });
  }


  // Read ONLY the APINN-ID column first. A full A:R read of the historical
  // PINNACLE sheet can reach Apps Script's 6-minute execution limit.
  var n = Math.max(0, pin.getLastRow() - 2);
  var todayIds = Object.keys(map);
  if (!n || !todayIds.length) return {ss: ss, pin: pin, targets: []};
  var ids = pin.getRange(3, 18, n, 1).getDisplayValues(); // R
  var first = -1, last = -1;
  for (var i = 0; i < ids.length; i++) {
    if (Object.prototype.hasOwnProperty.call(map, String(ids[i][0] || '').trim())) {
      if (first < 0) first = i;
      last = i;
    }
  }
  if (first < 0) return {ss: ss, pin: pin, targets: []};

  // Most cached games for a date occupy a compact block near each other.
  // Fetch just that block, not the entire years-long sheet.
  var fromRow = first + 3;
  var count = last - first + 1;
  var rows = pin.getRange(fromRow, 1, count, 18).getValues();
  var kickoffs = pin.getRange(fromRow, 77, count, 1).getValues(); // BY
  var now = Date.now(), targets = [];
  rows.forEach(function(r, i) {
    var apinnId = String(r[17] || '').trim();
    var sofaId = map[apinnId];
    var fav = String(r[3] || '').trim().toUpperCase();
    var kickoff = svSofaKickoff_(kickoffs[i] && kickoffs[i][0]);
    var votesAlreadyPresent = r[13] !== '' && r[13] !== null;
    var hasResult = String(r[15] || '').trim() !== '';
    if (!sofaId || !kickoff || kickoff <= now || hasResult ||
        votesAlreadyPresent || (fav !== 'H' && fav !== 'A')) return;
    if (svSofaDate_(kickoffs[i] && kickoffs[i][0]) !== today) return;
    targets.push({row: fromRow + i, id: sofaId, fav: fav, kickoff: kickoff});
  });
  targets.sort(function(a, b) {return a.kickoff - b.kickoff;});
  return {ss: ss, pin: pin, targets: targets};
}

function svSofaVotePct_(json, fav, provider) {
  if (!json || typeof json !== 'object') return null;
  var root = provider === 'crawlora'
    ? (json.data && (json.data.match_result || json.data.matchResult))
    : (json.vote || json.votes || (json.data && (json.data.vote || json.data.votes)) || json);
  if (!root || typeof root !== 'object') return null;
  function numberFrom(keys) {
    for (var i=0; i<keys.length; i++) {
      if (root[keys[i]] !== undefined && root[keys[i]] !== null &&
          root[keys[i]] !== '') {
        var num = Number(root[keys[i]]);
        if (Number.isFinite(num) && num >= 0) return num;
      }
    }
    return 0;
  }
  var home = numberFrom(['vote1', 'home', 'homeVotes', 'voteHome']);
  var draw = numberFrom(['voteX', 'draw', 'drawVotes', 'voteDraw']);
  var away = numberFrom(['vote2', 'away', 'awayVotes', 'voteAway']);
  var total = home + draw + away;
  return total > 0 ? Math.round(100 * (fav === 'H' ? home : away) / total) : null;
}

function svSofaGetVotes_(eventId, fav) {
  var key = PropertiesService.getScriptProperties().getProperty('SV_CRAWLORA_KEY');
  var provider = key ? 'crawlora' : 'direct';
  var url = key
    ? 'https://api.crawlora.net/api/v1/sofascore/event-votes?id=' + encodeURIComponent(eventId)
    : 'https://api.sofascore.com/api/v1/event/' + encodeURIComponent(eventId) + '/votes';
  var options = {
    method: 'get', muteHttpExceptions: true, followRedirects: true,
    headers: {'Accept': 'application/json'}
  };
  if (key) options.headers['x-api-key'] = key;
  var response = UrlFetchApp.fetch(url, options);
  var code = response.getResponseCode();
  var payload = null;
  try {payload = JSON.parse(response.getContentText());} catch (e) {}
  return {code: code, provider: provider,
    pct: code === 200 ? svSofaVotePct_(payload, fav, provider) : null};
}

function svSofaStatus_(cell, message) {
  var sh = SpreadsheetApp.openById(SV_SOFA_RECOVERY.spreadsheetId)
    .getSheetByName('ALERT STATS');
  sh.getRange(cell).setValue(message.slice(0, 240));
}

function svProbeSofaVotes() {
  var t = svSofaCandidates_().targets[0];
  if (!t) {
    svSofaStatus_('O2', 'SOFA PROBE: no future cached match with missing votes');
    return 'NO_TARGET';
  }
  try {
    var result = svSofaGetVotes_(t.id, t.fav);
    var message = 'SOFA PROBE ' + result.provider + ' | event=' + t.id +
      ' | HTTP ' + result.code + ' | pct=' +
      (result.pct === null ? 'NONE' : result.pct + '%');
    svSofaStatus_('O2', message);
    Logger.log(message);
    return result.code === 200 && result.pct !== null ? 'OK' : 'UNAVAILABLE';
  } catch (e) {
    svSofaStatus_('O2', 'SOFA PROBE ERROR | ' + String(e));
    return 'ERROR';
  }
}

function svRecoverSofaVotes() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    var day = Utilities.formatDate(new Date(), SV_SOFA_RECOVERY.tz, 'yyyy-MM-dd');
    var props = PropertiesService.getScriptProperties();
    var usedDay = props.getProperty('SV_SOFA_DAY');
    var used = usedDay === day ? Number(props.getProperty('SV_SOFA_CALLS') || 0) : 0;
    if (usedDay !== day) {
      props.setProperty('SV_SOFA_DAY', day);
      props.setProperty('SV_SOFA_CALLS', '0');
    }
    var data = svSofaCandidates_();
    var limit = Math.max(0, Math.min(SV_SOFA_RECOVERY.maxCallsPerRun,
      SV_SOFA_RECOVERY.maxCallsPerDay - used, data.targets.length));
    if (!limit) {
      svSofaStatus_('P2', 'SOFA RECOVERY IDLE | candidates=' + data.targets.length +
        ' | calls_today=' + used);
      return;
    }
    var written=0, failures=0, blocked=false, tested=0;
    for (var i=0; i<limit; i++) {
      var t = data.targets[i];
      var result;
      try {
        result = svSofaGetVotes_(t.id, t.fav);
      } catch(e) {
        failures++;
        break; // stop after connection-level failure, no rapid retry loop
      }
      tested++;
      used++;
      props.setProperty('SV_SOFA_CALLS', String(used));
      if (result.code === 403 || result.code === 429 || result.code === 401) {
        blocked=true;
        Logger.log('SOFA RECOVERY BLOCKED | '+result.provider+' HTTP '+result.code);
        break; // never rotate proxies or blindly retry a rejected request
      }
      if (result.code !== 200 || result.pct === null) {
        failures++;
      } else {
        var cell = data.pin.getRange(t.row, 14); // N only
        if (cell.getValue() === '' || cell.getValue() === null) {
          cell.setValue(result.pct);
          cell.setNumberFormat('0"%"');
          written++;
        }
      }
      if (i + 1 < limit) Utilities.sleep(SV_SOFA_RECOVERY.minimumIntervalMs);
    }
    svSofaStatus_('P2', (blocked ? 'BLOCKED' : failures ? 'PARTIAL' : 'RECOVERY') +
      ' ' + day + ' | tested=' + tested + ' | wrote=' + written +
      ' | failed=' + failures + ' | calls_today=' + used +
      ' | remaining_cached=' + Math.max(0, data.targets.length - written));
  } finally {
    lock.releaseLock();
  }
}
