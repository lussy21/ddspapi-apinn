"use strict";
const $=id=>document.getElementById(id);
let matches=[],current=null,leaguesSelected=null,history={all:[],side:[]},mode="strict",tab="open",historyTab="all",lastOpinion=null,loadedAt=null;
const excluded=/(Finland|Norway|Sweden|Denmark|Scotland|USA|Brazil|Argentina|ΕΘΝΙΚΕΣ|Nations League)/i;
const store=(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}};
const read=(k,d)=>{try{let v=localStorage.getItem(k);return v===null?d:JSON.parse(v)}catch(e){return d}};
let favorites=read("sv_live_faves",[]),journal=read("sv_live_journal",[]),savedLeagues=read("sv_live_leagues",null);
// Default to favorite on every new match and page opening.
let histMarket="fav";
let autoLedger=read("sv_prelock_v4",{});if(!autoLedger||Array.isArray(autoLedger)||typeof autoLedger!=="object")autoLedger={};
let compareMatchId=null;
let marketWatchItems=[],marketHunterItems=[],marketToolTab="analyst";
let marketToolLog=read("sv_market_tools_v1",[]);
if(!Array.isArray(marketToolLog))marketToolLog=[];
function num(v,col){if(typeof v==="number")return Number.isFinite(v)?v:null;let s=String(v??"").replace(/[%€\s]/g,"");if(!s)return null;if(s.includes(",")&&s.includes("."))s=s.replace(/\./g,"").replace(",",".");else if(s.includes(","))s=s.replace(",",".");else if([10,19,22].includes(col)&&/^\d{1,3}(\.\d{3})+$/.test(s))s=s.replace(/\./g,"");let n=Number(s);return Number.isFinite(n)?n:null}
const nf=(v,d=1)=>v!==null&&Number.isFinite(v)?new Intl.NumberFormat("el-GR",{minimumFractionDigits:d,maximumFractionDigits:d}).format(v):"—";
const price=v=>nf(v,3),per=v=>v===null?"—":nf(v,1)+"%",money=v=>v===null?"—":new Intl.NumberFormat("el-GR",{maximumFractionDigits:0}).format(v)+" €";
const safe=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const norm=s=>String(s??"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().trim();
const name=x=>x.h+" – "+x.a, fave=x=>x.f==="H"?x.h:x.a, key=x=>[x.lg,x.h,x.a].map(norm).join("|");
const parsedScore=x=>{let m=String(x.r||"").match(/^\s*(\d+)\s*[-:]\s*(\d+)\s*$/);return m?[+m[1],+m[2]]:null};
const finished=x=>parsedScore(x)!==null;
function won(x){let s=parsedScore(x);return s?(x.f==="H"?s[0]>s[1]:s[1]>s[0]):null}
function parseRow(r,i){
  const display={
    o:r[4],m:r[5],l:r[6],co:r[7],cm:r[8],cl:r[9],
    v:r[10],p:r[11],contra:r[12],s:r[13],r:r[15],
    v0:r[19],p0:r[20],contra0:r[21],
    v90:r[22],p90:r[23],contra90:r[24],
    percentile90:r[63],percentile:r[64]
  };
  return {
    id:i+3, lg:String(r[0]||""),h:String(r[1]||""),a:String(r[2]||""),f:r[3],
    o:num(r[4],4),m:num(r[5],5),l:num(r[6],6),
    co:num(r[7],7),cm:num(r[8],8),cl:num(r[9],9),
    v:num(r[10],10),p:num(r[11],11),contra:num(r[12],12),
    s:num(r[13],13),alert:String(r[14]||""),r:String(r[15]||""),
    v0:num(r[19],19),p0:num(r[20],20),contra0:num(r[21],21),
    v90:num(r[22],22),p90:num(r[23],23),contra90:num(r[24],24),
    kickoff:String(r[76]||""),
    sourceRank:num(r[64],64),source90Rank:num(r[63],63),
    rank:null,rankEstimated:false,formats:{},display
  };
}
function excelValue(x,key){const v=x.display&&x.display[key];return v!==undefined&&v!==null&&String(v).trim()!==""?String(v):"—"}
// Identical turnover league-relative percentile formula and breakpoints to PINNACLE column K.
// Excel counts ALL numeric K values in the same league, including unfinished fixtures.
function setupRanks(){
  // BM/BL are the actual Excel percentile cells. Recompute only while the
  // older 25-column bridge is still active and label the result estimated.
  const pools={};
  for(const x of matches)if(Number.isFinite(x.v)&&x.v>=0)(pools[x.lg]??=[]).push(x.v);
  for(const x of matches){
    const pool=pools[x.lg]||[];
    x.leagueN=pool.length;
    x.rankEstimated=!Number.isFinite(x.sourceRank);
    x.rank=Number.isFinite(x.sourceRank)?x.sourceRank:
      Number.isFinite(x.v)&&x.v>=0 ? 100*(pool.filter(n=>n<=x.v).length-1)/Math.max(1,pool.length-1) : null;
  }
}
function band(v){if(v===null||!Number.isFinite(v))return 0;return v<=35?1:v<=75?2:v<=87?3:4}
function pband(v,type){
  if(v===null||!Number.isFinite(v))return 0;
  if(type==="contra")return v>=32?4:v>=26?2:0;
  if(type==="sofa")return v>=82?4:v>=75?3:0;
  return v>=82?4:v>=75?2:0;
}
function color(id,level,type,sourceStyle){
  const target=$(id);
  target.className="metric"+(level?" excel-"+type+"-"+level:"");
  target.style.backgroundColor="";
  target.style.color="";
  if(!Array.isArray(sourceStyle))return;
  const bg=sourceStyle[0],fg=sourceStyle[1];
  if(typeof bg!=="string"||!/^#[0-9a-f]{6}$/i.test(bg)||bg.toLowerCase()==="#ffffff")return;
  target.className="metric excel-source";
  target.style.backgroundColor=bg;
  const hex=bg.slice(1);
  const rgb=[0,2,4].map(i=>parseInt(hex.slice(i,i+2),16)/255);
  const bright=rgb[0]*.299+rgb[1]*.587+rgb[2]*.114;
  target.style.color=typeof fg==="string"&&/^#[0-9a-f]{6}$/i.test(fg)?fg:(bright>.57?"#1e1e1e":"#ffffff");
}
function snapColor(id,level,type,format){
  const el=$(id);el.className="snapcell"+(level?" excel-snap-"+type+"-"+level:"");
  el.style.backgroundColor="";el.style.color="";
  if(Array.isArray(format)&&/^#[0-9a-f]{6}$/i.test(format[0]||"")&&format[0].toLowerCase()!=="#ffffff"){
    el.className="snapcell excel-snap-source";
    el.style.backgroundColor=format[0];
    el.style.color=/^#[0-9a-f]{6}$/i.test(format[1]||"")?format[1]:"#1e1e1e";
  }
}
function allLeagues(){return [...new Set(matches.map(x=>x.lg))].filter(Boolean).sort((a,b)=>a.localeCompare(b))}
function setupLeagues(){let names=allLeagues();leaguesSelected=Array.isArray(savedLeagues)?savedLeagues.filter(n=>names.includes(n)):names.filter(n=>!excluded.test(n));paintSettings()}
function paintSettings(){$("checks").innerHTML=allLeagues().map((l,i)=>'<label><input type="checkbox" data-league="'+safe(l)+'" '+(leaguesSelected.includes(l)?"checked":"")+'> '+safe(l)+'</label>').join("");$("checks").querySelectorAll("input").forEach(i=>i.addEventListener("change",()=>{leaguesSelected=i.checked?[...leaguesSelected,i.dataset.league]:leaguesSelected.filter(l=>l!==i.dataset.league);savedLeagues=leaguesSelected;store("sv_live_leagues",savedLeagues);clearOpinion();renderHistory()}))}
function activeList(){let q=norm($("search").value);let aliases={αστον:"aston",βιλα:"villa",φεγενορντ:"feyenoord",σιτι:"city",παρι:"paris",ντορτμουντ:"dortmund",ρεαλ:"real",κομο:"como"};for(let [greek,english] of Object.entries(aliases))if(q.includes(greek))q=q.replace(greek,english);let lg=$("leagueFilter").value;let items=matches.filter(x=>!lg||x.lg===lg);if(q)items=items.filter(x=>norm(name(x)+" "+x.lg).includes(q));else if(tab==="open")items=items.filter(x=>!finished(x));else if(tab==="faves")items=items.filter(x=>favorites.includes(key(x)));else items=items.filter(finished);return items.slice().reverse().slice(0,80)}
function fillLeagueFilter(){let old=$("leagueFilter").value;$("leagueFilter").innerHTML='<option value="">Όλα τα πρωταθλήματα</option>'+allLeagues().map(x=>'<option value="'+safe(x)+'">'+safe(x)+'</option>').join("");$("leagueFilter").value=allLeagues().includes(old)?old:""}
function listMatches(){let v=activeList();$("matchCount").textContent=v.length+(v.length>=80?"+":"")+" αγώνες";$("matchList").innerHTML=v.length?v.map(x=>'<div class="matchitem '+(current&&x.id===current.id?"active":"")+'"><button class="star '+(favorites.includes(key(x))?"on":"")+'" data-star="'+x.id+'" aria-label="Αγαπημένο">★</button><button class="matchtext" data-match="'+x.id+'" style="background:none;border:0;padding:0;text-align:left"><b>'+safe(name(x))+'</b><small>'+safe(x.lg)+(finished(x)?" · "+safe(x.r):" · Χωρίς τελικό σκορ")+'</small></button></div>').join(""):'<div class="empty">Δεν βρέθηκαν αγώνες. Δοκίμασε άλλη αναζήτηση ή καρτέλα.</div>';document.querySelectorAll("[data-match]").forEach(b=>b.addEventListener("click",()=>select(+b.dataset.match)));document.querySelectorAll("[data-star]").forEach(b=>b.addEventListener("click",()=>{let x=matches.find(z=>z.id===+b.dataset.star),k=key(x);favorites=favorites.includes(k)?favorites.filter(z=>z!==k):[...favorites,k];store("sv_live_faves",favorites);listMatches()}))}
function select(id){current=matches.find(x=>x.id===id);histMarket="fav";compareMatchId=null;clearOpinion();listMatches();render()}
function render(){
  if(!current)return;
  const x=current,styles=x.formats||{};
  $("matchLeague").textContent=x.lg;$("matchTitle").textContent=name(x);
  $("favLabel").textContent="Φαβορί: "+fave(x)+" · "+(x.f==="H"?"Εντός":"Εκτός");
  const result=$("result");
  result.textContent=finished(x)?"Τελικό "+x.r:"Χωρίς τελικό σκορ";
  result.style.backgroundColor="";
  result.style.color="";
  if(finished(x)&&Array.isArray(styles["15"])){
    const pair=styles["15"];
    if(/^#[0-9a-f]{6}$/i.test(pair[0]||"")&&pair[0].toLowerCase()!=="#ffffff"){
      result.style.backgroundColor=pair[0];result.style.color=pair[1]||"#1e1e1e";
    }
  }
  $("turnover").textContent=excelValue(x,"v");
  const rankBand=band(x.rank);
  $("turnHint").textContent=x.rank===null?"Χωρίς κατάταξη τζίρου":
    "Στάδιο "+rankBand+"/4 · "+(x.rankEstimated?"εκτίμηση ":"")+"εκατοστημόριο "+(x.rankEstimated?nf(x.rank,1):excelValue(x,"percentile"));
  color("turnBox",rankBand,"turn",styles["10"]);
  $("favPercent").textContent=excelValue(x,"p");
  color("favBox",pband(x.p,"fav"),"fav",styles["11"]);
  $("contraPercent").textContent=excelValue(x,"contra");
  color("contraBox",pband(x.contra,"contra"),"contra",styles["12"]);
  $("sofa").textContent=excelValue(x,"s");
  color("sofaBox",pband(x.s,"sofa"),"sofa",styles["13"]);
  for(const k of ["o","m","l","co","cm","cl"])$(k).textContent=excelValue(x,k);
  $("v0snap").textContent=excelValue(x,"v0");
  $("v90snap").textContent=excelValue(x,"v90");
  $("vsnap").textContent=excelValue(x,"v");
  $("p0snap").textContent=excelValue(x,"p0");
  $("p90snap").textContent=excelValue(x,"p90");
  $("psnap").textContent=excelValue(x,"p");
  $("contra0snap").textContent=excelValue(x,"contra0");
  $("contra90snap").textContent=excelValue(x,"contra90");
  $("contrasnap").textContent=excelValue(x,"contra");
  snapColor("v90snap",band(x.source90Rank),"turn",styles["22"]);
  snapColor("vsnap",rankBand,"turn",styles["10"]);
  snapColor("p0snap",pband(x.p0,"fav"),"fav",styles["20"]);
  snapColor("p90snap",pband(x.p90,"fav"),"fav",styles["23"]);
  snapColor("psnap",pband(x.p,"fav"),"fav",styles["11"]);
  snapColor("contra0snap",pband(x.contra0,"contra"),"contra",styles["21"]);
  snapColor("contra90snap",pband(x.contra90,"contra"),"contra",styles["24"]);
  snapColor("contrasnap",pband(x.contra,"contra"),"contra",styles["12"]);
  const alertBox=$("excelAlert");
  alertBox.classList.toggle("hide",!x.alert);
  alertBox.textContent=x.alert?"Σήμανση Excel: "+x.alert:"";
  alertBox.style.backgroundColor="";
  alertBox.style.color="";
  const af=styles["14"];
  if(x.alert&&Array.isArray(af)&&/^#[0-9a-f]{6}$/i.test(af[0]||"")&&af[0].toLowerCase()!=="#ffffff"){
    alertBox.style.backgroundColor=af[0];alertBox.style.color=/^#[0-9a-f]{6}$/i.test(af[1]||"")?af[1]:"#1e1e1e";
  }
  if(!$("fingerprintDetails").classList.contains("hide"))renderFingerprint();
  renderMarketObservation();renderAutoCard();renderHistory();renderArchive();
}
const change=(a,b)=>a!==null&&b!==null&&a>0?(b/a-1)*100:null;
// Every comparison uses all shared available market signals; never make up missing
// 90-minute or contra odds. Require a candidate to provide all signals the target has.
// The historical search is distinct from the Excel's own alerts.
// Same source data, two separate lenses: favorite or contra +0.5.
const signalSpecs=[
  {key:"openFav", fn:x=>x.o, tol:.19, weight:2.1, cTol:.31,cWeight:.50},
  {key:"currentFav", fn:x=>x.l, tol:.21, weight:2.1, cTol:.32,cWeight:.65},
  {key:"favMove", fn:x=>change(x.o,x.l), tol:13, weight:1.6,cTol:19,cWeight:.55},
  {key:"favMoney", fn:x=>x.p, tol:11, weight:1.8,cTol:19,cWeight:.20},
  {key:"sofa", fn:x=>x.s, tol:18, weight:1.1,cTol:24,cWeight:.70},
  {key:"relativeTurnover", fn:x=>x.rank, tol:29, weight:1.5,cTol:29,cWeight:1.5},
  {key:"earlyFavMoney", fn:x=>x.p0, tol:14, weight:.9,cTol:20,cWeight:.25},
  {key:"openContra", fn:x=>x.co, tol:.30, weight:1.1,cTol:.28,cWeight:2.6},
  {key:"currentContra", fn:x=>x.cl, tol:.31, weight:1.1,cTol:.29,cWeight:2.8},
  {key:"contraMove", fn:x=>change(x.co,x.cl), tol:15, weight:1.1,cTol:13,cWeight:2},
  {key:"favOpenTo90", fn:x=>change(x.o,x.m), tol:8, weight:1.3,cTol:15,cWeight:.35},
  {key:"fav90ToNow", fn:x=>change(x.m,x.l), tol:8, weight:1.3,cTol:15,cWeight:.35},
  {key:"contraOpenTo90", fn:x=>change(x.co,x.cm), tol:11, weight:1,cTol:10,cWeight:1.5},
  {key:"contra90ToNow", fn:x=>change(x.cm,x.cl), tol:11, weight:1,cTol:10,cWeight:1.5},
  {key:"contraMoney", fn:x=>x.contra!==null?x.contra:x.p!==null?100-x.p:null, tol:11, weight:0,cTol:11,cWeight:2.5},
  {key:"earlyContraMoney", fn:x=>x.contra0!==null?x.contra0:x.p0!==null?100-x.p0:null, tol:14, weight:0,cTol:15,cWeight:1.1},
  {key:"90ContraMoney", fn:x=>x.contra90!==null?x.contra90:x.p90!==null?100-x.p90:null, tol:15, weight:0,cTol:15,cWeight:1.2}
];
const usable=v=>v!==null&&Number.isFinite(v);
// Every stored call is an immutable, timestamped snapshot from BEFORE kickoff.
// Browser storage is local; no retrospective calls and no fake 24/7 tracking.
function kickoffMs(x){
 const k=String(x?.kickoff||"");
 const t=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(k)?Date.parse(k):NaN;
 return Number.isFinite(t)?t:null;
}
function autoKey(x){return key(x)+"|"+String(x.kickoff||"").slice(0,10);}
function kickoffLabel(x){
 const t=kickoffMs(x);
 return t===null?"Άγνωστη έναρξη":new Date(t).toLocaleString("el-GR",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"});
}
const levelNames={1:"Αδύναμη",2:"Μέτρια",3:"Ισχυρή"};
// SHARPVISION MARKET CASEBOOK v4
// "Psychologist" means measured similar historical situations, not guessed
// bookmaker motives. Every eligible historical fixture counts at most once.
// The cases are recomputed from finished PINNACLE rows; records of locked calls
// are kept separately. No Excel alerts or alert scores are read here.
function svCase(z){
  const values=[z.v,z.v90,z.p,z.p90,z.m,z.l,z.rank];
  if(!values.every(usable)||z.v90<=0||z.v<=z.v90||z.m<=1.01||z.l<=1.01||
     z.p<0||z.p>100||z.p90<0||z.p90>100)return null;
  const newTurnover=z.v-z.v90;
  const favorAdded=z.v*z.p/100-z.v90*z.p90/100;
  // If cumulative turnover corrections make a share impossible, discard row.
  const share=favorAdded/newTurnover;
  if(!Number.isFinite(share)||share<-.01||share>1.01)return null;
  const favShare=Math.max(0,Math.min(1,share));
  const growth=newTurnover/z.v90;
  const oddsMove=(z.l/z.m-1)*100;
  const priceState=oddsMove<=-.7?"down":oddsMove>=.7?"up":"flat";
  const moneyState=growth>=.25&&favShare>=.70?"fav":
    growth>=.25&&favShare<=.30?"contra":"split";
  const liquidity=z.rank>=75?"high":z.rank>=35?"medium":"low";
  return {
    moneyState,priceState,liquidity,
    newTurnover,favorAdded,contraAdded:newTurnover-favorAdded,
    favShare,growth,oddsMove,rank:z.rank,price:z.m,
    key:moneyState+"|"+priceState
  };
}
const svPriceLabels={down:"Πτώση απόδοσης",flat:"Σταθερή απόδοση",up:"Άνοδος απόδοσης"};
const svCashLabels={fav:"Έντονη εισροή προς φαβορί",contra:"Έντονη εισροή προς κόντρα",
  split:"Μικτή ή ήπια νέα ροή"};
const svAvg=(xs)=>xs.length?xs.reduce((sum,v)=>sum+v,0)/xs.length:null;
function svMarketExpected(z){
  // Victory of favorite and "contra +0.5" are complementary settlements.
  // Fair market reference is not a prediction, merely a margin-stripped price.
  if(!usable(z.l)||!usable(z.cl)||z.l<=1.01||z.cl<=1.01)return null;
  const fav=1/z.l,contra=1/z.cl;
  return fav/(fav+contra);
}
function svProfile(base,items){
  const cases=items.map(rec=>rec.x||rec);
  const n=cases.length,wins=cases.filter(z=>won(z)===true).length;
  const rated=cases.filter(z=>svMarketExpected(z)!==null);
  const e=rated.reduce((sum,z)=>sum+svMarketExpected(z),0);
  const varSum=rated.reduce((sum,z)=>{const p=svMarketExpected(z);return sum+p*(1-p)},0);
  const ratedWins=rated.filter(z=>won(z)===true).length;
  return {n,wins,winPct:n?100*wins/n:null,priceN:rated.length,
    expectedPct:rated.length?100*e/rated.length:null,
    priceWins:ratedWins,
    z:varSum>0?(ratedWins-e)/Math.sqrt(varSum):0,
    advantage:rated.length?(ratedWins-e)/rated.length:null,
    priceMove:base?.priceState||null};
}
function svMoneyCases(target,prior){
  const pattern=svCase(target);
  if(!pattern)return null;
  const historical=[];
  for(const z of prior){
    if(!finished(z)||autoKey(z)===autoKey(target))continue;
    const c=svCase(z);
    if(!c)continue;
    historical.push({x:z,c});
  }
  // All comparisons below are observed, finished source rows.
  const regime=historical.filter(rec=>rec.c.moneyState===pattern.moneyState);
  const comparable=rec=>Math.abs(Math.log(rec.c.price/pattern.price))<=Math.log(1.37)&&
    Math.abs(rec.c.rank-pattern.rank)<=40;
  const broad=rec=>Math.abs(Math.log(rec.c.price/pattern.price))<=Math.log(1.62)&&
    Math.abs(rec.c.rank-pattern.rank)<=55;
  const caseMatches=regime.filter(rec=>rec.c.priceState===pattern.priceState);
  let peers=caseMatches.filter(comparable),scope="παρόμοιες αποδόσεις και επίπεδο τζίρου";
  if(peers.length<12){
    peers=caseMatches.filter(broad);scope="διευρυμένη περιοχή αποδόσεων και τζίρου";
  }
  const score=rec=>
    Math.abs(Math.log(rec.c.price/pattern.price))*3.0+
    Math.abs(rec.c.rank-pattern.rank)/110+
    Math.abs(rec.c.favShare-pattern.favShare)*1.1+
    Math.abs(Math.log((1+rec.c.growth)/(1+pattern.growth)))*.22+
    (rec.x.f===target.f?0:.06);
  peers.sort((a,b)=>score(a)-score(b));
  if(peers.length>55)peers.length=55;
  // Reference group with similar favorite prices/league turnover, regardless
  // of odds move or inflow; used to guard against base-rate illusions.
  const base=historical.filter(rec=>comparable(rec));
  const profile=svProfile(pattern,peers);
  const baseline=svProfile(pattern,base);
  const states=["down","flat","up"].map(state=>{
    const recs=regime.filter(rec=>rec.c.priceState===state&&comparable(rec));
    const stats=svProfile({priceState:state},recs);
    return {state,n:stats.n,wins:stats.wins,winPct:stats.winPct,
      expectedPct:stats.expectedPct,priceN:stats.priceN};
  });
  const examples=peers.slice(0,6).map(rec=>({
    match:name(rec.x),league:rec.x.lg,score:rec.x.r,
    pct:Math.round(rec.c.favShare*1000)/10,
    newFav:Math.round(rec.c.favorAdded),
    priceMove:Math.round(rec.c.oddsMove*100)/100,
    favoriteWon:won(rec.x),fixture:autoKey(rec.x)
  }));
  return {pattern,profile,baseline,states,examples,scope,totalHistorical:historical.length,
    sameVenue:peers.filter(rec=>rec.x.f===target.f).length,
    sameVenueStats:svProfile(pattern,peers.filter(rec=>rec.x.f===target.f))};
}
// Factual discovery from past market cases; never a wager recommendation.
function svObservationHistory(x){
 const now=Date.now(),start=kickoffMs(x);
 return matches.filter(z=>{
   if(z.id===x.id||!finished(z))return false;
   const previous=kickoffMs(z);
   if(finished(x))return z.id<x.id&&(start===null||previous===null||previous<start);
   return previous===null?z.id<x.id:previous<now;
 });
}
function svMarketObservation(x,prior){
 const res=svMoneyCases(x,prior);
 if(!res)return null;
 const p=res.pattern,h=res.profile,states=res.states||[];
 const selected=states.find(z=>z.state===p.priceState);
 const total=states.reduce((n,z)=>n+z.n,0),matching=selected?selected.n:0;
 const frequency=total>=12?Math.round(matching/total*100):null;
 const rarity=frequency===null?null:100-frequency;
 const direction=p.priceState==="flat"?"έμεινε σχεδόν σταθερή":p.priceState==="down"?"έπεσε":"ανέβηκε";
 const flow=p.moneyState==="fav"?"Νέα χρήματα κυρίως στο φαβορί":
   p.moneyState==="contra"?"Νέα χρήματα κυρίως στην κόντρα":"Μικτή νέα ροή χρημάτων";
 const title=flow+" · η απόδοση του φαβορί "+direction;
 const details="Νέος τζίρος "+money(p.newTurnover)+" · στο φαβορί ≈"+
   money(p.favorAdded)+" ("+nf(100*p.favShare,1)+"%) · στην κόντρα ≈"+
   money(p.contraAdded)+" · απόδοση φαβορί "+price(x.m)+" → "+price(x.l)+
   " ("+(p.oddsMove>0?"+":"")+nf(p.oddsMove,2)+"%).";
 const historyText=h.n?
   "Σε "+h.n+" ιστορικούς αγώνες του ίδιου συνδυασμού: "+h.wins+
   " νίκες φαβορί και "+(h.n-h.wins)+" αποτελέσματα κόντρα +0,5.":
   "Δεν υπάρχουν ακόμη αρκετές συγκρίσιμες ιστορικές περιπτώσεις.";
 const frequencyText=frequency===null?
   "Μικρό συγκρίσιμο δείγμα για τη συχνότητα της κίνησης.":
   "Η ίδια μεταβολή απόδοσης εμφανίστηκε σε "+matching+"/"+total+
   " περιπτώσεις αντίστοιχης νέας ροής ("+frequency+"%).";
 const magnitude=Math.min(1,Math.abs(p.oddsMove)/4),concentration=2*Math.abs(p.favShare-.5);
 // Sorting measures distinctiveness, not the probability of an outcome.
 const rank=(rarity===null?35:rarity)*.7+magnitude*18+concentration*12;
 return {x,pattern:p,title,details,historyText,frequencyText,
   rank,rarity,compared:total,frequency};
}
// SHARPVISION PREMIUM MARKET FINGERPRINT
// Three observed Excel snapshots only. Smooth connectors are stylistic between
// consecutive known observations. No intermediate datapoints are invented.
// Initial favorite odds and 11:00 turnover may refer to different timestamps.
function svFingerprintStages(x){
 return [
   {title:"Αρχική / 11:00",short:"Αρχή",odds:x.o,turn:x.v0,p:x.p0,contra:x.contra0},
   {title:"90′ πριν",short:"90′ πριν",odds:x.m,turn:x.v90,p:x.p90,contra:x.contra90},
   {title:"Τελευταία",short:"Τώρα",odds:x.l,turn:x.v,p:x.p,contra:x.contra}
 ];
}
const svFingerprintCash=n=>n>=1000000?nf(n/1000000,1)+" εκ.":n>=1000?nf(n/1000,0)+" χιλ.":nf(n,0);
const svCashExact=n=>usable(n)&&n>=0?money(n).replace(/\s€$/,"€"):"—";
const svFingerprintValidOdds=n=>usable(n)&&n>1.01;
const svFingerprintValidCash=n=>usable(n)&&n>=0;
const svFingerprintPct=n=>usable(n)&&n>=0&&n<=100?n:null;
function svFingerprintTurnMax(max){
 if(!Number.isFinite(max)||max<=0)return 1;
 const rough=max/3,base=Math.pow(10,Math.floor(Math.log10(rough)));
 const step=[1,2,2.5,5,10].find(f=>f*base>=rough)||10;
 return 3*step*base;
}
function svFingerprintTag(x,y,label,kind){
 const odd=kind==="odds";
 const w=Math.max(54,Math.min(106,14+String(label).length*(odd?6.0:5.7)));
 const bx=(x-w/2).toFixed(1),by=(y-17).toFixed(1);
 return '<g class="sv-plot-tag sv-plot-'+kind+'">'+
  '<rect x="'+bx+'" y="'+by+'" width="'+w.toFixed(1)+'" height="22" rx="7" '+
    'fill="'+(odd?'#073d73':'#332718')+'" fill-opacity=".98" stroke="'+
    (odd?'#32c5fc':'#ffb653')+'" stroke-width="1.15"/>'+
  '<text x="'+x+'" y="'+(y-2).toFixed(1)+'" fill="'+
    (odd?'#88eaff':'#ffe1a1')+'" font-size="13.5" font-weight="850" text-anchor="middle">'+
    safe(label)+'</text></g>';
}
function svFingerprintSvg(stages,fixture,showTurnover=false){
 const W=360,H=304,top=57,bottom=228,xs=[75,179,283];
 const odds=stages.map(z=>z.odds).filter(svFingerprintValidOdds);
 const turn=showTurnover?stages.map(z=>z.turn).filter(svFingerprintValidCash):[];
 if(!odds.length&&!turn.length)
  return '<div class="sv-fingerprint-no-data">Δεν υπάρχουν ακόμη τιμές για γράφημα. Θα εμφανιστούν μόλις ενημερωθεί το Excel.</div>';
 const rawMin=Math.min(...odds,1e6),rawMax=Math.max(...odds,0);
 const pad=Math.max(.05,(rawMax-rawMin)*.30);
 const minOdds=odds.length?Math.max(1.01,rawMin-pad):1.01;
 const maxOdds=odds.length?rawMax+pad:2.01;
 const topTurn=svFingerprintTurnMax(turn.length?Math.max(...turn):0);
 const yOdds=v=>bottom-(v-minOdds)/(maxOdds-minOdds)*(bottom-top);
 const yTurn=v=>bottom-(v/topTurn)*(bottom-top);
 let svg='<svg viewBox="0 0 '+W+' '+H+'" xmlns="http://www.w3.org/2000/svg" '+
  'role="img" aria-label="'+(showTurnover?"Γράφημα απόδοσης και τζίρου":"Γράφημα απόδοσης φαβορί")+' σε τρία στάδια">'+
  '<title>'+safe("Αποτύπωμα αγοράς: "+name(fixture))+'</title>'+
  '<desc>Η μπλε γραμμή συνδέει μόνο διαδοχικά γνωστά στιγμιότυπα απόδοσης. '+
  (showTurnover?'Οι πορτοκαλί μπάρες δείχνουν πραγματικές καταγραφές τζίρου. ':'')+
  'Δεν συμπληρώνονται κενά ή ενδιάμεσες παρατηρήσεις.</desc>'+
  '<defs>'+
    '<linearGradient id="svBarPremium" x1="0" y1="0" x2="0" y2="1">'+
      '<stop offset="0%" stop-color="#ffbb55" stop-opacity=".88"/>'+
      '<stop offset="100%" stop-color="#ce7520" stop-opacity=".53"/>'+
    '</linearGradient>'+
    '<filter id="svLineGlow" x="-25%" y="-30%" width="150%" height="160%">'+
      '<feGaussianBlur stdDeviation="2.8"/></filter>'+
  '</defs>';
 svg+='<text x="10" y="25" fill="#75d8ff" font-size="15.5" font-weight="820">Απόδοση</text>'+
   (showTurnover?'<text x="351" y="25" fill="#ffca79" font-size="14.5" font-weight="820" text-anchor="end">Τζίρος €</text>':"");
 for(let i=0;i<=3;i++){
   const y=top+(bottom-top)*i/3,amount=(3-i)*topTurn/3,odd=maxOdds-(maxOdds-minOdds)*i/3;
   svg+='<line x1="45" y1="'+y.toFixed(1)+'" x2="314" y2="'+y.toFixed(1)+
     '" stroke="#477090" stroke-opacity=".63" stroke-width=".8" stroke-dasharray="4 5"/>';
   if(odds.length)
     svg+='<text x="40" y="'+(y+4).toFixed(1)+'" font-size="11.7" fill="#a8dafa" text-anchor="end">'+safe(nf(odd,2))+'</text>';
   if(turn.length)
     svg+='<text x="358" y="'+(y+4).toFixed(1)+'" font-size="11.7" fill="#edc78b" text-anchor="end">'+
      safe(svFingerprintCash(amount))+'</text>';
 }
 stages.forEach((z,i)=>{
   if(!showTurnover||!svFingerprintValidCash(z.turn))return;
   const x=xs[i],v=z.turn,y=yTurn(v),height=Math.max(.5,bottom-y);
   svg+='<rect x="'+(x-29)+'" y="'+y.toFixed(1)+'" width="58" height="'+height.toFixed(1)+
     '" rx="6" fill="url(#svBarPremium)" stroke="#ffbe70" stroke-opacity=".6" stroke-width=".8">'+
     '<title>'+safe(z.title+": τζίρος "+money(v))+'</title></rect>';
 });
 // When the 90′ odds are unavailable, a DASHED straight reference joins
 // only the two KNOWN endpoints. It is not a reported intermediate price or curve.
 // The visible note below the SVG spells this out explicitly.
 if(!svFingerprintValidOdds(stages[1].odds)&&
    svFingerprintValidOdds(stages[0].odds)&&svFingerprintValidOdds(stages[2].odds)){
   const x1=xs[0],x2=xs[2],y1=yOdds(stages[0].odds),y2=yOdds(stages[2].odds);
   svg+='<path d="M '+x1+' '+y1.toFixed(1)+' L '+x2+' '+y2.toFixed(1)+
     '" stroke="#52c9f5" stroke-width="3" stroke-linecap="round" stroke-dasharray="6 7" '+
     'opacity=".85" fill="none"/>';
 }
 // Smooth path only between TWO consecutive REAL market snapshots.
 for(let i=1;i<3;i++){
   const a=stages[i-1].odds,b=stages[i].odds;
   if(!svFingerprintValidOdds(a)||!svFingerprintValidOdds(b))continue;
   const x1=xs[i-1],x2=xs[i],y1=yOdds(a),y2=yOdds(b),c=(x2-x1)*.36;
   const d='M '+x1+' '+y1.toFixed(1)+' C '+(x1+c).toFixed(1)+' '+y1.toFixed(1)+
     ' '+(x2-c).toFixed(1)+' '+y2.toFixed(1)+' '+x2+' '+y2.toFixed(1);
   svg+='<path d="'+d+'" fill="none" stroke="#0dbafb" stroke-width="9" opacity=".2" filter="url(#svLineGlow)"/>'+
     '<path d="'+d+'" fill="none" stroke="#35c9fa" stroke-width="3.9" stroke-linecap="round"/>';
 }
 stages.forEach((z,i)=>{
   const x=xs[i],v=z.odds;
   if(svFingerprintValidOdds(v)){
     const y=yOdds(v);
     svg+='<circle cx="'+x+'" cy="'+y.toFixed(1)+'" r="7.5" fill="#061c37" stroke="#7febff" stroke-width="3">'+
       '<title>'+safe(z.title+": απόδοση φαβορί "+price(v))+'</title></circle>';
   }
 });
 stages.forEach((z,i)=>{
   const x=xs[i],v=z.turn;
   if(!showTurnover||!svFingerprintValidCash(v))return;
   const y=yTurn(v);
   const show=svCashExact(v),label=show.length>11?svFingerprintCash(v)+"€":show;
   const place=y<top+34?y+20:Math.max(top+14,y-13);
   svg+=svFingerprintTag(x,place,label,"cash");
 });
 stages.forEach((z,i)=>{
   const x=xs[i],v=z.odds;
   if(!svFingerprintValidOdds(v))return;
   const y=yOdds(v),cashY=svFingerprintValidCash(z.turn)?yTurn(z.turn):null;
   const tagAbove=y>top+35,tagY=tagAbove?y-16:y+37;
   // Avoid overdraw on a nearby bar label: the blue odds chip remains legible.
   svg+=svFingerprintTag(x,tagY,price(v),"odds");
 });
 stages.forEach((z,i)=>{
   const x=xs[i];
   svg+='<text x="'+x+'" y="261" fill="#ecf7ff" font-size="15" font-weight="790" text-anchor="middle">'+
     safe(z.short)+'</text>'+
     '<text x="'+x+'" y="283" fill="#94b8d9" font-size="11.5" text-anchor="middle">'+
     safe(i===0?(showTurnover?"αρχική / 11:00":"αρχική"):i===1?"90′ πριν":"τελευταία")+'</text>';
   if(!svFingerprintValidOdds(z.odds)&&(!showTurnover||!svFingerprintValidCash(z.turn)))
     svg+='<text x="'+x+'" y="'+(top+(bottom-top)*.56).toFixed(1)+
       '" fill="#82a8c8" font-size="10" text-anchor="middle">χωρίς στοιχεία</text>';
 });
 return svg+'</svg>';
}
// Default: only the blue favorite-odds curve. Turnover is strictly opt-in,
// never a second card or repeated numeric table.
let svFingerprintWithTurnover=false;
function setFingerprintMode(showTurnover){
 svFingerprintWithTurnover=!!showTurnover;
 const oddButton=$("fingerprintModeOdds"),bothButton=$("fingerprintModeBoth");
 oddButton.classList.toggle("is-selected",!svFingerprintWithTurnover);
 bothButton.classList.toggle("is-selected",svFingerprintWithTurnover);
 oddButton.setAttribute("aria-pressed",String(!svFingerprintWithTurnover));
 bothButton.setAttribute("aria-pressed",String(svFingerprintWithTurnover));
 if(!$("fingerprintDetails").classList.contains("hide"))renderFingerprint();
}
function renderFingerprint(){
 if(!current)return;
 const stages=svFingerprintStages(current),x=current,expanded=svFingerprintWithTurnover;
 $("fingerprintChart").innerHTML=svFingerprintSvg(stages,x,expanded);
 $("fingerprintTurnoverLegend").classList.toggle("hide",!expanded);
 $("fingerprintScales").textContent=expanded?
   "Μπλε: απόδοση · Πορτοκαλί: τζίρος (€). Η αρχική απόδοση και ο τζίρος 11:00 μπορεί να μην είναι της ίδιας ώρας.":
   "Η μπλε γραμμή δείχνει μόνο την απόδοση του φαβορί.";

 const missing90Odds=!svFingerprintValidOdds(stages[1].odds);
 const missing90Turn=!svFingerprintValidCash(stages[1].turn);
 const hasOdds=stages.some(z=>svFingerprintValidOdds(z.odds));
 const hasTurn=expanded&&stages.some(z=>svFingerprintValidCash(z.turn));
 const missing=[];
 if(hasOdds&&missing90Odds)missing.push("Δεν έχουμε απόδοση στα 90′.");
 if(hasTurn&&missing90Turn)missing.push("Δεν έχουμε τζίρο στα 90′.");
 if(missing90Odds&&svFingerprintValidOdds(stages[0].odds)&&svFingerprintValidOdds(stages[2].odds))
   missing.push("Η διακεκομμένη μπλε σύνδεση δείχνει μόνο δύο γνωστές τιμές, όχι την ενδιάμεση κίνηση.");
 $("fingerprintMissing").textContent=missing.join(" ");
 $("fingerprintMissing").classList.toggle("hide",!missing.length);

 // Only one money split, in the latest source snapshot. Earlier values
 // already belong to the main Excel table; don't draw extra comparisons.
 const fav=svFingerprintPct(stages[2].p),contra=svFingerprintPct(stages[2].contra);
 const both=fav!==null&&contra!==null&&Math.abs(fav+contra-100)<=.5;
 if(fav===null&&contra===null){
   $("fingerprintMoneyRows").innerHTML='<p class="tiny">Δεν υπάρχουν διαθέσιμα ποσοστά χρημάτων.</p>';
 }else{
   const bar=both?
     '<div class="sv-moneybar" aria-hidden="true"><span class="fav" style="width:'+
       fav.toFixed(2)+'%"></span><span class="contra" style="width:'+
       Math.min(contra,100-fav).toFixed(2)+'%"></span></div>':
     '<p class="tiny">Δεν υπάρχουν πλήρη, συγκρίσιμα ποσοστά.</p>';
   $("fingerprintMoneyRows").innerHTML='<div class="sv-fingerprint-moneyrow">'+
     '<div class="sv-moneyrow-heading"><strong>Τώρα</strong><span>Φαβορί '+
       safe(fav===null?"—":per(fav))+' · Κόντρα '+safe(contra===null?"—":per(contra))+
       '</span></div>'+bar+'</div>';
 }

 // A short contextual interpretation: no repeated price, turnover or share
 // numbers and no rule that falling price favors one selection.
 const oldestPrice=svFingerprintValidOdds(x.o)?x.o:svFingerprintValidOdds(x.m)?x.m:null;
 const currentPrice=svFingerprintValidOdds(x.l)?x.l:null;
 let oddsPhrase="";
 if(oldestPrice!==null&&currentPrice!==null){
   const diff=100*(currentPrice/oldestPrice-1);
   oddsPhrase=Math.abs(diff)<.25?"Η απόδοση έμεινε σχεδόν σταθερή":
     diff>0?"Η απόδοση ανέβηκε":"Η απόδοση έπεσε";
 }
 const oldestTurn=svFingerprintValidCash(x.v0)?x.v0:svFingerprintValidCash(x.v90)?x.v90:null;
 const currentTurn=svFingerprintValidCash(x.v)?x.v:null;
 let turnoverPhrase="";
 if(expanded&&oldestTurn!==null&&currentTurn!==null)
   turnoverPhrase=currentTurn>oldestTurn?"ο τζίρος αυξήθηκε":
     currentTurn<oldestTurn?"ο καταγεγραμμένος τζίρος μειώθηκε":"ο τζίρος έμεινε σταθερός";
 const changes=[oddsPhrase,turnoverPhrase].filter(Boolean);
 $("fingerprintInsight").textContent=changes.length?
   changes.join(" · ")+". Οι κινήσεις αυτές από μόνες τους δεν δείχνουν ποιος θα κερδίσει.":
   "Δεν υπάρχουν αρκετά στοιχεία για να περιγράψουμε την αλλαγή της αγοράς.";
}

function renderMarketObservation(){
 if(!current)return;
 const o=svMarketObservation(current,svObservationHistory(current));
 $("marketObservation").classList.toggle("hide",!o);
 const status=$("marketObservationStatus"),body=$("marketObservationBody"),
   history=$("marketObservationHistory");
 if(!o){
   status.textContent="Αναμονή στιγμιοτύπων";
   body.textContent="Χρειάζονται πραγματικά στιγμιότυπα 90′ και τελευταίας ενημέρωσης για αποδόσεις, τζίρο και χρήματα. Δεν συμπληρώνουμε κενά με υποθέσεις.";
   history.textContent="";
   return;
 }
 status.textContent="90′ → τελευταία ενημέρωση";
 body.textContent=o.title; // Numeric market figures already appear above in the chart and main data.
 history.textContent=o.historyText+" "+o.frequencyText;
}
// Empirical anomaly explorer. Unlike the Analyst's named money/odds patterns,
// Hunter ranks the unusual COMBINATION of continuous observed characteristics.
// This score never selects favorite/contra and never interprets bettor motives.
const hunterScales=[
 {key:"share",label:"κατανομή νέων χρημάτων",scale:.20,weight:1.15},
 {key:"lateMove",label:"κίνηση απόδοσης στα 90′",scale:.78,weight:1.18},
 {key:"growth",label:"ρυθμός αύξησης τζίρου",scale:.56,weight:.82},
 {key:"price",label:"επίπεδο απόδοσης",scale:.23,weight:.73},
 {key:"rank",label:"σχετικός τζίρος λίγκας",scale:30,weight:.70},
 {key:"previousMove",label:"κίνηση απόδοσης πριν τα 90′",scale:.85,weight:.66},
 {key:"contraMove",label:"κίνηση απόδοσης κόντρας",scale:.82,weight:.70},
 {key:"prevCash",label:"κατανομή χρημάτων στα 90′",scale:.17,weight:.38}
];
function hunterFeatures(x){
 const c=svCase(x);
 if(!c)return null;
 const features={
   share:c.favShare,
   lateMove:Math.asinh(c.oddsMove/3.5),
   growth:Math.log1p(c.growth),
   price:Math.log(c.price),
   rank:c.rank,
   prevCash:x.p90/100
 };
 if(usable(x.o)&&x.o>1.01)
   features.previousMove=Math.asinh(((x.m/x.o)-1)*100/4);
 if(usable(x.cm)&&x.cm>1.01&&usable(x.cl)&&x.cl>1.01)
   features.contraMove=Math.asinh(((x.cl/x.cm)-1)*100/4);
 return {x,case:c,values:features};
}
function hunterDistance(a,b){
 let sum=0,weight=0,compared=0;
 for(const f of hunterScales){
   const av=a.values[f.key],bv=b.values[f.key];
   if(!Number.isFinite(av)||!Number.isFinite(bv))continue;
   const delta=Math.abs(av-bv)/f.scale;
   sum+=f.weight*Math.min(16,delta*delta);
   weight+=f.weight;compared++;
 }
 if(compared<5||weight<=0)return null;
 return Math.sqrt(sum/weight);
}
function hunterNearest(feature,history,k=5,exclude=null){
 const candidates=[];
 for(const old of history){
   if(exclude!==null&&old.x.id===exclude)continue;
   const dist=hunterDistance(feature,old);
   if(dist===null)continue;
   if(candidates.length<k){candidates.push({old,dist});candidates.sort((a,b)=>a.dist-b.dist);}
   else if(dist<candidates[candidates.length-1].dist){
     candidates.pop();candidates.push({old,dist});candidates.sort((a,b)=>a.dist-b.dist);
   }
 }
 return candidates;
}
function hunterUnusualDetails(feature,history){
 const deviations=[];
 for(const spec of hunterScales){
   const v=feature.values[spec.key];
   if(!Number.isFinite(v))continue;
   const peers=history.map(h=>h.values[spec.key]).filter(Number.isFinite);
   if(peers.length<20)continue;
   const percentile=peers.filter(x=>x<=v).length/peers.length;
   const tail=Math.min(percentile,1-percentile);
   deviations.push({label:spec.label,tail});
 }
 deviations.sort((a,b)=>a.tail-b.tail);
 const notable=deviations.filter(z=>z.tail<=.16).slice(0,3);
 return notable.length
   ?"Ξεχωρίζουν σε σχέση με το ιστορικό: "+notable.map(z=>z.label).join(", ")+"."
   :"Ο συνδυασμός πολλών κινήσεων διαφέρει από παλιότερα παιχνίδια· κανένας μόνος δείκτης δεν αρκεί για εξήγηση.";
}
function buildMarketHunter(upcoming,past){
 const historical=past.map(hunterFeatures).filter(Boolean);
 marketHunterItems=[];
 $("marketHunterCount").textContent="0";
 if(historical.length<15)return;
 // For comparison, establish the historical leave-one-out nearest-neighbor
 // distance. Percentile is unusualness of a profile, NOT a win likelihood.
 const historicalScores=historical.map(h=>{
   const nearest=hunterNearest(h,historical,5,h.x.id);
   return nearest.length>=3?nearest.reduce((a,z)=>a+z.dist,0)/nearest.length:null;
 }).filter(Number.isFinite);
 if(historicalScores.length<15)return;
 marketHunterItems=upcoming.map(x=>{
   const feature=hunterFeatures(x);
   if(!feature)return null;
   const neighbors=hunterNearest(feature,historical,5);
   if(neighbors.length<3)return null;
   const distance=neighbors.reduce((v,z)=>v+z.dist,0)/neighbors.length;
   const percentile=Math.round(100*historicalScores.filter(z=>z<=distance).length/historicalScores.length);
   return {x,distance,percentile,historySize:historical.length,
     explanation:hunterUnusualDetails(feature,historical),
     nearest:neighbors.slice(0,3).map(z=>({
       match:name(z.old.x),score:z.old.x.r,matchDistance:z.dist
     })),
     feature
   };
 }).filter(Boolean).sort((a,b)=>b.percentile-a.percentile||b.distance-a.distance||
   kickoffMs(a.x)-kickoffMs(b.x));
 $("marketHunterCount").textContent=String(marketHunterItems.length);
}
function renderMarketHunter(){
 const count=marketHunterItems.length;
 const kept=svSavedExtras("hunter",marketHunterItems.map(o=>o.x));
 $("marketHunterSummary").textContent=count
  ?"Ο Κυνηγός συνέκρινε "+count+" προσεχείς αγώνες με τα ιστορικά προφίλ χρημάτων, "+
   "μεταβολής αποδόσεων, τζίρου και αρχικής συμπεριφοράς. Η σειρά προκύπτει από "+
   "τη συνολική απόσταση από προηγούμενες καταστάσεις, όχι από την έκβαση τους."
   :kept?"Αποθηκευμένοι αγώνες που περιμένουν τελικό αποτέλεσμα. "+svCoverage():
     "Δεν υπάρχουν ακόμη αρκετά δεδομένα για τον Κυνηγό. "+svCoverage();
 $("marketHunterRows").innerHTML=count?marketHunterItems.slice(0,30).map(o=>{
   const examples=o.nearest.map(z=>z.match+" ("+z.score+")").join(" · ");
   const rare="Η συμπεριφορά διαφέρει περισσότερο από του "+o.percentile+
       "% των ιστορικών παιχνιδιών ως προς τον συνδυασμό μετρήσεων. "+
       "Δεν είναι πιθανότητα νίκης.";
   return '<button type="button" class="market-watch-item" data-hunter-id="'+o.x.id+'">'+
     '<b>'+safe(name(o.x))+'</b><small>'+safe(o.x.lg)+" · "+safe(kickoffLabel(o.x))+'</small>'+
     '<span class="watch-pattern">Ιστορική διαφοροποίηση: '+safe(o.percentile)+
       '/100 (όχι πιθανότητα αποτελέσματος)</span>'+
     '<span class="market-hunter-reason">'+safe(o.explanation)+'</span>'+
     '<small>'+safe(rare)+'</small>'+
     '<span class="market-hunter-observed">Πιο κοντινές παλιές περιπτώσεις: '+safe(examples)+'</span>'+
     '<small>Άνοιγμα ανάλυσης αγώνα ↗</small></button>';
 }).join("")+
 (count>30?'<p class="market-watch-foot">Οι 30 πρώτες από '+count+' παρατηρήσεις.</p>':""):
 (kept?'':'<p class="market-watch-intro">Αναμονή επαρκών μετρήσεων.</p>');
 $("marketHunterRows").insertAdjacentHTML("beforeend",kept);
 $("marketHunterRows").querySelectorAll("[data-hunter-id]").forEach(b=>b.addEventListener("click",()=>{
   const id=Number(b.dataset.hunterId);
   if(!matches.some(z=>z.id===id))return;
   closeMarketWatch();select(id);
   const title=$("matchTitle");
   if(title&&typeof title.scrollIntoView==="function")
     title.scrollIntoView({behavior:"smooth",block:"start"});
 }));
 svWireSaved("marketHunterRows");
}
function renderMarketTools(){
 const selected=marketToolTab;
 for(const [tab,panel,button] of [
   ["analyst","marketAnalystView","marketToolAnalyst"],
   ["hunter","marketHunterView","marketToolHunter"],
   ["psych","marketPsychView","marketToolPsych"]
 ]){
   $(panel).classList.toggle("hide",tab!==selected);
   $(button).classList.toggle("active",tab===selected);
   $(button).setAttribute("aria-pressed",String(tab===selected));
 }
 if(selected==="analyst")renderMarketWatch();
 else if(selected==="hunter")renderMarketHunter();
 else renderMarketPsych();
 renderMarketToolHistory();
}
function selectMarketTool(value){
 marketToolTab=["analyst","hunter","psych"].includes(value)?value:"analyst";
 renderMarketTools();
}

/* Browser-only records of what was actually seen BEFORE each kickoff.
   Never reconstruct a pregame signal retrospectively from a final score. */
function svCoverage(){
 const open=matches.filter(x=>!finished(x));
 const future=open.filter(x=>kickoffMs(x)!==null&&kickoffMs(x)>Date.now());
 const ready=future.filter(x=>svCase(x)!==null);
 return "Χωρίς τελικό: "+open.length+" · Μελλοντικοί με ώρα: "+future.length+
   " · Πλήρη στιγμιότυπα: "+ready.length+".";
}
function svRememberTool(tool,x,label,pick=null,level=0){
 const now=Date.now(),start=kickoffMs(x);
 if(start===null||start<=now||finished(x))return false;
 const fixture=autoKey(x),id=tool+"|"+fixture;
 const existing=marketToolLog.find(e=>e&&e.id===id);
 if(existing){
   if(tool==="psych"&&(existing.lastPick!==pick||existing.lastLevel!==level)){
     existing.lastPick=pick;existing.lastLevel=level;return true;
   }
   return false;
 }
 marketToolLog.unshift({id,tool,fixture,match:name(x),league:x.lg,kickoff:x.kickoff,
   recordedAt:new Date().toISOString(),label,firstPick:pick,lastPick:pick,firstLevel:level,lastLevel:level});
 return true;
}
function svToolMatch(e){return matches.find(x=>autoKey(x)===e.fixture)||null}
function svActiveLog(tool){
 return marketToolLog.filter(e=>{
   if(!e||e.tool!==tool)return false;
   const x=svToolMatch(e);
   return !x||!finished(x);
 });
}
function svSavedLabel(e){
 if(e.tool!=="psych")return e.label;
 const locked=autoLedger[e.fixture];
 if(locked){
   return locked.pick==="abstain"?e.label+" · τώρα Αποχή":
     (locked.pick==="fav"?"Φαβορί":"Κόντρα +0,5")+" "+locked.level+"/3 · κλειδωμένο";
 }
 return e.lastPick==="abstain"?e.label+" · τώρα Αποχή":e.label+" · προσωρινό";
}
function svSavedCard(e){
 const x=svToolMatch(e);
 const past=Date.parse(e.kickoff)<=Date.now();
 const status=past?"Έχει ξεκινήσει · αναμονή τελικού αποτελέσματος":"Πριν από τη σέντρα";
 const label=svSavedLabel(e);
 const inner='<b>'+safe(e.match)+'</b><small>'+safe(e.league)+' · '+safe(kickoffLabel({kickoff:e.kickoff}))+
   '</small><span class="watch-pattern">'+safe(label)+'</span>'+
   '<span class="market-saved-status">'+safe(status)+'</span>';
 return x?'<button type="button" class="market-watch-item" data-saved-fixture="'+safe(e.fixture)+'">'+inner+'</button>':
   '<div class="market-watch-item">'+inner+'</div>';
}
function svSavedExtras(tool,live){
 const keys=new Set(live.map(x=>autoKey(x)));
 return svActiveLog(tool).filter(e=>!keys.has(e.fixture))
   .sort((a,b)=>Date.parse(a.kickoff)-Date.parse(b.kickoff))
   .slice(0,30).map(svSavedCard).join("");
}
function svWireSaved(root){
 $(root).querySelectorAll("[data-saved-fixture]").forEach(b=>b.addEventListener("click",()=>{
   const x=matches.find(z=>autoKey(z)===b.dataset.savedFixture);
   if(!x)return;
   closeMarketWatch();select(x.id);
   const el=$("matchTitle");
   if(el&&typeof el.scrollIntoView==="function")el.scrollIntoView({behavior:"smooth",block:"start"});
 }));
}
function renderMarketPsych(){
 const entries=svActiveLog("psych").sort((a,b)=>Date.parse(a.kickoff)-Date.parse(b.kickoff));
 $("marketPsychSummary").textContent=entries.length?
   "Αγώνες που πέρασαν τα όρια Φαβορί ή Κόντρα πριν από τη σέντρα. Παραμένουν μέχρι το τελικό σκορ. Η προσωρινή ένδειξη μπορεί να αλλάξει.":
   "Δεν έχει καταγραφεί ακόμη επιλογή Φαβορί ή Κόντρα. "+svCoverage();
 $("marketPsychRows").innerHTML=entries.length?entries.slice(0,30).map(svSavedCard).join("")+
   (entries.length>30?'<p class="market-watch-foot">Εμφανίζονται οι πρώτοι 30 αγώνες.</p>':""):
   '<p class="market-watch-intro">Οι απλές Αποχές δεν προστίθενται.</p>';
 svWireSaved("marketPsychRows");
}
function renderMarketToolHistory(){
 const done=marketToolLog.filter(e=>{
   if(!e||!["analyst","hunter","psych"].includes(e.tool))return false;
   const x=svToolMatch(e);
   if(!x||!finished(x))return false;
   if(e.tool!=="psych")return true;
   const locked=autoLedger[e.fixture];
   return locked?locked.pick==="fav"||locked.pick==="contra":
     e.lastPick==="fav"||e.lastPick==="contra";
 }).sort((a,b)=>String(b.recordedAt).localeCompare(String(a.recordedAt)));
 $("marketHistoryCount").textContent=String(done.length);
 const names={analyst:"Αναλυτής",hunter:"Κυνηγός",psych:"Ψυχολόγος"};
 $("marketHistoryRows").innerHTML=done.length?done.slice(0,10).map(e=>{
   const x=svToolMatch(e),locked=e.tool==="psych"?autoLedger[e.fixture]:null;
   return '<div class="market-watch-item"><b>'+safe(e.match)+'</b>'+
     '<small>'+safe(names[e.tool])+' · '+safe(new Date(e.recordedAt).toLocaleDateString("el-GR"))+'</small>'+
     '<span class="watch-pattern">'+safe(e.tool==="psych"&&locked?
       (locked.pick==="fav"?"Φαβορί":"Κόντρα +0,5")+" "+locked.level+"/3 · κλειδωμένο":
       svSavedLabel(e))+'</span>'+
     '<span class="market-saved-score">Τελικό '+safe(x.r)+'</span></div>';
 }).join(""):'<p class="market-watch-intro">Δεν υπάρχουν ακόμη καταγραφές με τελικό σκορ. Οι Αποχές δεν εμφανίζονται.</p>';
}

function buildMarketWatch(){
 const now=Date.now();
 const past=matches.filter(z=>finished(z)&&(kickoffMs(z)===null||kickoffMs(z)<now));
 const upcoming=matches.filter(x=>!finished(x)&&kickoffMs(x)!==null&&kickoffMs(x)>now&&svCase(x)!==null);
 marketWatchItems=upcoming.map(x=>svMarketObservation(x,past.filter(z=>z.id!==x.id&&(kickoffMs(z)!==null||z.id<x.id))))
   .filter(Boolean)
   .sort((a,b)=>b.rank-a.rank||kickoffMs(a.x)-kickoffMs(b.x));
 $("marketWatchCount").textContent=String(marketWatchItems.length);
 buildMarketHunter(upcoming,past);
 let changed=false;
 for(const o of marketWatchItems)
   changed=svRememberTool("analyst",o.x,o.title)||changed;
 for(const o of marketHunterItems)
   changed=svRememberTool("hunter",o.x,"Ασυνήθιστο προφίλ "+o.percentile+"/100")||changed;
 for(const x of upcoming){
   const decision=autoLedger[autoKey(x)]||automaticOpinion(x,past.filter(z=>autoKey(z)!==autoKey(x)));
   const previous=marketToolLog.find(e=>e.id==="psych|"+autoKey(x));
   if(decision.pick==="abstain"&&!previous)continue;
   const label=previous?previous.label:
     (decision.pick==="fav"?"Φαβορί":"Κόντρα +0,5")+" "+decision.level+"/3";
   changed=svRememberTool("psych",x,label,decision.pick,decision.level)||changed;
 }
 if(changed){
   marketToolLog=marketToolLog.filter(e=>e&&e.id&&e.fixture&&e.recordedAt)
     .sort((a,b)=>String(b.recordedAt).localeCompare(String(a.recordedAt))).slice(0,1000);
   store("sv_market_tools_v1",marketToolLog);
 }
 $("marketWatchCount").textContent=String(svActiveLog("analyst").length);
 $("marketHunterCount").textContent=String(svActiveLog("hunter").length);
 $("marketPsychCount").textContent=String(svActiveLog("psych").length);
 if(!$("marketWatchPanel").classList.contains("hide"))renderMarketTools();
}
function renderMarketWatch(){
 const n=marketWatchItems.length;
 const kept=svSavedExtras("analyst",marketWatchItems.map(o=>o.x));
 $("marketWatchSummary").textContent=n
   ?"Βρέθηκαν "+n+" προσεχείς αγώνες με πλήρη στιγμιότυπα. Πρώτες εμφανίζονται οι λιγότερο συνηθισμένες κινήσεις χρημάτων/αποδόσεων, όχι προβλέψεις νίκης."
   :kept?"Αποθηκευμένοι αγώνες που περιμένουν τελικό αποτέλεσμα. "+svCoverage():
     "Δεν υπάρχουν ακόμη προσεχείς αγώνες με πλήρη στιγμιότυπα. "+svCoverage();
 $("marketWatchRows").innerHTML=n?marketWatchItems.slice(0,30).map(o=>{
   const x=o.x;
   return '<button type="button" class="market-watch-item" data-observation-id="'+x.id+'">'+
     '<b>'+safe(name(x))+'</b><small>'+safe(x.lg)+" · "+safe(kickoffLabel(x))+'</small>'+
     '<span class="watch-pattern">'+safe(o.title)+'</span>'+
     '<span class="watch-facts">'+safe(o.details)+'</span>'+
     '<small>'+safe(o.historyText+" "+o.frequencyText)+'</small>'+
     '<small>Άνοιγμα ανάλυσης αγώνα ↗</small></button>';
 }).join("")+
   (n>30?'<p class="market-watch-foot">Οι 30 πρώτες από '+n+' παρατηρήσεις.</p>':""):
   (kept?'':'<p class="market-watch-intro">Δεν υπάρχουν ακόμη παρατηρήσεις με πλήρη πραγματικά δεδομένα.</p>');
 $("marketWatchRows").insertAdjacentHTML("beforeend",kept);
 $("marketWatchRows").querySelectorAll("[data-observation-id]").forEach(b=>b.addEventListener("click",()=>{
   const id=Number(b.dataset.observationId);
   if(!matches.some(z=>z.id===id))return;
   closeMarketWatch();
   select(id);
   const title=$("matchTitle");
   if(title&&typeof title.scrollIntoView==="function")
     title.scrollIntoView({behavior:"smooth",block:"start"});
 }));
 svWireSaved("marketWatchRows");
}
function closeMarketWatch(){
 $("marketWatchPanel").classList.add("hide");
 $("marketWatchToggle").setAttribute("aria-expanded","false");
}
function toggleMarketWatch(){
 const panel=$("marketWatchPanel");
 if(!panel.classList.contains("hide")){closeMarketWatch();return}
 panel.classList.remove("hide");
 $("marketWatchToggle").setAttribute("aria-expanded","true");
 renderMarketTools();
 if(typeof panel.scrollIntoView==="function")
   panel.scrollIntoView({behavior:"smooth",block:"start"});
}

function automaticOpinion(x,prior){
  const result=svMoneyCases(x,prior);
  if(!result){
    return {pick:"abstain",level:0,source:"sharpvision_cases",version:"v4",
      reason:"Δεν υπάρχουν αξιόπιστα στιγμιότυπα 90′ τζίρου, ποσοστών και αποδόσεων. Δεν κατασκευάζω ιστορικό μοτίβο.",
      casebook:null};
  }
  const {pattern:p,profile:h,baseline:b,states,examples,sameVenue,sameVenueStats}=result;
  const moneyLabel=svCashLabels[p.moneyState],priceLabel=svPriceLabels[p.priceState];
  const newFavEur=Math.round(p.favorAdded);
  const pct=nf(p.favShare*100,1)+"%";
  const sign=p.oddsMove>0?"+":"";
  const description=moneyLabel+": "+pct+" από τα "+money(p.newTurnover)+
    " νέου τζίρου πήγε στο φαβορί (≈"+money(newFavEur)+"). "+
    priceLabel+" από το 90′ στο τελευταίο στιγμιότυπο ("+sign+nf(p.oddsMove,2)+"%).";
  const sameCases=h.n+" παλιές περιπτώσεις αυτού του συνδυασμού με "+result.scope+
    ": φαβορί νίκησε "+h.wins+"/"+h.n+
    (h.n?" ("+nf(h.winPct,0)+"%).":".");
  const counterpart=h.priceN>=6?
    "Στις "+h.priceN+" με πλήρεις τιμές φαβορί/κόντρας, η αγορά αντιστοιχούσε σε "+
      nf(h.expectedPct,0)+"% νίκες φαβορί και έγιναν "+h.priceWins+"/"+h.priceN+"."
      :"Δεν υπάρχουν αρκετές ιστορικές τιμές και των δύο πλευρών για σύγκριση με την αγορά.";
  const baselineText=b.n>=10?
    "Βασική εικόνα στην ίδια περιοχή αποδόσεων/τζίρου: "+b.wins+"/"+b.n+
    " νίκες φαβορί ("+nf(b.winPct,0)+"%).":
    "Πολύ μικρό γενικό δείγμα στην ίδια περιοχή αποδόσεων/τζίρου.";
  let pick="abstain",level=0;
  const n=h.priceN,delta=h.advantage,z=h.z;
  const enoughBase=b.priceN>=15;
  const contextContrast=enoughBase&&h.priceN?((h.priceWins/h.priceN)-(b.priceWins/b.priceN)):null;
  const advantageOk=delta!==null&&Math.abs(delta)>=.10;
  const baselineOk=contextContrast!==null&&Math.abs(contextContrast)>=.065&&
    Math.sign(contextContrast)===Math.sign(delta);
  // Count alone NEVER triggers a pick. Require a residual versus quoted
  // odds and versus unconditional peers of comparable price and liquidity.
  if(n>=12&&h.n>=12&&advantageOk&&Math.abs(z)>=1.45&&baselineOk){
    const proposed=delta>0?"fav":"contra";
    const venue=h.n>=6&&sameVenue>=5&&sameVenueStats.n>=5
      ?(sameVenueStats.winPct-h.expectedPct)/100:null;
    // With contradictory same-venue evidence, stay out.
    if(venue===null||Math.sign(venue)===Math.sign(delta)||Math.abs(venue)<.055){
      pick=proposed;level=1;
      if(n>=23&&sameVenue>=6&&Math.abs(z)>=1.9&&Math.abs(delta)>=.13&&
         Math.abs(contextContrast)>=.095)level=2;
      if(n>=38&&sameVenue>=9&&Math.abs(z)>=2.65&&Math.abs(delta)>=.17&&
         Math.abs(contextContrast)>=.13)level=3;
    }
  }
  const why=pick==="abstain"?
    "Αποχή: δεν υπάρχει αρκετή ανεξάρτητη ένδειξη ότι ο συνδυασμός αποδίδει διαφορετικά από τις αποδόσεις της αγοράς και τα συγκρίσιμα παιχνίδια.":
    "Επιλογή "+(pick==="fav"?"φαβορί":"κόντρα +0,5")+
    ": οι ιστορικές περιπτώσεις του ίδιου συνδυασμού είχαν ουσιαστική απόκλιση από "+
    "την προσδοκία των αποδόσεων ΚΑΙ από τον βασικό ιστορικό μέσο όρο. "+
    "Βαθμίδα "+level+"/3, βάσει μεγέθους και συνέπειας δείγματος.";
  const label=moneyLabel+" × "+priceLabel;
  const reason=["ΙΣΤΟΡΙΚΗ ΚΑΤΑΣΤΑΣΗ: "+label,description,sameCases,counterpart,baselineText,why,
    "Δεν συμπεραίνουμε προθέσεις στοιχηματικών ή παικτών. Η ιστορική διαφορά δεν αποτελεί βέβαιη πρόβλεψη."].join("\n");
  return {pick,level,source:"sharpvision_cases",version:"v4",
    reason,sample:h.n,sameVenue,nFav:0,nContra:0,
    casebook:{label,description,scope:result.scope,
      profile:h,baseline:b,states,examples,sameVenue,
      historical:result.totalHistorical,measuredAt:new Date().toISOString()},
    evidenceDelta:delta,relativeToBaseline:contextContrast
  };
}
function captureAutoPredictions(){
 const now=Date.now();
 const due=matches.filter(x=>kickoffMs(x)!==null&&kickoffMs(x)>now+120000&&kickoffMs(x)<=now+22*60000&&!finished(x)&&
   svCase(x)!==null&&!autoLedger[autoKey(x)]);
 if(!due.length)return;
 // Only outcomes already recorded as final on the pre-kickoff snapshot may
 // supply evidence. Finished matches with known later kickoffs are excluded.
 const earlier=matches.filter(z=>finished(z)&&(kickoffMs(z)===null||kickoffMs(z)<now));
 let changed=false;
 for(const x of due)try{
   if(Date.now()>=kickoffMs(x)-120000||autoLedger[autoKey(x)])continue;
   const historical=earlier.filter(z=>autoKey(z)!==autoKey(x));
   const decision=automaticOpinion(x,historical);
   const entry={fixture:autoKey(x),match:name(x),league:x.lg,kickoff:x.kickoff,
     recordedAt:new Date().toISOString(),favorite:fave(x),favoriteVenue:x.f,
     oddsFav:x.l,oddsContra:x.cl,...decision};
   if(Date.parse(entry.recordedAt)>=kickoffMs(x))continue;
   autoLedger[entry.fixture]=entry;changed=true;
 }catch(e){/* One bad row must not interrupt the Excel view. */}
 if(changed){
   const entries=Object.values(autoLedger).filter(z=>z&&z.recordedAt)
     .sort((a,b)=>String(b.recordedAt).localeCompare(String(a.recordedAt))).slice(0,1200);
   autoLedger=Object.fromEntries(entries.map(z=>[z.fixture,z]));
   store("sv_prelock_v4",autoLedger);
 }
}
function autoOutcome(entry){
 const x=matches.find(z=>autoKey(z)===entry.fixture);
 if(!x||!finished(x))return "pending";
 if(entry.pick==="abstain")return "abstain";
 const winner=won(x);
 return entry.pick==="fav"?(winner?"win":"lose"):(winner?"lose":"win");
}
function renderCasebook(book,retrospective=false){
 const panel=$("casebookPanel"),teaser=$("casebookTeaser"),
   table=$("casebookStates"),examples=$("casebookExamples");
 if(!book){panel.classList.add("hide");teaser.textContent="";table.innerHTML="";examples.innerHTML="";return}
 const a=book.profile||{},base=book.baseline||{},n=a.n||0;
 const f=(x)=>x===null||x===undefined?"—":nf(x,0)+"%";
 teaser.textContent=
   (retrospective?"Αναδρομική σύγκριση, ΟΧΙ καταγεγραμμένη πρόβλεψη πριν τη σέντρα.\n":"")+
   "Παρόμοιες περιπτώσεις: "+(n?a.wins+"/"+n+" νίκες φαβορί ("+f(a.winPct)+")":"Καμία")+
   "\nΑπό αυτές, "+(a.priceN||0)+" είχαν και τις δύο τιμές για έλεγχο με τις τότε αποδόσεις."+
   (a.priceN>=6?" Η αγορά αντιστοιχούσε σε "+f(a.expectedPct)+
      " και έγιναν "+a.priceWins+"/"+a.priceN+" νίκες φαβορί.":"")+
   (base.priceN>=10?"\nΣε παρόμοια επίπεδα αποδόσεων και τζίρου γενικά: "+
      base.priceWins+"/"+base.priceN+" ("+f(100*base.priceWins/base.priceN)+")":"")+
   "\nΣύγκριση: "+book.scope+". Σύνολο παλιών αγώνων με έγκυρα στιγμιότυπα: "+
   (book.historical||0)+".";
 const titles={down:"Έπεσε",flat:"Έμεινε σταθερή",up:"Ανέβηκε"};
 const lines=(book.states||[]).map(z=>{
   const pct=z.n?f(z.winPct):"—";
   const cls=book.label&&
       ((book.label.includes("Πτώση")&&z.state==="down")||
       (book.label.includes("Σταθερή")&&z.state==="flat")||
       (book.label.includes("Άνοδος")&&z.state==="up"))?" class=\"case-current\"":"";
   return '<tr'+cls+'><td>'+safe(titles[z.state]||z.state)+'</td><td>'+
     safe((z.n||0)?z.wins+"/"+z.n:"0")+'</td><td>'+safe(pct)+'</td></tr>';
 }).join("");
 table.innerHTML='<table class="casebook-table"><thead><tr><th>Απόδοση φαβορί</th>'+
   '<th>Νίκες/αγώνες</th><th>Ποσοστό</th></tr></thead><tbody>'+lines+'</tbody></table>';
 examples.innerHTML=(book.examples||[]).length?(book.examples||[]).map(e=>
   '<div class="casebook-example"><strong>'+safe(e.match)+'</strong> '+
   '<span class="'+(e.favoriteWon?"good":"bad")+'">'+safe(e.score)+'</span>'+
   '<small>'+safe(e.league)+' · '+safe(e.favoriteWon?"Νίκη φαβορί":"Επιτυχία κόντρας +0,5")+
   ' · Νέος τζίρος προς φαβορί ≈'+safe(money(e.newFav))+
   ' · Μερίδιο '+safe(nf(e.pct,1))+'% · Μεταβολή απόδοσης '+
   safe((e.priceMove>0?"+":"")+nf(e.priceMove,2))+'%</small></div>').join(""):
   '<div class="casebook-note">Δεν υπάρχουν αρκετά πλήρη παραδείγματα.</div>';
 panel.classList.remove("hide");
}

// Presentation only. Decisions and historical calculations are unchanged.
function svBriefPsychologistReason(full,book,side){
 const profile=book&&book.profile;
 const n=Number(profile&&profile.n),wins=Number(profile&&profile.wins);
 if(profile&&Number.isInteger(n)&&n>0&&Number.isInteger(wins)&&wins>=0&&wins<=n){
   const contra=side==="contra",successes=contra?n-wins:wins;
   const first=contra?
     "Σε "+n+" παρόμοιους αγώνες, η κόντρα +0,5 επαληθεύτηκε "+successes+
       " φορές ("+nf(100*successes/n,0)+"%).":
     "Σε "+n+" παρόμοιους αγώνες, το φαβορί κέρδισε "+wins+
       " φορές ("+nf(100*wins/n,0)+"%).";
   const conclusion=side==="fav"?
     "Η ιστορική σύγκριση με τις αποδόσεις και παρόμοια παιχνίδια στηρίζει το φαβορί.":
     side==="contra"?
     "Η ιστορική σύγκριση με τις αποδόσεις και παρόμοια παιχνίδια στηρίζει την κόντρα.":
     "Τα στοιχεία δεν είναι αρκετά ισχυρά για επιλογή.";
   return first+" "+conclusion;
 }
 const first=String(full||"").split("\n").map(z=>z.trim()).find(Boolean);
 return !first?"Δεν υπάρχουν ακόμη διαθέσιμα στοιχεία.":
   first.startsWith("ΙΣΤΟΡΙΚΗ ΚΑΤΑΣΤΑΣΗ:")?
     "Δεν υπάρχουν αρκετές συγκρίσιμες περιπτώσεις για τεκμηριωμένη επιλογή.":first;
}

function renderAutoCard(){
 if(!current)return;
 renderCasebook(null);
 const x=current,t=kickoffMs(x),saved=autoLedger[autoKey(x)];
 const card=$("autoDecisionCard");
 const detail=$("autoDetails");
 if(card.dataset.fixtureKey!==autoKey(x)){
   detail.open=false;
   card.dataset.fixtureKey=autoKey(x);
 }
 const badge=$("autoGrade"),pick=$("autoPick"),reason=$("autoReason"),lock=$("autoLock");
 // Only an actual favorite/contra decision gets color. Abstention,
 // unrecorded fixtures and missing data stay visually neutral.
 const set=(lv,grade,title,why,when,side="none",casebook=null,briefWhen=null)=>{
   const marketSide=["fav","contra"].includes(side)?side:"none";
   const step=Math.max(1,Math.min(3,Number(lv)||1));
   const tone="outlook-"+marketSide+(marketSide==="none"?"":" level-"+step);
   card.className="panel pad prematch-card "+tone;
   badge.className="prematch-tag "+tone;badge.textContent=grade;
   pick.textContent=title;
   reason.textContent=svBriefPsychologistReason(why,casebook,side);
   $("autoReasonFull").textContent=why;
   lock.textContent=briefWhen||when;
   $("autoLockFull").textContent=when;
 };
 if(saved){
   const titles={fav:"Νίκη φαβορί · "+saved.favorite,contra:"Κόντρα +0,5",abstain:"Αποχή"};
   const result=autoOutcome(saved);
   set(saved.level,saved.pick==="abstain"?"Αποχή · Χωρίς βαθμίδα":saved.level+"/3 · "+levelNames[saved.level],titles[saved.pick]||"Αποχή",saved.reason,
     "Κλειδώθηκε "+new Date(saved.recordedAt).toLocaleString("el-GR")+" · Πριν από "+kickoffLabel(x)+
     (result==="win"?" · Επαληθεύτηκε":result==="lose"?" · Δεν επαληθεύτηκε":" · Αναμονή αποτελέσματος"),saved.pick,saved.casebook,
     "🔒 Κλειδώθηκε "+new Date(saved.recordedAt).toLocaleTimeString("el-GR",{hour:"2-digit",minute:"2-digit"})+
     (result==="win"?" · Επαληθεύτηκε":result==="lose"?" · Δεν επαληθεύτηκε":" · Αναμονή αποτελέσματος"));
   renderCasebook(saved.casebook);
 }else if(t===null){
   set(1,"1/3 · Χωρίς ώρα","Δεν υπάρχει προ-αγωνιστική καταγραφή",
     "Λείπει έγκυρη ώρα έναρξης στην BY του Excel. Δεν μπορούμε να επιβεβαιώσουμε ότι δεν ξεκίνησε.",
     "Δεν επινοούμε ώρα έναρξης.");
 }else if(Date.now()>=t-60000||finished(x)){
   set(1,"1/3 · Χωρίς εγγραφή","Δεν καταγράφηκε πριν τη σέντρα",
     "Αυτός ο αγώνας δεν είχε προ-αγωνιστική καταγραφή σε αυτή τη συσκευή. Δεν συμπληρώνουμε εκτιμήσεις μετά τη σέντρα.",
     "Έναρξη: "+kickoffLabel(x));
   // Show observed historical cases for past fixtures WITHOUT manufacturing
   // a pre-match prediction or counting this fixture's final score as evidence.
   const past=matches.filter(z=>z.id<x.id&&finished(z)&&
     (kickoffMs(z)===null||t===null||kickoffMs(z)<t));
   const view=svMoneyCases(x,past);
   if(view){
     const cases={
       label:svCashLabels[view.pattern.moneyState]+" × "+svPriceLabels[view.pattern.priceState],
       profile:view.profile,baseline:view.baseline,states:view.states,
       examples:view.examples,scope:view.scope,historical:view.totalHistorical
     };
     renderCasebook(cases,true);
   }
 }else{
   // A changing interpretation is displayed at any pregame time; only the
   // first eligible reading in the T-75..T-2 minute window is saved immutably.
   const hasBasic=["o","l","p","rank"].every(k=>usable(x[k]));
   if(!hasBasic){
     set(1,"Αναμονή στοιχείων","Δεν υπάρχουν αρκετά δεδομένα",
       "Χρειάζονται αρχικές/τελευταίες αποδόσεις, ποσοστό χρημάτων και σχετικός τζίρος για τεκμηριωμένη γνώμη.",
       "Έναρξη: "+kickoffLabel(x));
   }else{
     const historyNow=matches.filter(z=>finished(z)&&z.id!==x.id&&
       (kickoffMs(z)===null||kickoffMs(z)<Date.now()));
     const preview=automaticOpinion(x,historyNow);
     const choice=preview.pick==="fav"?"Νίκη φαβορί · "+fave(x):
       preview.pick==="contra"?"Κόντρα +0,5":"Αποχή";
     const grade=preview.pick==="abstain"?"Προσωρινή · Αποχή":
       "Προσωρινή · "+preview.level+"/3 · "+levelNames[preview.level];
     set(preview.pick==="abstain"?1:preview.level,grade,choice,preview.reason,
       "Ζωντανή μη αποθηκευμένη εκτίμηση · Κλειδώνει περίπου 22–2 λεπτά πριν την έναρξη, αν η εφαρμογή είναι ανοιχτή · Έναρξη "+kickoffLabel(x),preview.pick,preview.casebook,"Προσωρινή ένδειξη · Δεν έχει κλειδώσει");
     renderCasebook(preview.casebook);
   }
 }
}

function marketWon(x) {
  const w=won(x);
  return w===null?null:histMarket==="contra"?!w:w;
}
function selectedMarketLabel(){return histMarket==="contra"?"Κόντρα +0,5":"Νίκη φαβορί"}
function clearOpinion(){lastOpinion=null;$("opinionText").classList.add("hide");}
function paintMarketSwitch(){
  document.querySelectorAll("[data-market]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.market===histMarket)));
}
function similarity(t,h,side=histMarket,searchMode=mode){
  const forContra=side==="contra";
  const hasContraMoney=usable(t.contra)||usable(t.p);
  if(forContra){
    if(!usable(t.rank)||!hasContraMoney||!usable(h.rank)||!(usable(h.contra)||usable(h.p)))return null;
  }else if(!["o","l","p","rank"].every(k=>usable(t[k])&&usable(h[k])))return null;
  const multiplier={strict:1,medium:1.7,wide:2.8}[searchMode]||1;
  let weighted=0,totalWeight=0,features=0;
  for(const spec of signalSpecs){
    const weight=forContra?spec.cWeight:spec.weight;
    if(weight<=0)continue;
    const a=spec.fn(t);if(!usable(a))continue;
    const b=spec.fn(h);if(!usable(b))return null;
    const tol=forContra?spec.cTol:spec.tol;
    const diff=Math.abs(a-b);
    if(diff>tol*multiplier)return null;
    weighted+=(diff/tol)*weight;
    totalWeight+=weight;
    features++;
  }
  if(features<4||!totalWeight)return null;
  const distance=weighted/totalWeight;
  return {distance,similarity:Math.round(100*Math.exp(-.24*distance)),features};
}

function rate(list){
  const n=list.length;
  if(!n)return {text:"—",sub:"Κανένα κοντινό ματς"};
  const wins=list.filter(x=>marketWon(x)===true).length;
  return {
    text:wins+"/"+n,
    sub:(histMarket==="contra"?"Επιτυχίες κόντρας ":"Νίκες φαβορί ")+
      nf(wins/n*100,0)+"% · "+(histMarket==="contra"?"Φαβορί ":"Κόντρα ")+(n-wins)+"/"+n
  };
}
function renderHistory(){
  if(!current)return;
  paintMarketSwitch();
  const forContra=histMarket==="contra";
  let hasEssential=forContra
    ? usable(current.rank)&&(usable(current.contra)||usable(current.p))
    : ["o","l","p","rank"].every(k=>usable(current[k]));
  let found=[];
  if(hasEssential){
    found=matches.filter(x=>x.id!==current.id&&finished(x)&&leaguesSelected.includes(x.lg))
      .map(x=>{const s=similarity(current,x);return s?{...x,...s}:null})
      .filter(Boolean).sort((a,b)=>a.distance-b.distance);
  }
  // Favorite on the same home/away side implies the opposite side (contra)
  // is also at the same venue as in the selected match.
  history={all:found,side:found.filter(x=>x.f===current.f)};
  const no90=!usable(current.m),noContra=!usable(current.co)||!usable(current.cl);
  const contraLabel=forContra?"την κόντρα +0,5":"το φαβορί";
  const caveat=(no90||noContra)
    ?" Προσωρινή σύγκριση: λείπουν "+[no90?"αποδόσεις 90′":null,noContra?"αποδόσεις κόντρας":null].filter(Boolean).join(" και ")+". Δεν συγκρίνονται ανύπαρκτα στάδια."
    :" Συγκρίθηκαν όλα τα διαθέσιμα χρονικά στάδια.";
  const focus=forContra
    ?" Δίνουμε έμφαση στις αποδόσεις και τα χρήματα της κόντρας, μαζί με το επίπεδο τζίρου."
    :" Δίνουμε έμφαση στις αποδόσεις και τα χρήματα του φαβορί, μαζί με το επίπεδο τζίρου.";
  if(!hasEssential){
    $("insight").textContent=forContra
      ?"Για ιστορικό κόντρας χρειάζονται ποσοστό χρημάτων κόντρας και επίπεδο τζίρου."
      :"Για ιστορικό φαβορί χρειάζονται αρχική/τελευταία απόδοση φαβορί, ποσοστό και επίπεδο τζίρου.";
  }else if(!found.length){
    $("insight").textContent="Δεν βρέθηκαν αρκετά κοντινά ιστορικά ματς για "+contraLabel+". Δοκίμασε «Λίγο πιο ανοιχτά»."+focus+caveat;
  }else{
    $("insight").textContent="Βρέθηκαν "+found.length+" ιστορικά ματς για "+contraLabel+" στα επιλεγμένα πρωταθλήματα."+
      focus+caveat+" Τα ποσοστά είναι ιστορικές συχνότητες, όχι προβλέψεις."+
      (found.length<10?" Το δείγμα είναι μικρό.":"");
  }
  $("allTitle").textContent=forContra?"Όλες οι κόντρες +0,5":"Όλα τα φαβορί";
  $("allSubtitle").textContent="Εντός και εκτός";
  const a=rate(history.all),b=rate(history.side);
  $("allWins").textContent=a.text;$("allN").textContent=a.sub;
  $("sideWins").textContent=b.text;$("sideN").textContent=b.sub;
  $("sideTitle").textContent=(forContra?"Κόντρα":"Φαβορί")+" "+(forContra?(current.f==="H"?"εκτός":"εντός"):(current.f==="H"?"εντός":"εκτός"));
  $("sideSubtitle").textContent="Ίδια έδρα της "+(forContra?"κόντρας":"πλευράς φαβορί")+" με τον αγώνα";
  if(!$("historyDetails").classList.contains("hide"))paintHistory();
}

function paintHistory(){
 const x=history[historyTab]||[];
 const heading=x.length>40?'<p class="tiny" style="padding:8px 0">Τα 40 πιο κοντινά από '+x.length+' · οι συνολικές συχνότητες μετρούν όλα τα ματς</p>':"";
 $("historyRows").innerHTML=x.length?heading+x.slice(0,40).map(z=>{
   const hit=marketWon(z)===true;
   const venue=histMarket==="contra"?(z.f==="H"?"εκτός":"εντός"):(z.f==="H"?"εντός":"εκτός");
   const chosen=histMarket==="contra"?"Κόντρα +0,5":"Φαβορί";
   const result=histMarket==="contra"?(hit?"Κέρδισε η κόντρα +0,5":"Κέρδισε το φαβορί"):(hit?"Κέρδισε το φαβορί":"Κέρδισε η κόντρα +0,5");
   return '<div class="histrow"><div><b>'+safe(name(z))+'</b><small>'+
     safe(z.lg)+' · Ομοιότητα '+z.similarity+'/100 · '+z.features+' στοιχεία · '+chosen+' '+venue+
     '</small><button type="button" class="compare-button subtle" data-compare="'+z.id+'">Δίπλα δίπλα ↗</button></div>'+
     '<div style="text-align:right;white-space:nowrap"><b class="'+(hit?"good":"bad")+'">'+safe(z.r)+
     '</b><small>'+result+'</small></div></div>';
 }).join(""):'<div class="empty">Δεν υπάρχουν παρόμοιοι αγώνες σε αυτή την αναζήτηση.</div>';
 document.querySelectorAll("[data-compare]").forEach(b=>b.addEventListener("click",()=>showHistoricalCompare(+b.dataset.compare)));
 if(compareMatchId!==null && !x.some(z=>z.id===compareMatchId)){
   compareMatchId=null;$("comparePanel").classList.add("hide");
 }else if(compareMatchId!==null)showHistoricalCompare(compareMatchId);
}
function showHistoricalCompare(id){
 if(!current)return;
 const other=(history[historyTab]||[]).find(z=>z.id===id);
 if(!other){$("comparePanel").classList.add("hide");compareMatchId=null;return}
 compareMatchId=id;
 const x=current,score=other.similarity;
 $("compareTitle").textContent=name(x)+" ↔ "+name(other);
 $("compareMeta").textContent="Πρωτάθλημα: "+x.lg+" ↔ "+other.lg+
   " · Ομοιότητα "+score+"/100 · "+other.features+" συγκρίσιμα στοιχεία · "+
   "Τελικό ιστορικού "+other.r;
 // Colors measure closeness, not quality or favorability. A relative turnover
 // percentile is comparable across leagues; absolute turnover is shown as context.
 const definitions=[
   ["Φαβορί",z=>fave(z),null],
   ["Έδρα φαβορί",z=>z.f==="H"?"Εντός":"Εκτός",null],
   ["Αρχική απόδοση φαβορί",z=>z.o,.12],
   ["90′ φαβορί",z=>z.m,.12],
   ["Τελευταία φαβορί",z=>z.l,.12],
   ["Μεταβολή φαβορί",z=>change(z.o,z.l),4,"percentpoint"],
   ["Αρχική κόντρα +0,5",z=>z.co,.18],
   ["90′ κόντρα +0,5",z=>z.cm,.18],
   ["Τελευταία κόντρα +0,5",z=>z.cl,.18],
   ["Μεταβολή κόντρας",z=>change(z.co,z.cl),5,"percentpoint"],
   ["Τζίρος",z=>z.v,null,"cash"],
   ["Τζίρος % μέσα στη λίγκα",z=>z.rank,12,"pct"],
   ["11:00 χρήματα φαβορί",z=>z.p0,8,"pct"],
   ["90′ χρήματα φαβορί",z=>z.p90,8,"pct"],
   ["Τελευταία χρήματα φαβορί",z=>z.p,8,"pct"],
   ["11:00 χρήματα κόντρας",z=>z.contra0,8,"pct"],
   ["90′ χρήματα κόντρας",z=>z.contra90,8,"pct"],
   ["Τελευταία χρήματα κόντρας",z=>z.contra,8,"pct"],
   ["SofaScore",z=>z.s,9,"pct"],
   ["Καμπανάκι Excel",z=>z.alert,null],
   ["Τελικό σκορ",z=>z.r,null]
 ];
 const format=(v,type)=>{
   if(v===null||v===undefined||v==="")return "—";
   if(typeof v==="number"){
     if(type==="cash")return nf(v,0);
     return nf(v,type==="pct"||type==="percentpoint"?1:3)+(type==="pct"||type==="percentpoint"?"%":"");
   }
   return String(v);
 };
 // Exact displayed values from the user's Excel whenever that cell exists.
 const excelKeys={
   "Αρχική απόδοση φαβορί":"o","90′ φαβορί":"m","Τελευταία φαβορί":"l",
   "Αρχική κόντρα +0,5":"co","90′ κόντρα +0,5":"cm","Τελευταία κόντρα +0,5":"cl",
   "Τζίρος":"v","Τζίρος % μέσα στη λίγκα":"percentile",
   "11:00 χρήματα φαβορί":"p0","90′ χρήματα φαβορί":"p90","Τελευταία χρήματα φαβορί":"p",
   "11:00 χρήματα κόντρας":"contra0","90′ χρήματα κόντρας":"contra90",
   "Τελευταία χρήματα κόντρας":"contra","SofaScore":"s"
 };
 const displayCell=(label,z,value,type)=>{
   const k=excelKeys[label];
   return k&&z.display?excelValue(z,k):format(value,type);
 };
 const rows=definitions.map(([label,fn,tol,type])=>{
   const a=fn(x),b=fn(other);
   const matched=tol!==null&&typeof a==="number"&&Number.isFinite(a)&&typeof b==="number"&&Number.isFinite(b);
   const cls=matched?(Math.abs(a-b)<=tol?"same":"far"):"not-comparable";
   return '<tr><td>'+safe(label)+'</td><td>'+safe(displayCell(label,x,a,type))+'</td>'+
     '<td class="'+cls+'">'+safe(displayCell(label,other,b,type))+'</td></tr>';
 }).join("");
 $("compareBody").innerHTML='<table class="compare-table"><thead><tr><th>Στοιχείο</th><th>Επιλεγμένος</th><th>Ιστορικός</th></tr></thead><tbody>'+
    rows+'</tbody></table>';
 $("comparePanel").classList.remove("hide");
}

// Give an interpretable historical lean without treating frequencies as calibrated
// probabilities. "Strength" describes sample size/consistency, not bet confidence.
function opinion(){
  if(!current)return;
  const a=history.all,s=history.side,n=a.length,ns=s.length;
  const wins=a.filter(x=>marketWon(x)===true).length;
  const sideWins=s.filter(x=>marketWon(x)===true).length;
  const p=n?wins/n:null,ps=ns?sideWins/ns:null;
  const blended=p===null?null:ps===null?p:p+.25*(ps-p);
  const conflict=p!==null&&ps!==null&&Math.abs(p-.5)>.08&&Math.abs(ps-.5)>.08&&(p-.5)*(ps-.5)<0;
  const nearlyEven=blended!==null&&Math.abs(blended-.5)<.065;
  const selected=selectedMarketLabel();
  const opposite=histMarket==="contra"?"Νίκη φαβορί":"Κόντρα +0,5";
  let pick="Αποχή",trend="Ανεπαρκή στοιχεία",strength="Ανεπαρκής",note="";
  if(n>=5&&blended!==null){
    if(nearlyEven){trend="Ισορροπημένο ιστορικό";strength="Αδύναμη";}
    else{
      pick=blended>.5?selected:opposite;
      trend=blended>.5?"Προς "+selected.toLowerCase():"Προς "+opposite.toLowerCase();
      const separation=Math.abs(blended-.5);
      strength=!conflict&&n>=25&&ns>=10&&separation>=.20?"Ισχυρή":
        !conflict&&n>=12&&ns>=5&&separation>=.12?"Μέτρια":"Αδύναμη";
      if(conflict)strength="Αδύναμη — αντικρουόμενα δείγματα";
    }
  }
  const stats=n
    ?"Συνολικά "+wins+"/"+n+" επαληθεύσεις "+(histMarket==="contra"?"κόντρας +0,5":"φαβορί")+
       " ("+nf(100*p,0)+"%). "+(ns?"Ίδια έδρα "+sideWins+"/"+ns+" ("+nf(100*ps,0)+"%).":"Δεν υπάρχουν παρόμοια ίδιας έδρας.")
    :"Δεν βρέθηκαν παρόμοια ολοκληρωμένα παιχνίδια.";
  if(n<5)note="Το δείγμα είναι υπερβολικά μικρό για κατεύθυνση.";
  else if(conflict)note="Το συνολικό ιστορικό και η ίδια έδρα δείχνουν αντίθετες κατευθύνσεις.";
  else if(nearlyEven)note="Οι ιστορικές συχνότητες είναι πολύ κοντά, χωρίς ξεκάθαρη πλευρά.";
  else if(n<12||ns<5)note="Υπάρχει κατεύθυνση, αλλά το δείγμα είναι μικρό. Χαμηλή βαρύτητα.";
  else note="Η τάση στηρίζεται στα ιστορικά αποτελέσματα, όχι σε επιβεβαιωμένη πιθανότητα.";
  const chosenPrice=pick==="Νίκη φαβορί"?current.l:pick==="Κόντρα +0,5"?current.cl:null;
  let oddsNote="Οι ιστορικές συχνότητες δεν αποδεικνύουν αξία στην απόδοση.";
  if(pick!=="Αποχή"){
    if(chosenPrice===null||chosenPrice<=1)
      oddsNote="Δεν υπάρχει διαθέσιμη αντίστοιχη απόδοση για έλεγχο. Η τάση δεν είναι πρόταση πονταρίσματος.";
    else{
      const historyShare=pick===selected?p:1-p,breakEven=1/chosenPrice;
      if(historyShare<breakEven)
        oddsNote="Προσοχή στην απόδοση "+price(chosenPrice)+": το ακατέργαστο ιστορικό ποσοστό είναι κάτω από το απαιτούμενο "+nf(100*breakEven,0)+"%. Δεν τεκμηριώνεται αξία.";
      else
        oddsNote="Η απόδοση είναι "+price(chosenPrice)+", αλλά το ιστορικό από μόνο του δεν αποδεικνύει πλεονέκτημα.";
    }
  }
  const provisional=(!usable(current.m)||!usable(current.co)||!usable(current.cl))
    ?" Η σύγκριση είναι προσωρινή: λείπουν αποδόσεις 90′ ή κόντρας.":"";
  const reason="Πλευρά ιστορικής σύγκρισης: "+selected+". "+stats+" "+note+" "+oddsNote+provisional;
  lastOpinion={key:key(current),match:name(current),pick,reason,created:new Date().toISOString(),
    id:current.id,odds:chosenPrice,historyAll:n,historySide:ns,trend,strength,
    analysisSide:histMarket,analysisOnly:true};
  $("opinionText").textContent="Εξετάζεις: "+selected+
    "\nΙστορική τάση: "+trend+"\nΙσχύς ένδειξης: "+strength+
    "\n"+stats+"\n"+note+"\n"+oddsNote+provisional;
  $("opinionText").classList.remove("hide");
}

function renderArchive(){
 const entries=Object.values(autoLedger).filter(e=>e&&e.fixture&&e.recordedAt)
   .sort((a,b)=>String(b.recordedAt).localeCompare(String(a.recordedAt)));
 const results=entries.map(e=>({entry:e,outcome:autoOutcome(e)}));
 const chosen=results.filter(z=>z.entry.pick!=="abstain");
 const graded=chosen.filter(z=>z.outcome==="win"||z.outcome==="lose");
 const correct=graded.filter(z=>z.outcome==="win").length;
 for(let i=1;i<=3;i++){
   const inLevel=graded.filter(z=>z.entry.level===i);
   const ok=inLevel.filter(z=>z.outcome==="win").length;
   $("grade"+i+"Stats").textContent=inLevel.length?ok+"/"+inLevel.length:"—";
   $("grade"+i+"Note").textContent=inLevel.length?nf(ok/inLevel.length*100,0)+"% ιστορική επαλήθευση":"Καμία ολοκληρωμένη";
 }
 const fav=graded.filter(z=>z.entry.pick==="fav"),contra=graded.filter(z=>z.entry.pick==="contra");
 const ratio=z=>z.length?z.filter(x=>x.outcome==="win").length+"/"+z.length:"—";
 $("autoTotals").textContent="Καταγραφές "+entries.length+" · Με τελικό σκορ "+
   results.filter(z=>z.outcome!=="pending").length+" · Αποχές "+
   results.filter(z=>z.entry.pick==="abstain").length+" · "+
   "Επιτυχίες "+(graded.length?correct+"/"+graded.length:"—")+
   " · Φαβορί "+ratio(fav)+" · Κόντρα "+ratio(contra)+
   ". Μετράμε μόνο πραγματικές καταγραφές πριν από τη σέντρα, όχι παλιούς αγώνες εκ των υστέρων.";
 $("autoArchiveRows").innerHTML=results.length?results.slice(0,80).map(({entry:e,outcome})=>{
   const title=e.pick==="fav"?"Φαβορί":e.pick==="contra"?"Κόντρα +0,5":"Αποχή";
   const status=outcome==="win"?"✓ Επαληθεύτηκε":
     outcome==="lose"?"✕ Δεν επαληθεύτηκε":
     outcome==="abstain"?"— Αποχή · Δεν μετρά ως επιτυχία":"⌛ Αναμονή αποτελέσματος";
   const statusClass=outcome==="win"?"win":outcome==="lose"?"lose":"pending";
   const lock=new Date(e.recordedAt).toLocaleString("el-GR");
   return '<div class="auto-entry"><b>'+safe(e.match)+'</b><small>'+
     safe(e.league)+' · '+safe(title)+' · '+safe(e.pick==="abstain"?"Δεν βαθμολογείται":e.level+"/3 · "+(levelNames[e.level]||"Αδύναμη"))+
     '</small><small>Κλειδώθηκε '+safe(lock)+' · Έναρξη '+safe(String(e.kickoff||""))+
     '</small><small class="'+statusClass+'">'+status+'</small></div>';
 }).join(""):'<div class="empty">Δεν υπάρχουν ακόμη αυτόματες προ-αγωνιστικές αποφάσεις. Θα καταγράφονται όταν η εφαρμογή είναι ανοιχτή πριν από τη σέντρα και υπάρχουν αρκετά στοιχεία.</div>';
 const manual=journal.map(j=>{
   const x=matches.find(m=>key(m)===j.key&&finished(m));
   const status=x?(j.pick==="Αποχή"?"Αποχή":j.pick==="Νίκη φαβορί"?
      (won(x)?"Επαληθεύτηκε":"Δεν επαληθεύτηκε"):
      (!won(x)?"Επαληθεύτηκε":"Δεν επαληθεύτηκε")):"Αναμονή σκορ";
   const created=new Date(j.created);
   return '<div class="histrow"><div><b>'+safe(j.match)+'</b><small>'+safe(j.pick)+
     ' · '+safe(Number.isFinite(created.getTime())?created.toLocaleString("el-GR"):"—")+
     '</small></div><div class="tiny">'+safe(status)+'</div></div>';
 });
 $("archiveRows").innerHTML=manual.join("")||"Δεν υπάρχουν χειροκίνητες εκτιμήσεις.";
}

async function getJSON(url,opt){let r=await fetch(url,{credentials:"same-origin",cache:"no-store",...opt});let d=await r.json();if(r.status===401&&url!=="/api/login"){$("app").classList.add("hide");$("login").classList.remove("hide");throw Error("Χρειάζεται σύνδεση.")}return d}
let refreshInFlight=false,feedRetryTimer=null,feedRetryCount=0;
function scheduleFeedRetry(){
  if(feedRetryTimer!==null)return;
  const wait=feedRetryCount<8?3000:8000;
  feedRetryCount++;
  feedRetryTimer=setTimeout(()=>{
    feedRetryTimer=null;
    if(!$("app").classList.contains("hide"))refresh();
  },wait);
}
async function refresh(){
  if(refreshInFlight)return;
  refreshInFlight=true;
  const status=$("feedStatus");
  if(!matches.length){status.textContent="Σύνδεση με Excel…";status.className="status";}
  try{
    const d=await getJSON("/api/matches");
    if(!d.ok){
      if(d.state==="loading"){
        status.textContent=feedRetryCount>=8?"Το Excel αργεί — προσπάθεια…":"Ανάκτηση Excel…";
        status.className="status";
        if(!matches.length){
          $("matchTitle").textContent="Φορτώνουμε τους αγώνες…";
          $("insight").textContent="Η σύνδεση λειτουργεί. Η ανάγνωση του Excel γίνεται στο παρασκήνιο, χωρίς να μπλοκάρει την εφαρμογή.";
        }
        scheduleFeedRetry();
        return;
      }
      status.textContent=d.state==="not_connected"?"Αναμονή σύνδεσης Excel":"Πρόβλημα ενημέρωσης";
      status.className="status warn";
      if(!matches.length){
        $("matchTitle").textContent="Αναμονή δεδομένων Excel";
        $("insight").textContent="Δεν ολοκληρώθηκε ακόμη η ανάκτηση. Θα προσπαθήσουμε ξανά αυτόματα.";
      }
      if(d.state!=="not_connected")scheduleFeedRetry();
      return;
    }
    feedRetryCount=0;
    if(feedRetryTimer!==null){clearTimeout(feedRetryTimer);feedRetryTimer=null}
    const selectedKey=current?key(current):null;
    matches=d.rows.map((r,i)=>{
      const x=parseRow(r,i);
      x.formats=Array.isArray(d.formats)&&d.formats[i]&&typeof d.formats[i]==="object"?d.formats[i]:{};
      return x;
    }).filter(x=>x.lg&&x.h&&x.a&&["H","A"].includes(x.f));
    setupRanks();setupLeagues();fillLeagueFilter();
    captureAutoPredictions();
    buildMarketWatch();
    status.textContent=d.stale?"Παλαιότερα δεδομένα":"Excel συνδεδεμένο";
    status.className=d.stale?"status warn":"status live";
    $("updatedAt").textContent="Ανάκτηση: "+new Date(d.serverFetchedAt||Date.now()).toLocaleString("el-GR");
    current=matches.find(x=>key(x)===selectedKey)
      ||matches.filter(x=>!finished(x)).slice(-1)[0]||matches.slice(-1)[0]||null;
    if(current&&key(current)!==selectedKey){histMarket="fav";clearOpinion()}
    if(current)render();else $("matchTitle").textContent="Δεν υπάρχουν αγώνες στο Excel";
    listMatches();
  }catch(e){
    status.textContent="Διακοπή σύνδεσης — επανάληψη…";
    status.className="status warn";
    if(!matches.length)$("insight").textContent="Η σύνδεση καθυστερεί. Η εφαρμογή θα ξαναδοκιμάσει χωρίς να χρειάζεται να την κλείσεις.";
    scheduleFeedRetry();
  }finally{
    refreshInFlight=false;
  }
}
async function boot(){try{let d=await getJSON("/api/session");if(d.authenticated){$("login").classList.add("hide");$("app").classList.remove("hide");await refresh()}else{$("login").classList.remove("hide")}}catch(e){$("login").classList.remove("hide")}}
$("loginForm").addEventListener("submit",async e=>{e.preventDefault();$("loginError").textContent="Σύνδεση…";try{let d=await getJSON("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:$("password").value})});if(!d.ok){$("loginError").textContent=d.error==="not_configured"?"Η πρόσβαση δεν έχει ενεργοποιηθεί ακόμα.":d.error==="too_many_attempts"?"Πολλές προσπάθειες. Δοκίμασε σε 10 λεπτά.":"Λάθος κωδικός.";return}$("password").value="";$("loginError").textContent="";$("login").classList.add("hide");$("app").classList.remove("hide");await refresh()}catch(e){$("loginError").textContent="Δεν ήταν δυνατή η σύνδεση."}});
$("logout").addEventListener("click",async()=>{await fetch("/api/logout",{method:"POST",credentials:"same-origin"});$("app").classList.add("hide");$("login").classList.remove("hide")});
$("reload").addEventListener("click",refresh);$("search").addEventListener("input",listMatches);$("leagueFilter").addEventListener("change",listMatches);
document.querySelectorAll("[data-tab]").forEach(b=>b.addEventListener("click",()=>{tab=b.dataset.tab;document.querySelectorAll("[data-tab]").forEach(z=>z.classList.toggle("active",z===b));listMatches()}));
document.querySelectorAll("[data-mode]").forEach(b=>b.addEventListener("click",()=>{mode=b.dataset.mode;document.querySelectorAll("[data-mode]").forEach(z=>z.setAttribute("aria-pressed",String(z===b)));clearOpinion();renderHistory()}));
document.querySelectorAll("[data-market]").forEach(b=>b.addEventListener("click",()=>{
  if(histMarket===b.dataset.market)return;
  histMarket=b.dataset.market;
  clearOpinion();renderHistory();
}));
$("settingsToggle").addEventListener("click",()=>$("settings").classList.toggle("hide"));
document.querySelectorAll("[data-preset]").forEach(b=>b.addEventListener("click",()=>{let all=allLeagues();leaguesSelected=b.dataset.preset==="all"?all:b.dataset.preset==="none"?[]:all.filter(x=>!excluded.test(x));savedLeagues=leaguesSelected;store("sv_live_leagues",savedLeagues);paintSettings();clearOpinion();renderHistory()}));
$("viewHistory").addEventListener("click",()=>{$("historyDetails").classList.toggle("hide");$("viewHistory").textContent=$("historyDetails").classList.contains("hide")?"Δες ματς & σκορ ▾":"Κρύψε τα ματς ▴";paintHistory()});
$("closeCompare").addEventListener("click",()=>{compareMatchId=null;$("comparePanel").classList.add("hide")});
document.querySelectorAll("[data-history]").forEach(b=>b.addEventListener("click",()=>{historyTab=b.dataset.history;document.querySelectorAll("[data-history]").forEach(z=>z.classList.toggle("active",z===b));paintHistory()}));
$("opinion").addEventListener("click",opinion);
$("marketWatchToggle").addEventListener("click",toggleMarketWatch);
$("marketWatchClose").addEventListener("click",closeMarketWatch);
$("marketToolAnalyst").addEventListener("click",()=>selectMarketTool("analyst"));
$("marketToolHunter").addEventListener("click",()=>selectMarketTool("hunter"));
$("marketToolPsych").addEventListener("click",()=>selectMarketTool("psych"));
$("archiveToggle").addEventListener("click",()=>$("archive").classList.toggle("hide"));
$("fingerprintModeOdds").addEventListener("click",()=>setFingerprintMode(false));
$("fingerprintModeBoth").addEventListener("click",()=>setFingerprintMode(true));
$("fingerprintToggle").addEventListener("click",()=>{
  const panel=$("fingerprintDetails"),nowHidden=panel.classList.toggle("hide");
  $("fingerprintToggle").setAttribute("aria-expanded",String(!nowHidden));
  $("fingerprintToggle").textContent=nowHidden?"Δες γράφημα ▾":"Κρύψε γράφημα ▴";
  if(!nowHidden)renderFingerprint();
});
$("snapToggle").addEventListener("click",()=>{
  const shown=$("snapDetails").classList.toggle("hide");
  $("snapToggle").setAttribute("aria-expanded",String(!shown));
  $("snapToggle").textContent=shown?"Δες τα 3 στάδια του Excel ▾":"Κρύψε τα 3 στάδια ▴";
});
$("saveOpinion").addEventListener("click",()=>{if(!current||finished(current)){alert("Δεν αποθηκεύουμε εκτίμηση αφού βγει τελικό σκορ.");return}if(!lastOpinion||lastOpinion.key!==key(current)||lastOpinion.analysisSide!==histMarket){alert("Πάτησε πρώτα «Εσύ τι θα επέλεγες;» για την επιλεγμένη πλευρά.");return}journal=[lastOpinion,...journal].slice(0,250);store("sv_live_journal",journal);renderArchive();alert("Αποθηκεύτηκε στη συσκευή.")});
boot();
setInterval(()=>{if(!$("app").classList.contains("hide"))refresh()},600000);
