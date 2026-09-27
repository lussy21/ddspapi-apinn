const SOFA_DRY_TOURNAMENTS = [
  ['England - Premier League',17],['Germany - Bundesliga',35],['France - Ligue 1',34],
  ['Greece - Super League',185],['Greece - Super League 2',186],['Italy - Serie A',23],
  ['Spain - La Liga',8],['Belgium - Pro League',38],['Denmark - Superliga',39],
  ['Norway - Eliteserien',20],['Netherlands - Eredivisie',37],['Turkey - Super League',52],
  ['Brazil - Serie A',325],['Argentina - Liga Profesional',155],['Sweden - Allsvenskan',40],
  ['USA - MLS',242],['UEFA - Champions League',7],['Finland - Veikkausliiga',41],
  ['Scotland - Premiership',36],['UEFA - Europa League',679],['UEFA - Conference League',17015],
  ['UEFA - Nations League',10783],['CONCACAF - Nations League',14100],
  ['CAF - Africa Cup of Nations Qualifiers',1848],['World Cup Qualification UEFA',11],
  ['World Cup Qualification CAF',13],['World Cup Qualification AFC',308],
  ['World Cup Qualification CONCACAF',14],['World Cup Qualification CONMEBOL',295],
  ['World Cup Qualification OFC',309],['Euro Qualification',27],
  ['AFC Asian Cup Qualification',28],['AFC Asian Cup',246],['Africa Cup of Nations',270],
  ['CONCACAF Gold Cup',140],['Copa America',133],['European Championship',1],['FIFA World Cup',16]
];

function drySeasonId_(tid) {
  const r = sofaFetchJson_('/unique-tournament/' + tid + '/seasons');
  if (r.code !== 200 || !r.json || !Array.isArray(r.json.seasons)) return null;
  const year = Utilities.formatDate(new Date(), SOFA_CFG.tz, 'yyyy');
  const s = r.json.seasons.find(x => String(x.name || '').indexOf(year) >= 0) || r.json.seasons[0];
  return s && s.id ? Number(s.id) : null;
}

function dryEvents_(tid) {
  const sid = drySeasonId_(tid);
  if (!sid) return [];
  const dateKey = todayKey_(), seen = {}, out = [];
  ['last','next'].forEach(dir => {
    for (let page=0; page<4; page++) {
      const r = sofaFetchJson_('/unique-tournament/' + tid + '/season/' + sid + '/events/' + dir + '/' + page);
      if (r.code !== 200 || !r.json) break;
      (r.json.events || []).forEach(e => {
        if (!e || !e.id || seen[e.id]) return;
        seen[e.id] = true;
        const d = Utilities.formatDate(new Date(Number(e.startTimestamp||0)*1000), SOFA_CFG.tz, 'yyyy-MM-dd');
        if (d === dateKey) out.push(e);
      });
      if (!r.json.hasNextPage) break;
    }
  });
  return out;
}

function dryRunSofaAllToday() {
  const sheet = ss_().getSheetByName(SOFA_CFG.pinnacleSheet);
  const lastRow = sheet.getLastRow();
  const rows = lastRow >= 3 ? sheet.getRange(3,1,lastRow-2,18).getValues() : [];
  const fixtures = [];
  const ids = {};
  SOFA_DRY_TOURNAMENTS.forEach(t => {
    try {
      dryEvents_(t[1]).forEach(e => {
        if (!ids[e.id]) { ids[e.id]=true; e.__league=t[0]; fixtures.push(e); }
      });
    } catch (err) {
      Logger.log('TOURNAMENT ERROR | ' + t[0] + ' | ' + err);
    }
  });
  Logger.log('SOFA TODAY FIXTURES=' + fixtures.length);
  let matched=0, withVotes=0;
  rows.forEach((row,i) => {
    const home=String(row[1]||'').trim(), away=String(row[2]||'').trim();
    const fav=String(row[3]||'').trim().toUpperCase();
    const result=String(row[15]||'').trim(), apinn=String(row[17]||'').trim();
    if (!home || !away || !apinn || result || (fav!=='H' && fav!=='A')) return;
    const f=findFixture_(home,away,fixtures);
    if (!f || !f.id) return;
    matched++;
    const vr=sofaFetchJson_('/event/' + f.id + '/votes');
    if (vr.code!==200 || !vr.json) return;
    const pct=favoritePct_(vr.json.vote || vr.json.votes || vr.json,fav);
    if (pct===null) return;
    withVotes++;
    Logger.log('MATCH | row='+(i+3)+' | '+home+' vs '+away+' | APINN='+apinn+' | SOFA='+f.id+' | Sofa='+pct+'% | '+f.__league);
  });
  Logger.log('DRY RUN DONE | fixtures='+fixtures.length+' | matched='+matched+' | withVotes='+withVotes+' | WRITES=0');
}
