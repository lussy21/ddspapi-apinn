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

/**
 * Optional discovery of NEW SofaScore IDs after the old all-football
 * scheduled-events route was retired. Uses the newer scheduled-tournaments
 * and category date routes, without paying for proxies. Failure is nonfatal:
 * cached IDs are still handled by the votes worker.
 */
function sofaDiscoverCachedFixtures_(missing,cache,teamScoreFn) {
  let added=0,requests=0,blocked=false;
  const discoveryStart=Date.now(),discoveryLimitMs=85000;
  const grouped={};
  missing.forEach(r=>{
    const day=Utilities.formatDate(new Date(r.kickoff),SOFA_CFG.tz,'yyyy-MM-dd');
    if(!grouped[day])grouped[day]=[];
    grouped[day].push(r);
  });
  const categoryKey=s=>String(s||'').normalize('NFD')
    .replace(/[\u0300-\u036f]/g,'').toLowerCase()
    .replace(/[^a-z0-9]+/g,' ').trim();
  const matchCountry=(league,category)=>{
    let pref=categoryKey(String(league||'').split(' - ')[0]);
    let cat=categoryKey(category);
    if(pref==='uefa')pref='europe';
    if(pref==='usa')pref='united states';
    if(pref==='turkey')pref='turkiye';
    if(pref==='scotland')pref='scotland';
    return !!(pref&&cat&&(pref===cat||pref.indexOf(cat)>=0||cat.indexOf(pref)>=0));
  };
  const used={};
  Object.keys(grouped).slice(0,2).forEach(day=>{
    if(blocked||requests>=12||Date.now()-discoveryStart>discoveryLimitMs)return;
    let schedule;
    try{
      schedule=sofaFetchJson_('/sport/football/scheduled-tournaments/'+day+'/page/1');
      requests++;
    }catch(e){Logger.log('SOFA DISCOVERY SCHEDULE ERROR | '+e);return;}
    if(schedule.code===401||schedule.code===403||schedule.code===429){
      blocked=true;return;
    }
    const tournaments=schedule.json&&schedule.json.tournaments;
    if(schedule.code!==200||!Array.isArray(tournaments)){
      Logger.log('SOFA DISCOVERY SCHEDULE HTTP '+schedule.code+' | '+day);
      return;
    }
    const cats={};
    tournaments.forEach(t=>{
      const c=(t.tournament&&t.tournament.category)||t.category||
        (t.uniqueTournament&&t.uniqueTournament.category)||{};
      if(!c.id||!c.name)return;
      if(grouped[day].some(r=>matchCountry(r.league,c.name)))cats[c.id]=c;
    });
    Object.keys(cats).forEach(catId=>{
      if(blocked||requests>=12||Date.now()-discoveryStart>discoveryLimitMs)return;
      let result;
      try{
        result=sofaFetchJson_('/category/'+catId+'/scheduled-events/'+day);
        requests++;
      }catch(e){Logger.log('SOFA DISCOVERY CATEGORY ERROR | '+e);return;}
      if(result.code===401||result.code===403||result.code===429){blocked=true;return;}
      const events=result.json&&result.json.events;
      if(result.code!==200||!Array.isArray(events))return;
      grouped[day].forEach(t=>{
        if(cache.byApinn[t.apinn])return;
        const candidates=events.filter(e=>
          e&&e.id&&e.homeTeam&&e.awayTeam &&
          Number.isFinite(Number(e.startTimestamp)) &&
          Math.abs(Number(e.startTimestamp)*1000-t.kickoff)<=2*3600*1000
        );
        const event=findFixture_(t.home,t.away,candidates);
        if(!event||used[event.id])return;
        const hs=teamScoreFn(t.home,event.homeTeam.name);
        const as=teamScoreFn(t.away,event.awayTeam.name);
        if(hs<0.86||as<0.86)return;
        cache.sheet.appendRow([t.apinn,Number(event.id),t.home,t.away,day]);
        cache.byApinn[t.apinn]={sofaId:Number(event.id)};
        used[event.id]=true;
        added++;
        Logger.log('SOFA DISCOVERY VERIFIED | '+t.home+' - '+t.away+
          ' | apinn='+t.apinn+' | sofa='+event.id);
      });
    });
  });
  Logger.log('SOFA DISCOVERY | found='+added+' | calls='+requests+' | blocked='+blocked);
  return {added:added,calls:requests,blocked:blocked};
}

function runSofaDaily() {
  // This function is called by the existing sofaDaily Apps Script trigger.
  // The former sport-wide /scheduled-events endpoint now returns HTTP 404.
  // Work from VERIFIED APINN -> Sofa event IDs already in SOFA CACHE.
  const lock=LockService.getScriptLock();
  if(!lock.tryLock(1000))return;
  try{
    const runStarted=Date.now();
    const props=PropertiesService.getScriptProperties();
    const today=todayKey_();
    const now=Date.now(),until=now+24*60*60*1000;
    const previousDay=props.getProperty('SOFA_VOTE_CALL_DAY');
    let calls=previousDay===today?Number(props.getProperty('SOFA_VOTE_CALLS')||0):0;
    if(previousDay!==today){
      props.setProperty('SOFA_VOTE_CALL_DAY',today);
      props.setProperty('SOFA_VOTE_CALLS','0');
      props.deleteProperty('SOFA_VOTE_NEXT_AT');
      props.setProperty('SOFA_VOTES_CURSOR','0');
    }
    setControl_('P2','RUNNING '+nowStamp_()+' | cache-first; no paid API');
    const ss=ss_(),pin=ss.getSheetByName(SOFA_CFG.pinnacleSheet);
    const cached=loadCache_(); // existing event IDs, no tournament fetch required
    const rowCount=Math.max(0,pin.getLastRow()-2);
    if(!rowCount){
      setControl_('P2','IDLE '+nowStamp_()+' | PINNACLE empty');
      return;
    }
    const eventIds=pin.getRange(3,18,rowCount,1).getDisplayValues();
    const kickoffs=pin.getRange(3,77,rowCount,1).getValues();
    const unknownIndexes=[];
    for(let i=0;i<rowCount;i++){
      const timestamp=new Date(kickoffs[i][0]).getTime();
      if(!Number.isFinite(timestamp)||timestamp<=now||timestamp>until)continue;
      const eventId=String(eventIds[i][0]||'').trim();
      if(eventId&&!cached.byApinn[eventId])unknownIndexes.push(i);
    }
    let discovered=0;
    // Discovery is best-effort and runs once per day, not on every
    // short continuation. Cached votes continue even if discovery fails.
    if(unknownIndexes.length&&props.getProperty('SOFA_DISCOVERY_DAY')!==today){
      props.setProperty('SOFA_DISCOVERY_DAY',today);
      try{
        const names=pin.getRange(3,1,rowCount,3).getValues();
        const missing=unknownIndexes.map(i=>({
          apinn:String(eventIds[i][0]||'').trim(),
          home:String(names[i][1]||'').trim(),
          away:String(names[i][2]||'').trim(),
          league:String(names[i][0]||'').trim(),
          kickoff:new Date(kickoffs[i][0]).getTime()
        })).filter(r=>r.home&&r.away&&r.league);
        discovered=sofaDiscoverCachedFixtures_(missing,cached,teamScore_).added;
      }catch(err){Logger.log('SOFA DISCOVERY SKIPPED | '+err);}
    }
    let first=-1,last=-1,unmapped=0;
    for(let i=0;i<rowCount;i++){
      const timestamp=new Date(kickoffs[i][0]).getTime();
      if(!Number.isFinite(timestamp)||timestamp<=now||timestamp>until)continue;
      const eventId=String(eventIds[i][0]||'').trim();
      if(!eventId)continue;
      if(cached.byApinn[eventId]){
        if(first<0)first=i;
        last=i;
      }else unmapped++;
    }
    if(first<0){
      setControl_('P2','NO CACHED TARGETS '+nowStamp_()+
        ' | unmapped_future='+unmapped+' | HTTP schedule 404 bypassed');
      return;
    }
    const from=first+3,len=last-first+1;
    const rows=pin.getRange(from,1,len,18).getValues();
    const times=pin.getRange(from,77,len,1).getValues();
    const targets=[];
    rows.forEach((r,i)=>{
      const id=String(r[17]||'').trim();
      const entry=cached.byApinn[id];
      const timestamp=new Date(times[i][0]).getTime();
      const side=String(r[3]||'').trim().toUpperCase();
      const vote=r[13],result=String(r[15]||'').trim();
      if(!entry||!Number.isFinite(timestamp)||timestamp<=now||timestamp>until||
        (side!=='H'&&side!=='A')||result||!r[1]||!r[2]||
        (vote!==''&&vote!==null&&vote!==undefined))return;
      targets.push({row:from+i,sofaId:entry.sofaId,fav:side});
    });
    targets.sort((a,b)=>a.row-b.row);
    const maxCalls=Math.min(16,Math.max(0,80-calls),targets.length);
    const deadline=260000;
    const offset=targets.length?
      Number(props.getProperty('SOFA_VOTES_CURSOR')||0)%targets.length:0;
    let checked=0,written=0,errors=0,blocked=false;
    for(let i=0;i<maxCalls;i++){
      if(Date.now()-runStarted>deadline)break;
      const t=targets[(offset+i)%targets.length];let res;
      try{res=sofaFetchJson_('/event/'+t.sofaId+'/votes');}
      catch(err){errors++;Logger.log('SOFA VOTE FETCH FAILED | '+t.row+' | '+err);break;}
      checked++;calls++;
      props.setProperty('SOFA_VOTE_CALLS',String(calls));
      if(res.code===401||res.code===403||res.code===429){
        blocked=true;
        Logger.log('SOFA VOTES BLOCKED | HTTP '+res.code+' | row='+t.row);
        break;
      }
      if(res.code!==200||!res.json){errors++;continue;}
      const payload=res.json.vote||res.json.votes||res.json;
      const pct=favoritePct_(payload,t.fav);
      if(pct===null||!Number.isFinite(pct)||pct<0||pct>100){errors++;continue;}
      const cell=pin.getRange(t.row,14);
      if(String(cell.getDisplayValue()||'').trim())continue;
      cell.setValue(pct);
      cell.setNumberFormat('0"%"');
      written++;
      Logger.log('SOFA VOTE SAVED | '+t.row+' | '+pct+'%');
    }
    SpreadsheetApp.flush();
    if(targets.length&&checked){
      props.setProperty('SOFA_VOTES_CURSOR',String((offset+checked)%targets.length));
    }
    // Resume incomplete daily work in a separate short execution. No new
    // permanent triggers, Apify calls or paid proxies.
    let queued=false;
    if(!blocked&&checked>0&&targets.length>checked&&calls<80){
      const next=Number(props.getProperty('SOFA_VOTE_NEXT_AT')||0);
      if(next<=Date.now()){
        try{
          ScriptApp.newTrigger('sofaDaily').timeBased().after(10*60*1000).create();
          props.setProperty('SOFA_VOTE_NEXT_AT',String(Date.now()+10*60*1000));
          queued=true;
        }catch(err){Logger.log('SOFA VOTE CONTINUATION UNAVAILABLE | '+err);}
      }
    }
    const status=blocked?'BLOCKED':errors?'PARTIAL':queued?'CONTINUE':
      targets.length===0?'DONE':'CHECKED';
    setControl_('P2',status+' '+nowStamp_()+
      ' | cache='+Object.keys(cached.byApinn).length+
      ' | candidates='+targets.length+' | checked='+checked+' | wrote='+written+
      ' | unmapped='+unmapped+' | discovered='+discovered+' | errors='+errors+' | calls_today='+calls+
      ' | next='+queued);
  }catch(err){
    setControl_('P2','ERROR '+nowStamp_()+' | '+String(err).slice(0,160));
    throw err;
  }finally{lock.releaseLock();}
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
