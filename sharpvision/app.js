"use strict";
const $=id=>document.getElementById(id);
let matches=[],current=null,leaguesSelected=null,history={all:[],side:[]},mode="strict",tab="open",historyTab="all",lastOpinion=null,loadedAt=null;
const excluded=/(Finland|Norway|Sweden|Denmark|Scotland|USA|Brazil|Argentina|ΕΘΝΙΚΕΣ|Nations League)/i;
const store=(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}};
const read=(k,d)=>{try{let v=localStorage.getItem(k);return v===null?d:JSON.parse(v)}catch(e){return d}};
let favorites=read("sv_live_faves",[]),journal=read("sv_live_journal",[]),savedLeagues=read("sv_live_leagues",null);
// Default to favorite on every new match and page opening.
let histMarket="fav";
let autoLedger=read("sv_prelock_v3",{});if(!autoLedger||Array.isArray(autoLedger)||typeof autoLedger!=="object")autoLedger={};
let compareMatchId=null;
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
  renderAutoCard();renderHistory();renderArchive();
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
// SHARPVISION MARKET PSYCHOLOGY v3
// These are observable market behaviors, not claims about bettors' intentions.
// Explicitly independent of Excel alerts, colors, alert ratings and alerts log.
const svClip=(v,min=-1,max=1)=>Math.max(min,Math.min(max,v));
const svSign=v=>v>.24?1:v<-.24?-1:0;
const svWord=s=>s>0?"φαβορί":s<0?"κόντρα":"καμία πλευρά";
const svPercent=v=>nf(v,1)+"%";
function svFairMarket(z){
  if(!usable(z.l)||z.l<=1.01)return null;
  const a=1/z.l;
  if(usable(z.cl)&&z.cl>1.01){const b=1/z.cl;return svClip(a/(a+b),.05,.95)}
  return svClip(a,.05,.95);
}
function svHistorySignal(x,prior){
  const unique=new Map(),views={fav:0,contra:0};
  for(const z of prior){
    if(!finished(z)||autoKey(x)===autoKey(z))continue;
    for(const side of ["fav","contra"]){
      const result=similarity(x,z,side,"wide");
      if(!result||result.features<6||result.similarity<77)continue;
      views[side]++;
      const id=autoKey(z),existing=unique.get(id);
      if(!existing||result.similarity>existing.sim.similarity)unique.set(id,{x:z,sim:result});
    }
  }
  const ranked=[...unique.values()].sort((a,b)=>b.sim.similarity-a.sim.similarity);
  // Repeated entries of the same league cannot crowd out other competitions.
  const leagueCounts={},items=[];
  for(const entry of ranked){
    const league=entry.x.lg;
    if((leagueCounts[league]||0)>=12)continue;
    items.push(entry);leagueCounts[league]=(leagueCounts[league]||0)+1;
    if(items.length>=36)break;
  }
  const n=items.length,same=items.filter(z=>z.x.f===x.f).length;
  if(n<7)return {n,same,score:null,avg:0,views,reason:"Λίγα πραγματικά συγκρίσιμα αποτελέσματα ("+n+")."};
  let sum=0,ws=0,sum2=0,win=0,expected=0,known=0;
  for(const z of items){
    const baseline=svFairMarket(z.x);
    if(baseline===null)continue;
    const w=Math.pow(z.sim.similarity/100,5)*(z.x.f===x.f?1.09:1);
    ws+=w;sum2+=w*w;sum+=w*((won(z.x)?1:0)-baseline);
    expected+=w*baseline;win+=w*(won(z.x)?1:0);known++;
  }
  if(!ws||known<7)return {n,same,score:null,avg:0,views,reason:"Λείπει ιστορική τιμή αγοράς από τα συγκρίσιμα ματς."};
  const neff=ws*ws/sum2,delta=sum/ws;
  // 14 prior-equivalent observations regularize noisy small samples.
  const adjusted=delta*(neff/(neff+14));
  const score=svClip(adjusted/.13);
  const avg=items.reduce((v,z)=>v+z.sim.similarity,0)/n;
  return {n,same,score,avg,views,edge:adjusted,
    reason:n+" διαφορετικοί παρόμοιοι αγώνες ("+same+" ίδιας έδρας), ομοιότητα "+
      nf(avg,0)+"/100. Σε σύγκριση με τις αντίστοιχες τιμές τους, "+
      (adjusted>=0?"τα φαβορί πήγαν σχετικά καλύτερα.":"οι κόντρες πήγαν σχετικά καλύτερα.")};
}
function svOddsSignal(x){
 const openingFav=change(x.o,x.l),openingContra=change(x.co,x.cl);
 const lateFav=change(x.m,x.l),lateContra=change(x.cm,x.cl);
 const total=[],late=[];
 if(usable(openingFav))total.push(svClip(-openingFav/7));
 if(usable(openingContra))total.push(svClip(openingContra/8));
 if(usable(lateFav))late.push(svClip(-lateFav/4));
 if(usable(lateContra))late.push(svClip(lateContra/5));
 const mean=a=>a.length?a.reduce((v,z)=>v+z,0)/a.length:null;
 const whole=mean(total),latest=mean(late);
 if(whole===null&&latest===null)
   return {score:null,late:null,contradiction:false,reason:"Δεν υπάρχουν αρκετά στοιχεία μεταβολής αποδόσεων."};
 const contradiction=total.length===2&&total[0]*total[1]<-.12||
   late.length===2&&late[0]*late[1]<-.12;
 const base=whole===null?latest:latest===null?whole:.62*whole+.38*latest;
 return {score:svClip(base),late:latest,contradiction,
  reason:base>.18?"Οι τιμές κινούνται προς το φαβορί (πέφτει η δική του ή ανεβαίνει της κόντρας).":
    base<-.18?"Οι τιμές κινούνται προς την κόντρα (ανεβαίνει του φαβορί ή πέφτει της κόντρας).":
    "Οι αποδόσεις έχουν μικτή ή σχεδόν ουδέτερη κίνηση."};
}
function svMoneySignal(x){
  if(!usable(x.p))return {score:null,reason:"Δεν υπάρχουν δεδομένα ποσοστού χρημάτων."};
  const stages=[];
  if(usable(x.p0))stages.push(svClip((x.p-x.p0)/11));
  if(usable(x.p90))stages.push(svClip((x.p-x.p90)/8));
  if(usable(x.p0)&&usable(x.p90))stages.push(svClip((x.p90-x.p0)/10)*.5);
  if(!stages.length)return {score:null,reason:"Γνωρίζουμε την κατανομή χρημάτων, αλλά όχι πώς άλλαξε στον χρόνο."};
  const score=svClip(stages.reduce((v,z)=>v+z,0)/stages.length*1.18);
  return {score,reason:score>.19?"Το ποσοστό χρημάτων μετακινείται προς το φαβορί ("+svPercent(x.p)+").":
   score<-.19?"Το ποσοστό χρημάτων μετακινείται προς την κόντρα ("+svPercent(100-x.p)+").":
   "Τα ποσοστά χρημάτων δεν δείχνουν ουσιαστική νέα μετακίνηση."};
}
function automaticOpinion(x,prior){
  const odds=svOddsSignal(x),moneyFlow=svMoneySignal(x),history=svHistorySignal(x,prior);
  const cautions=[],details=[],evidence=[];
  // This is intensity, not a directional vote: turnover alone predicts neither side.
  const turnover=usable(x.rank)?x.rank:null;
  const sufficientTurn=turnover!==null&&turnover>=65;
  if(turnover===null)cautions.push("Δεν γνωρίζουμε συγκρίσιμο επίπεδο τζίρου.");
  else if(turnover<35)cautions.push("Χαμηλός σχετικός τζίρος: ευάλωτες μεταβολές αποδόσεων.");
  else details.push("Τζίρος "+nf(turnover,0)+"ο εκατοστημόριο λίγκας — ένταση, όχι κατεύθυνση.");
  if(odds.score!==null){
    details.push(odds.reason);evidence.push({name:"Αποδόσεις",score:odds.score,weight:.36});
  }else details.push(odds.reason);
  if(moneyFlow.score!==null){
    details.push(moneyFlow.reason);evidence.push({name:"Μεταβολή χρημάτων",score:moneyFlow.score,weight:.26});
  }else details.push(moneyFlow.reason);
  if(history.score!==null){
    details.push(history.reason);evidence.push({name:"Ιστορική υπεραπόδοση έναντι αγοράς",score:history.score,weight:.38});
  }else details.push(history.reason);
  if(odds.contradiction)cautions.push("Οι δύο τιμές (φαβορί/κόντρα) δεν επιβεβαιώνουν την ίδια κίνηση.");
  const priceDir=svSign(odds.score??0),moneyDir=svSign(moneyFlow.score??0),histDir=svSign(history.score??0);
  const moneyPriceConflict=priceDir*moneyDir===-1;
  if(moneyPriceConflict){
    cautions.push("Αντίφαση: τα χρήματα πάνε προς "+svWord(moneyDir)+
      ", ενώ η κίνηση αποδόσεων στηρίζει "+svWord(priceDir)+
      ". Δεν μπορούμε να ξέρουμε γιατί.");
  }else if(priceDir!==0&&priceDir===moneyDir){
    details.push("Αποδόσεις και νέα ροή χρημάτων συμφωνούν προς "+svWord(priceDir)+".");
  }
  if(history.n>=7&&histDir!==0&&priceDir!==0&&histDir!==priceDir)
    cautions.push("Το ιστορικό διαφωνεί με την τωρινή τιμή αγοράς.");
  if(odds.late!==null&&svSign(odds.late)!==0&&priceDir!==0&&svSign(odds.late)!==priceDir)
    cautions.push("Ανατροπή τάσης στο τελευταίο στάδιο αποδόσεων.");
  if(usable(x.v)&&usable(x.v90)&&x.v90>0&&x.v/x.v90>=2.5)
    details.push("Ο τζίρος αυξήθηκε έντονα μετά το στιγμιότυπο 90′: απαιτείται προσοχή στη νεότερη κίνηση.");
  const weight=evidence.reduce((a,z)=>a+z.weight,0);
  const total=weight?evidence.reduce((a,z)=>a+z.weight*z.score,0)/weight:0;
  const direction=svSign(total);
  const supports=evidence.filter(z=>svSign(z.score)===direction&&direction!==0);
  const against=evidence.filter(z=>svSign(z.score)===-direction&&direction!==0);
  // Two independent families must agree. The two odds timestamps are one
  // family, never counted as separate corroborations.
  let pick="abstain",level=0;
  if(direction!==0&&supports.length>=2&&Math.abs(total)>=.34&&!odds.contradiction){
    pick=direction>0?"fav":"contra";
    level=1;
    if(Math.abs(total)>=.44&&supports.length>=2&&against.length===0&&
       sufficientTurn&&!moneyPriceConflict&&history.n>=8)
       level=2;
    if(level>=2&&supports.length===3&&against.length===0&&
       Math.abs(total)>=.67&&history.n>=22&&history.same>=7&&
       history.avg>=87&&sufficientTurn&&turnover>=75&&
       !cautions.some(z=>/Ανατροπή|Αντίφαση|διαφωνεί/.test(z))&&
       ["m","cm","p0","p90"].every(k=>usable(x[k])))
       level=3;
  }
  const label=pick==="fav"?"Φαβορί":pick==="contra"?"Κόντρα +0,5":"Αποχή";
  let summary;
  if(pick==="abstain"){
    summary="Αποχή: δεν συμφωνούν τουλάχιστον δύο ανεξάρτητες ενδείξεις ή η αγορά δίνει αντικρουόμενα μηνύματα.";
  }else{
    summary="Επιλογή "+label+": "+supports.map(z=>z.name).join(" και ")+
      " στηρίζουν την ίδια πλευρά."+
      (level===3?" Τρεις ανεξάρτητες ενδείξεις με ισχυρή συμφωνία.":
      level===2?" Αρκετή συνοχή, όχι όμως πλήρης επιβεβαίωση.":" Υπάρχουν ενδείξεις αλλά και ουσιαστική αβεβαιότητα.");
  }
  const lines=[summary,...details,...cautions.map(z=>"ΠΡΟΣΟΧΗ: "+z),
    "Οι ενδείξεις περιγράφουν συμπεριφορά της αγοράς, όχι προθέσεις παικτών ή βεβαιότητα αποτελέσματος."];
  return {
    pick,level,source:"sharpvision_market_psychology",version:"v3",
    sample:history.n,sameVenue:history.same,similarityAvg:history.avg?Math.round(history.avg):0,
    nFav:history.views.fav,nContra:history.views.contra,
    marketScore:Math.round(total*100),evidence:details,cautions,
    reason:lines.join("\n")
  };
}
function captureAutoPredictions(){
 const now=Date.now();
 const due=matches.filter(x=>kickoffMs(x)!==null&&kickoffMs(x)>now+120000&&kickoffMs(x)<=now+75*60000&&!finished(x)&&
   usable(x.o)&&usable(x.l)&&usable(x.p)&&usable(x.rank)&&!autoLedger[autoKey(x)]);
 if(!due.length)return;
 // Only outcomes already recorded as final on the pre-kickoff snapshot may
 // supply evidence. Finished matches with known later kickoffs are excluded.
 const earlier=matches.filter(z=>finished(z)&&(kickoffMs(z)===null||kickoffMs(z)<now));
 let changed=false;
 for(const x of due)try{
   if(Date.now()>=kickoffMs(x)-60000||autoLedger[autoKey(x)])continue;
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
   store("sv_prelock_v3",autoLedger);
 }
}
function autoOutcome(entry){
 const x=matches.find(z=>autoKey(z)===entry.fixture);
 if(!x||!finished(x))return "pending";
 if(entry.pick==="abstain")return "abstain";
 const winner=won(x);
 return entry.pick==="fav"?(winner?"win":"lose"):(winner?"lose":"win");
}
function renderAutoCard(){
 if(!current)return;
 const x=current,t=kickoffMs(x),saved=autoLedger[autoKey(x)];
 const badge=$("autoGrade"),pick=$("autoPick"),reason=$("autoReason"),lock=$("autoLock");
 const set=(lv,grade,title,why,when)=>{
   badge.className="prematch-tag level-"+lv;badge.textContent=grade;
   pick.textContent=title;reason.textContent=why;lock.textContent=when;
 };
 if(saved){
   const titles={fav:"Νίκη φαβορί · "+saved.favorite,contra:"Κόντρα +0,5",abstain:"Αποχή"};
   const result=autoOutcome(saved);
   set(saved.level,saved.pick==="abstain"?"Αποχή · Χωρίς βαθμίδα":saved.level+"/3 · "+levelNames[saved.level],titles[saved.pick]||"Αποχή",saved.reason,
     "Κλειδώθηκε "+new Date(saved.recordedAt).toLocaleString("el-GR")+" · Πριν από "+kickoffLabel(x)+
     (result==="win"?" · Επαληθεύτηκε":result==="lose"?" · Δεν επαληθεύτηκε":" · Αναμονή αποτελέσματος"));
 }else if(t===null){
   set(1,"1/3 · Χωρίς ώρα","Δεν υπάρχει προ-αγωνιστική καταγραφή",
     "Λείπει έγκυρη ώρα έναρξης στην BY του Excel. Δεν μπορούμε να επιβεβαιώσουμε ότι δεν ξεκίνησε.",
     "Δεν επινοούμε ώρα έναρξης.");
 }else if(Date.now()>=t-60000||finished(x)){
   set(1,"1/3 · Χωρίς εγγραφή","Δεν καταγράφηκε πριν τη σέντρα",
     "Αυτός ο αγώνας δεν είχε προ-αγωνιστική καταγραφή σε αυτή τη συσκευή. Δεν συμπληρώνουμε εκτιμήσεις μετά τη σέντρα.",
     "Έναρξη: "+kickoffLabel(x));
 }else{
   set(1,"1/3 · Αναμονή","Περιμένουμε αποδόσεις",
     "Μόλις εμφανιστούν οι αρχικές και τελευταίες αποδόσεις, ποσοστά και τζίρος, καταγράφεται απόφαση, ακόμη κι αν δεν ανοίξεις το συγκεκριμένο παιχνίδι.",
     "Έναρξη: "+kickoffLabel(x)+" · Η εφαρμογή πρέπει να είναι ανοιχτή.");
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
$("archiveToggle").addEventListener("click",()=>$("archive").classList.toggle("hide"));
$("snapToggle").addEventListener("click",()=>{
  const shown=$("snapDetails").classList.toggle("hide");
  $("snapToggle").setAttribute("aria-expanded",String(!shown));
  $("snapToggle").textContent=shown?"Δες τα 3 στάδια του Excel ▾":"Κρύψε τα 3 στάδια ▴";
});
$("saveOpinion").addEventListener("click",()=>{if(!current||finished(current)){alert("Δεν αποθηκεύουμε εκτίμηση αφού βγει τελικό σκορ.");return}if(!lastOpinion||lastOpinion.key!==key(current)||lastOpinion.analysisSide!==histMarket){alert("Πάτησε πρώτα «Εσύ τι θα επέλεγες;» για την επιλεγμένη πλευρά.");return}journal=[lastOpinion,...journal].slice(0,250);store("sv_live_journal",journal);renderArchive();alert("Αποθηκεύτηκε στη συσκευή.")});
boot();
setInterval(()=>{if(!$("app").classList.contains("hide"))refresh()},600000);
