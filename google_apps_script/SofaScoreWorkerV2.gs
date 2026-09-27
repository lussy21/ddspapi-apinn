/**
 * SofaScore Google worker V2.
 * Safe scope:
 * - reads today's fixtures from SofaScore tournament pages
 * - writes only PINNACLE!N, SOFA CACHE!A:E, ALERT STATS!O2/P2
 * - never touches odds, turnover, alerts, results, or other columns
 * - no paid APIs
 */

const SOFA_CFG = {
  tz: 'Europe/Athens',
  apiBase: 'https://api.sofascore.com/api/v1',
  spreadsheetId: '1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM',
  pinnacleSheet: 'PINNACLE',
  cacheSheet: 'SOFA CACHE',
  controlSheet: 'ALERT STATS',
  testEventId: 16362020
};

const SOFA_TOURNAMENTS = [
  ['England - Premier League',17],
  ['Germany - Bundesliga',35],
  ['France - Ligue 1',34],
  ['Greece - Super League',185],
  ['Greece - Super League 2',186],
  ['Italy - Serie A',23],
  ['Spain - La Liga',8],
  ['Belgium - Pro League',38],
  ['Denmark - Superliga',39],
  ['Norway - Eliteserien',20],
  ['Netherlands - Eredivisie',37],
  ['Turkey - Super League',52],
  ['Brazil - Serie A',325],
  ['Argentina - Liga Profesional',155],
  ['Sweden - Allsvenskan',40],
  ['USA - MLS',242],
  ['UEFA - Champions League',7],
  ['Finland - Veikkausliiga',41],
  ['Scotland - Premiership',36],
  ['UEFA - Europa League',679],
  ['UEFA - Conference League',17015],
  ['UEFA - Nations League',10783],
  ['CONCACAF - Nations League',14100],
  ['CAF - Africa Cup of Nations Qualifiers',1848],
  ['World Cup Qualification UEFA',11],
  ['World Cup Qualification CAF',13],
  ['World Cup Qualification AFC',308],
  ['World Cup Qualification CONCACAF',14],
  ['World Cup Qualification CONMEBOL',295],
  ['World Cup Qualification OFC',309],
  ['Euro Qualification',27],
  ['AFC Asian Cup Qualification',28],
  ['AFC Asian Cup',246],
  ['Africa Cup of Nations',270],
  ['CONCACAF Gold Cup',140],
  ['Copa America',133],
  ['European Championship',1],
  ['FIFA World Cup',16]
];

function sofaFetchJson_(path) {
  const r = UrlFetchApp.fetch(SOFA_CFG.apiBase + path, {
    method: 'get',
    muteHttpExceptions: true,
    followRedirects: true
  });
  let json = null;
  try { json = JSON.parse(r.getContentText()); } catch (e) {}
  return {code:r.getResponseCode(), json:json};
}

function ss_() {
  return SpreadsheetApp.openById(SOFA_CFG.spreadsheetId);
}

function stamp_() {
  return Utilities.formatDate(new Date(), SOFA_CFG.tz, 'yyyy-MM-dd HH:mm:ss');
}

function today_() {
  return Utilities.formatDate(new Date(), SOFA_CFG.tz, 'yyyy-MM-dd');
}

function control_(cell, value) {
  ss_().getSheetByName(SOFA_CFG.controlSheet).getRange(cell).setValue(value);
}

function ascii_(v) {
  return String(v || '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g,'')
    .toLowerCase().replace(/&/g,' and ')
    .replace(/[^a-z0-9]+/g,' ')
    .replace(/\s+/g,' ').trim();
}

const ALIAS_ = {
  'olympiakos':'olympiacos',
  'olympiakos ii':'olympiacos b',
  'inter miami cf':'inter miami',
  'paris saint germain':'psg',
  'saint truidense':'sint truidense',
  'hacken':'bk hacken',
  'caykur rizespor':'rizespor',
  'republic of ireland':'ireland'
};

function norm_(v) {
  let s = ascii_(v);
  if (ALIAS_[s]) s = ALIAS_[s];
  const drop = {fc:1,cf:1,sc:1,afc:1,fk:1,ac:1,club:1};
  s = s.split(' ').filter(x => !drop[x]).join(' ').trim();
  if (ALIAS_[s]) s = ALIAS_[s];
  return s;
}

function lev_(a,b) {
  if (a===b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;
  let p = Array.from({length:b.length+1},(_,i)=>i);
  for (let i=1;i<=a.length;i++) {
    let c=[i];
    for (let j=1;j<=b.length;j++) {
      const cost=a[i-1]===b[j-1]?0:1;
      c[j]=Math.min(c[j-1]+1,p[j]+1,p[j-1]+cost);
    }
    p=c;
  }
  return p[b.length];
}

function score_(a,b) {
  a=norm_(a); b=norm_(b);
  if (!a || !b) return 0;
  if (a===b) return 1;
  if (a.indexOf(b)>=0 || b.indexOf(a)>=0) return 0.96;
  const edit=1-(lev_(a,b)/Math.max(a.length,b.length));
  const A=new Set(a.split(' ')), B=new Set(b.split(' '));
  let inter=0; A.forEach(x=>{if(B.has(x)) inter++;});
  const union=new Set([...A,...B]).size || 1;
  return Math.max(edit,inter/union);
}

function findFixture_(home,away,fixtures) {
  let best=null, bs=0;
  fixtures.forEach(f=>{
    const h=f.homeTeam&&f.homeTeam.name||'';
    const a=f.awayTeam&&f.awayTeam.name||'';
    const hs=score_(home,h), as=score_(away,a);
    if (hs<0.68 || as<0.68) return;
    const s=(hs+as)/2;
    if (s>bs) {bs=s;best=f;}
  });
  return bs>=0.76 ? best : null;
}

function pct_(payload,fav) {
  const v=(payload&&payload.vote)||(payload&&payload.votes)||payload;
  if (!v || typeof v!=='object') return null;
  const n=(keys)=>{
    for (let i=0;i<keys.length;i++) {
      const x=Number(v[keys[i]]);
      if (Number.isFinite(x)) return x;
    }
    return 0;
  };
  const v1=n(['vote1','home','homeVotes','voteHome']);
  const vx=n(['voteX','draw','drawVotes','voteDraw']);
  const v2=n(['vote2','away','awayVotes','voteAway']);
  const total=v1+vx+v2;
  if (total<=0) return null;
  return Math.round(((fav==='H'?v1:v2)*100)/total);
}

function seasonId_(tid) {
  const r=sofaFetchJson_('/unique-tournament/'+tid+'/seasons');
  if (r.code!==200 || !r.json || !Array.isArray(r.json.seasons)) return null;
  const year=Utilities.formatDate(new Date(),SOFA_CFG.tz,'yyyy');
  const yy=year.slice(-2), yy2=String(Number(year)+1).slice(-2);
  const s=r.json.seasons.find(x=>{
    const n=String(x.name||'');
    return n.indexOf(year)>=0 || n.indexOf(yy+'/'+yy2)>=0 || n.indexOf(yy+'-'+yy2)>=0;
  }) || r.json.seasons[0];
  return s&&s.id ? Number(s.id) : null;
}

function eventsToday_(tid) {
  const sid=seasonId_(tid);
  if (!sid) return [];
  const day=today_(), seen={}, out=[];
  ['last','next'].forEach(dir=>{
    for (let page=0;page<4;page++) {
      const r=sofaFetchJson_('/unique-tournament/'+tid+'/season/'+sid+'/events/'+dir+'/'+page);
      if (r.code!==200 || !r.json) break;
      (r.json.events||[]).forEach(e=>{
        if (!e || !e.id || seen[e.id]) return;
        seen[e.id]=1;
        const d=Utilities.formatDate(new Date(Number(e.startTimestamp||0)*1000),SOFA_CFG.tz,'yyyy-MM-dd');
        if (d===day) out.push(e);
      });
      if (!r.json.hasNextPage) break;
    }
  });
  return out;
}

function allToday_() {
  const byId={};
  SOFA_TOURNAMENTS.forEach(t=>{
    try {
      eventsToday_(t[1]).forEach(e=>{
        if (!byId[e.id]) { e.__league=t[0]; byId[e.id]=e; }
      });
    } catch(e) {
      Logger.log('TOURNAMENT ERROR | '+t[0]+' | '+e);
    }
  });
  return Object.keys(byId).map(k=>byId[k]);
}

function loadCache_() {
  const sh=ss_().getSheetByName(SOFA_CFG.cacheSheet);
  const last=sh.getLastRow();
  const vals=last>=2 ? sh.getRange(2,1,last-1,5).getValues() : [];
  const map={};
  vals.forEach((r,i)=>{
    const a=String(r[0]||'').trim(), s=Number(r[1]||0);
    if (a&&s) map[a]={sofaId:s,row:i+2};
  });
  return {sheet:sh,map:map};
}

function testSofaGoogleConnection() {
  const r=sofaFetchJson_('/event/'+SOFA_CFG.testEventId);
  const e=r.json&&r.json.event;
  if (r.code===200 && e) {
    control_('O2','OK '+stamp_()+' | HTTP 200 | '+e.homeTeam.name+' - '+e.awayTeam.name);
    return true;
  }
  control_('O2','FAILED '+stamp_()+' | HTTP '+r.code);
  return false;
}

function dryRunSofaAllToday() {
  const sh=ss_().getSheetByName(SOFA_CFG.pinnacleSheet);
  const last=sh.getLastRow();
  const rows=last>=3 ? sh.getRange(3,1,last-2,18).getValues() : [];
  const nowMs=Date.now();
  const fixtures=allToday_().filter(f =>
    Number(f.startTimestamp || 0) * 1000 > nowMs
  );
  let matched=0, withVotes=0;
  rows.forEach((row,i)=>{
    const home=String(row[1]||'').trim(), away=String(row[2]||'').trim();
    const fav=String(row[3]||'').trim().toUpperCase();
    const result=String(row[15]||'').trim(), apinn=String(row[17]||'').trim();
    if (!home||!away||!apinn||result||(fav!=='H'&&fav!=='A')) return;
    const f=findFixture_(home,away,fixtures);
    if (!f||!f.id) return;
    matched++;
    const vr=sofaFetchJson_('/event/'+f.id+'/votes');
    if (vr.code!==200||!vr.json) return;
    const p=pct_(vr.json,fav);
    if (p===null) return;
    withVotes++;
    Logger.log('MATCH | row='+(i+3)+' | '+home+' vs '+away+' | Sofa='+p+'% | '+f.__league);
  });
  Logger.log('DRY RUN DONE | fixtures='+fixtures.length+' | matched='+matched+' | withVotes='+withVotes+' | WRITES=0');
}

function runSofaDaily() {
  const lock=LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    const props=PropertiesService.getScriptProperties();
    const today=today_();
    if (props.getProperty('SOFA_VOTES_DONE_DATE')===today) {
      control_('P2','SKIPPED '+stamp_()+' | already done today');
      return;
    }

    control_('P2','RUNNING '+stamp_());
    const nowMs=Date.now();
    const fixtures=allToday_().filter(f =>
      Number(f.startTimestamp || 0) * 1000 > nowMs
    );
    if (!fixtures.length) {
      control_('P2','STOPPED '+stamp_()+' | fixtures=0');
      return;
    }

    const byId={}; fixtures.forEach(f=>{byId[Number(f.id)]=f;});
    const sh=ss_().getSheetByName(SOFA_CFG.pinnacleSheet);
    const last=sh.getLastRow();
    const rows=last>=3 ? sh.getRange(3,1,last-2,18).getValues() : [];
    const cache=loadCache_();

    let matched=0,written=0,cached=0,errors=0;

    rows.forEach((row,i)=>{
      const rowNo=i+3;
      const home=String(row[1]||'').trim(), away=String(row[2]||'').trim();
      const fav=String(row[3]||'').trim().toUpperCase();
      const result=String(row[15]||'').trim(), apinn=String(row[17]||'').trim();

      if (!home||!away||!apinn||result||(fav!=='H'&&fav!=='A')) return;

      let f=null, sofaId=null;
      const cachedInfo=cache.map[apinn];
      if (cachedInfo && byId[cachedInfo.sofaId]) {
        sofaId=cachedInfo.sofaId;
        f=byId[sofaId];
      } else {
        f=findFixture_(home,away,fixtures);
        if (f&&f.id) sofaId=Number(f.id);
      }
      if (!f||!sofaId) return;

      matched++;

      if (!cachedInfo) {
        cache.sheet.appendRow([apinn,sofaId,home,away,today_()]);
        cache.map[apinn]={sofaId:sofaId};
        cached++;
      }

      const vr=sofaFetchJson_('/event/'+sofaId+'/votes');
      if (vr.code!==200||!vr.json) {errors++;return;}
      const p=pct_(vr.json,fav);
      if (p===null) {errors++;return;}

      const oldRaw=row[13];
      const oldNum=(typeof oldRaw==='number')
        ? oldRaw
        : Number(String(oldRaw||'').replace('%','').replace(',','.').trim());
      const val=p;
      const cell=sh.getRange(rowNo,14);
      if (!Number.isFinite(oldNum) || oldNum!==val || typeof oldRaw!=='number') {
        cell.setValue(val);
        written++;
      }
      cell.setNumberFormat('0"%"');
      Utilities.sleep(80);
    });

    props.setProperty('SOFA_VOTES_DONE_DATE',today);
    control_('P2','DONE '+stamp_()+' | fixtures='+fixtures.length+' | matched='+matched+' | cache+='+cached+' | wrote='+written+' | errors='+errors);
  } catch(e) {
    control_('P2','ERROR '+stamp_()+' | '+String(e).slice(0,120));
    throw e;
  } finally {
    lock.releaseLock();
  }
}


function repairTodayNumericVotes() {
  const book=ss_();
  const pin=book.getSheetByName(SOFA_CFG.pinnacleSheet);
  const cache=book.getSheetByName(SOFA_CFG.cacheSheet);
  const day=today_();

  const cacheLast=cache.getLastRow();
  const cacheRows=cacheLast>=2 ? cache.getRange(2,1,cacheLast-1,5).getValues() : [];
  const todayApinn={};
  cacheRows.forEach(r=>{
    const apinn=String(r[0]||'').trim();
    let d='';
    if (r[4] instanceof Date) {
      d=Utilities.formatDate(r[4],SOFA_CFG.tz,'yyyy-MM-dd');
    } else {
      const s=String(r[4]||'').trim();
      if (/^\d{4}-\d{2}-\d{2}$/.test(s)) d=s;
      else if (s) {
        const dt=new Date(s);
        if (!isNaN(dt.getTime())) d=Utilities.formatDate(dt,SOFA_CFG.tz,'yyyy-MM-dd');
      }
    }
    if (apinn && d===day) todayApinn[apinn]=true;
  });

  const last=pin.getLastRow();
  if (last<3) {
    Logger.log('REPAIR DONE | converted=0');
    return;
  }

  const rows=pin.getRange(3,1,last-2,18).getValues();
  let converted=0;
  let formatted=0;

  rows.forEach((row,i)=>{
    const apinn=String(row[17]||'').trim();
    if (!todayApinn[apinn]) return;

    const raw=row[13];
    if (raw==='' || raw===null) return;

    let n=null;
    if (typeof raw==='number') {
      n=raw;
      if (n>=0 && n<=1) n=n*100;
    } else {
      const text=String(raw).trim();
      if (/^\d+(?:[.,]\d+)?%$/.test(text)) {
        n=Number(text.replace('%','').replace(',','.'));
      } else if (/^\d+(?:[.,]\d+)?$/.test(text)) {
        n=Number(text.replace(',','.'));
      }
    }

    if (!Number.isFinite(n)) return;
    n=Math.round(n);

    const cell=pin.getRange(i+3,14);
    if (typeof raw!=='number' || Math.abs(raw-n)>1e-9) {
      cell.setValue(n);
      converted++;
    }
    cell.setNumberFormat('0"%"');
    formatted++;
  });

  SpreadsheetApp.flush();
  Logger.log('REPAIR DONE | converted='+converted+' | formatted='+formatted+' | values preserved');
}

function installSofaDailyTrigger() {
  ScriptApp.getProjectTriggers().forEach(t=>{
    if (t.getHandlerFunction()==='sofaDaily') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('sofaDaily')
    .timeBased()
    .atHour(12)
    .nearMinute(30)
    .everyDays(1)
    .inTimezone(SOFA_CFG.tz)
    .create();
  control_('P2','INSTALLED '+stamp_()+' | daily near 12:30');
}

function removeSofaDailyTrigger() {
  let n=0;
  ScriptApp.getProjectTriggers().forEach(t=>{
    if (t.getHandlerFunction()==='sofaDaily') {ScriptApp.deleteTrigger(t);n++;}
  });
  control_('P2','TRIGGER REMOVED '+stamp_()+' | count='+n);
}
