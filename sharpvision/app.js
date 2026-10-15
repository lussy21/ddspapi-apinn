"use strict";
const $=id=>document.getElementById(id);
let matches=[],current=null,leaguesSelected=null,history={all:[],side:[]},mode="strict",tab="open",historyTab="all",lastOpinion=null,loadedAt=null;
const excluded=/(Finland|Norway|Sweden|Denmark|Scotland|USA|Brazil|Argentina|ΕΘΝΙΚΕΣ|Nations League)/i;
const store=(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}};
const read=(k,d)=>{try{let v=localStorage.getItem(k);return v===null?d:JSON.parse(v)}catch(e){return d}};
let favorites=read("sv_live_faves",[]),journal=read("sv_live_journal",[]),savedLeagues=read("sv_live_leagues",null);
function num(v,col){if(typeof v==="number")return Number.isFinite(v)?v:null;let s=String(v??"").replace(/[%€\s]/g,"");if(!s)return null;if(s.includes(",")&&s.includes("."))s=s.replace(/\./g,"").replace(",",".");else if(s.includes(","))s=s.replace(",",".");else if([10,19,22].includes(col)&&/^\d{1,3}(\.\d{3})+$/.test(s))s=s.replace(/\./g,"");let n=Number(s);return Number.isFinite(n)?n:null}
const nf=(v,d=1)=>v!==null&&Number.isFinite(v)?new Intl.NumberFormat("el-GR",{minimumFractionDigits:d,maximumFractionDigits:d}).format(v):"—";
const price=v=>nf(v,3),per=v=>v===null?"—":nf(v,1)+"%",money=v=>v===null?"—":new Intl.NumberFormat("el-GR",{maximumFractionDigits:0}).format(v)+" €";
const safe=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const norm=s=>String(s??"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().trim();
const name=x=>x.h+" – "+x.a, fave=x=>x.f==="H"?x.h:x.a, key=x=>[x.lg,x.h,x.a].map(norm).join("|");
const parsedScore=x=>{let m=String(x.r||"").match(/^\s*(\d+)\s*[-:]\s*(\d+)\s*$/);return m?[+m[1],+m[2]]:null};
const finished=x=>parsedScore(x)!==null;
function won(x){let s=parsedScore(x);return s?(x.f==="H"?s[0]>s[1]:s[1]>s[0]):null}
function parseRow(r,i){return {id:i+3,lg:String(r[0]||""),h:String(r[1]||""),a:String(r[2]||""),f:r[3],o:num(r[4],4),m:num(r[5],5),l:num(r[6],6),co:num(r[7],7),cm:num(r[8],8),cl:num(r[9],9),v:num(r[10],10),p:num(r[11],11),contra:num(r[12],12),s:num(r[13],13),r:String(r[15]||""),v0:num(r[19],19),p0:num(r[20],20),v90:num(r[22],22),p90:num(r[23],23),rank:null}}
// Identical turnover league-relative percentile formula and breakpoints to PINNACLE column K.
// Excel counts ALL numeric K values in the same league, including unfinished fixtures.
function setupRanks(){
  const pools={};
  for(const x of matches)if(Number.isFinite(x.v)&&x.v>=0)(pools[x.lg]??=[]).push(x.v);
  for(const x of matches){
    const pool=pools[x.lg]||[];
    x.leagueN=pool.length;
    x.rank=Number.isFinite(x.v)&&x.v>=0 ? 100*(pool.filter(n=>n<=x.v).length-1)/Math.max(1,pool.length-1) : null;
  }
}
function band(v){if(v===null||!Number.isFinite(v))return 0;return v<=35?1:v<=75?2:v<=87?3:4}
function pband(v,type){
  if(v===null||!Number.isFinite(v))return 0;
  if(type==="contra")return v>=32?4:v>=26?2:0;
  if(type==="sofa")return v>=82?4:v>=75?3:0;
  return v>=82?4:v>=75?2:0;
}
function color(id,level,type){$(id).className="metric"+(level?" excel-"+type+"-"+level:"")}
function allLeagues(){return [...new Set(matches.map(x=>x.lg))].filter(Boolean).sort((a,b)=>a.localeCompare(b))}
function setupLeagues(){let names=allLeagues();leaguesSelected=Array.isArray(savedLeagues)?savedLeagues.filter(n=>names.includes(n)):names.filter(n=>!excluded.test(n));paintSettings()}
function paintSettings(){$("checks").innerHTML=allLeagues().map((l,i)=>'<label><input type="checkbox" data-league="'+safe(l)+'" '+(leaguesSelected.includes(l)?"checked":"")+'> '+safe(l)+'</label>').join("");$("checks").querySelectorAll("input").forEach(i=>i.addEventListener("change",()=>{leaguesSelected=i.checked?[...leaguesSelected,i.dataset.league]:leaguesSelected.filter(l=>l!==i.dataset.league);savedLeagues=leaguesSelected;store("sv_live_leagues",savedLeagues);renderHistory()}))}
function activeList(){let q=norm($("search").value);let aliases={αστον:"aston",βιλα:"villa",φεγενορντ:"feyenoord",σιτι:"city",παρι:"paris",ντορτμουντ:"dortmund",ρεαλ:"real",κομο:"como"};for(let [greek,english] of Object.entries(aliases))if(q.includes(greek))q=q.replace(greek,english);let lg=$("leagueFilter").value;let items=matches.filter(x=>!lg||x.lg===lg);if(q)items=items.filter(x=>norm(name(x)+" "+x.lg).includes(q));else if(tab==="open")items=items.filter(x=>!finished(x));else if(tab==="faves")items=items.filter(x=>favorites.includes(key(x)));else items=items.filter(finished);return items.slice().reverse().slice(0,80)}
function fillLeagueFilter(){let old=$("leagueFilter").value;$("leagueFilter").innerHTML='<option value="">Όλα τα πρωταθλήματα</option>'+allLeagues().map(x=>'<option value="'+safe(x)+'">'+safe(x)+'</option>').join("");$("leagueFilter").value=allLeagues().includes(old)?old:""}
function listMatches(){let v=activeList();$("matchCount").textContent=v.length+(v.length>=80?"+":"")+" αγώνες";$("matchList").innerHTML=v.length?v.map(x=>'<div class="matchitem '+(current&&x.id===current.id?"active":"")+'"><button class="star '+(favorites.includes(key(x))?"on":"")+'" data-star="'+x.id+'" aria-label="Αγαπημένο">★</button><button class="matchtext" data-match="'+x.id+'" style="background:none;border:0;padding:0;text-align:left"><b>'+safe(name(x))+'</b><small>'+safe(x.lg)+(finished(x)?" · "+safe(x.r):" · Χωρίς τελικό σκορ")+'</small></button></div>').join(""):'<div class="empty">Δεν βρέθηκαν αγώνες. Δοκίμασε άλλη αναζήτηση ή καρτέλα.</div>';document.querySelectorAll("[data-match]").forEach(b=>b.addEventListener("click",()=>select(+b.dataset.match)));document.querySelectorAll("[data-star]").forEach(b=>b.addEventListener("click",()=>{let x=matches.find(z=>z.id===+b.dataset.star),k=key(x);favorites=favorites.includes(k)?favorites.filter(z=>z!==k):[...favorites,k];store("sv_live_faves",favorites);listMatches()}))}
function select(id){current=matches.find(x=>x.id===id);lastOpinion=null;$("opinionText").classList.add("hide");listMatches();render()}
function render(){if(!current)return;$("matchLeague").textContent=current.lg;$("matchTitle").textContent=name(current);$("favLabel").textContent="Φαβορί: "+fave(current)+" · "+(current.f==="H"?"Εντός":"Εκτός");$("result").textContent=finished(current)?"Τελικό "+current.r:"Χωρίς τελικό σκορ";$("turnover").textContent=money(current.v);const rankBand=band(current.rank);$("turnHint").textContent=current.rank===null?"Χωρίς τιμή τζίρου":"Στάδιο "+rankBand+"/4 · "+nf(current.rank,1)+"ο εκατοστημόριο · "+current.leagueN+" ματς λίγκας";color("turnBox",rankBand,"turn");$("favPercent").textContent=per(current.p);color("favBox",pband(current.p,"fav"),"fav");const cp=current.contra!==null?current.contra:(current.p===null?null:100-current.p);$("contraPercent").textContent=per(cp);color("contraBox",pband(cp,"contra"),"contra");$("sofa").textContent=per(current.s);color("sofaBox",pband(current.s,"sofa"),"sofa");for(let k of ["o","m","l","co","cm","cl"])$(k).textContent=price(current[k]);renderHistory();renderArchive()}
const change=(a,b)=>a!==null&&b!==null&&a>0?(b/a-1)*100:null;
// Every comparison uses all shared available market signals; never make up missing
// 90-minute or contra odds. Require a candidate to provide all signals the target has.
const signalSpecs=[
  {key:"openFav", fn:x=>x.o, tol:.19, weight:2.1},
  {key:"currentFav", fn:x=>x.l, tol:.21, weight:2.1},
  {key:"favMove", fn:x=>change(x.o,x.l), tol:13, weight:1.6},
  {key:"favMoney", fn:x=>x.p, tol:11, weight:1.8},
  {key:"sofa", fn:x=>x.s, tol:18, weight:1.1},
  {key:"relativeTurnover", fn:x=>x.rank, tol:29, weight:1.5},
  {key:"earlyFavMoney", fn:x=>x.p0, tol:14, weight:.9},
  {key:"openContra", fn:x=>x.co, tol:.30, weight:1.1},
  {key:"currentContra", fn:x=>x.cl, tol:.31, weight:1.1},
  {key:"contraMove", fn:x=>change(x.co,x.cl), tol:15, weight:1.1},
  {key:"favOpenTo90", fn:x=>change(x.o,x.m), tol:8, weight:1.3},
  {key:"fav90ToNow", fn:x=>change(x.m,x.l), tol:8, weight:1.3},
  {key:"contraOpenTo90", fn:x=>change(x.co,x.cm), tol:11, weight:1.0},
  {key:"contra90ToNow", fn:x=>change(x.cm,x.cl), tol:11, weight:1.0}
];
const usable=v=>v!==null&&Number.isFinite(v);
function similarity(t,h){
  if(!["o","l","p","rank"].every(k=>usable(t[k])&&usable(h[k])))return null;
  const multiplier={strict:1,medium:1.7,wide:2.8}[mode];
  let weighted=0,totalWeight=0,features=0;
  for(const spec of signalSpecs){
    const a=spec.fn(t); if(!usable(a))continue;
    const b=spec.fn(h); if(!usable(b))return null;
    const diff=Math.abs(a-b);
    if(diff>spec.tol*multiplier)return null;
    weighted+=(diff/spec.tol)*spec.weight;
    totalWeight+=spec.weight;
    features++;
  }
  if(features<4||!totalWeight)return null;
  const distance=weighted/totalWeight;
  return {distance,similarity:Math.round(100*Math.exp(-.24*distance)),features};
}
function rate(list){let n=list.length;if(!n)return {text:"—",sub:"Κανένα κοντινό ματς"};let wins=list.filter(x=>won(x)===true).length;return {text:wins+"/"+n,sub:"Νίκες φαβορί "+nf(wins/n*100,0)+"% · Κόντρα "+(n-wins)+"/"+n}}
function renderHistory(){
  if(!current)return;
  const essential=["o","l","p","rank"];
  const missing=essential.filter(k=>!usable(current[k]));
  let found=[];
  if(!missing.length){
    found=matches.filter(x=>x.id!==current.id&&finished(x)&&leaguesSelected.includes(x.lg))
      .map(x=>{const s=similarity(current,x);return s?{...x,...s}:null})
      .filter(Boolean).sort((a,b)=>a.distance-b.distance);
  }
  history={all:found,side:found.filter(x=>x.f===current.f)};
  const no90=!usable(current.m),noContra=!usable(current.co)||!usable(current.cl);
  const preliminary=no90||noContra;
  const caveat=preliminary?" Προσωρινή σύγκριση: λείπουν "+[no90?"αποδόσεις 90′":null,noContra?"αποδόσεις κόντρας":null].filter(Boolean).join(" και ")+". Δεν συγκρίνονται τα στάδια που λείπουν.":" Συγκρίθηκαν όλα τα διαθέσιμα χρονικά στάδια.";
  if(missing.length)$("insight").textContent="Για ιστορική σύγκριση χρειάζονται τουλάχιστον αρχική/τωρινή απόδοση φαβορί, ποσοστό φαβορί και τζίρος.";
  else if(!found.length)$("insight").textContent="Δεν βρέθηκαν αγώνες που να ταιριάζουν σε όλα τα διαθέσιμα κριτήρια. Δοκίμασε «Λίγο πιο ανοιχτά»."+caveat;
  else $("insight").textContent="Βρέθηκαν "+found.length+" ιστορικά ματς στα επιλεγμένα πρωταθλήματα."+caveat+(found.length<10?" Μικρό δείγμα: τα ποσοστά δεν είναι αξιόπιστη πρόβλεψη.":" Τα αποτελέσματα είναι ιστορικές συχνότητες, όχι πιθανότητες.");
  const a=rate(history.all),b=rate(history.side);
  $("allWins").textContent=a.text;$("allN").textContent=a.sub;
  $("sideWins").textContent=b.text;$("sideN").textContent=b.sub;
  $("sideTitle").textContent="Φαβορί "+(current.f==="H"?"εντός":"εκτός");
  $("sideSubtitle").textContent="Ίδια έδρα με τον αγώνα";
  if(!$("historyDetails").classList.contains("hide"))paintHistory();
}
function paintHistory(){
 const x=history[historyTab]||[];
 const heading=x.length>40?'<p class="tiny" style="padding:8px 0">Τα 40 πιο κοντινά από '+x.length+' · οι συνολικές συχνότητες μετρούν όλα τα ματς</p>':"";
 $("historyRows").innerHTML=x.length?heading+x.slice(0,40).map(z=>
 '<div class="histrow"><div><b>'+safe(name(z))+'</b><small>'+safe(z.lg)+' · Δείκτης ομοιότητας '+z.similarity+'/100 · '+z.features+' στοιχεία · '+(z.f==="H"?"Φαβορί εντός":"Φαβορί εκτός")+'</small></div><div style="text-align:right;white-space:nowrap"><b class="'+(won(z)?"good":"bad")+'">'+safe(z.r)+'</b><small>'+(won(z)?"Φαβορί":"Κόντρα +0,5")+'</small></div></div>'
 ).join(""):'<div class="empty">Δεν υπάρχουν παρόμοιοι αγώνες σε αυτή την αναζήτηση.</div>';
}
function opinion(){if(!current)return;let a=history.all,s=history.side,wins=a.filter(x=>won(x)).length,sideWins=s.filter(x=>won(x)).length,pick="Αποχή",reason;if(a.length<8||s.length<5){reason="Τα κοντινά ιστορικά παιχνίδια είναι λίγα ("+a.length+" συνολικά, "+s.length+" ίδιας έδρας). Θα προτιμούσα αποχή."}else{let share=(wins/a.length+sideWins/s.length)/2,market=current.l?1/current.l:null,contra=current.cl?1/current.cl:null;if(share>=.68&&market!==null&&share>market+.08){pick="Νίκη φαβορί";reason="Το ιστορικό δείχνει περισσότερες νίκες φαβορί, αλλά η σύγκριση δεν δίνει πιστοποιημένη πιθανότητα."}else if(share<=.38&&contra!==null&&1-share>contra+.08){pick="Κόντρα +0,5";reason="Στα κοντινά ιστορικά δείγματα το φαβορί δεν κέρδιζε συχνά. Παραμένει περιορισμένο δείγμα."}else reason="Δεν προκύπτει αρκετά καθαρό πλεονέκτημα έναντι των αποδόσεων. Θα προτιμούσα αποχή."}
lastOpinion={key:key(current),match:name(current),pick,reason,created:new Date().toISOString(),id:current.id,odds:pick==="Νίκη φαβορί"?current.l:pick==="Κόντρα +0,5"?current.cl:null,historyAll:a.length,historySide:s.length};$("opinionText").textContent="Εκτίμηση: "+pick+". "+reason;$("opinionText").classList.remove("hide")}
function renderArchive(){let entries=journal.map(j=>{let x=matches.find(m=>key(m)===j.key&&finished(m));let txt=x?(j.pick==="Αποχή"?"Αποχή":j.pick==="Νίκη φαβορί"?(won(x)?"Επαληθεύτηκε":"Δεν επαληθεύτηκε"):(!won(x)?"Επαληθεύτηκε":"Δεν επαληθεύτηκε")):"Αναμονή σκορ";return '<div class="histrow"><div><b>'+safe(j.match)+'</b><small>'+safe(j.pick)+" · "+safe(new Date(j.created).toLocaleString("el-GR"))+'</small></div><div class="tiny">'+safe(txt)+'</div></div>'});$("archiveRows").innerHTML=entries.join("")||"Δεν υπάρχουν αποθηκευμένες εκτιμήσεις."}
async function getJSON(url,opt){let r=await fetch(url,{credentials:"same-origin",cache:"no-store",...opt});let d=await r.json();if(r.status===401&&url!=="/api/login"){$("app").classList.add("hide");$("login").classList.remove("hide");throw Error("Χρειάζεται σύνδεση.")}return d}
async function refresh(){let status=$("feedStatus");status.textContent="Ενημέρωση…";status.className="status";try{let d=await getJSON("/api/matches");if(!d.ok){matches=[];current=null;listMatches();status.textContent=d.state==="not_connected"?"Αναμονή σύνδεσης Excel":"Σφάλμα ενημέρωσης";status.className="status warn";$("matchTitle").textContent="Περιμένουμε τη σύνδεση με το Excel";$("insight").textContent="Η εφαρμογή ανέβηκε online, αλλά δεν έχει συνδεθεί ακόμη η ασφαλής ανάγνωση του Google Sheet.";return}let selectedKey=current?key(current):null;matches=d.rows.map((r,i)=>parseRow(r,i)).filter(x=>x.lg&&x.h&&x.a&&["H","A"].includes(x.f));setupRanks();setupLeagues();fillLeagueFilter();status.textContent=d.stale?"Παλαιότερα δεδομένα":"Excel συνδεδεμένο";status.className=d.stale?"status warn":"status live";$("updatedAt").textContent="Ανάκτηση: "+new Date(d.serverFetchedAt||Date.now()).toLocaleString("el-GR");current=matches.find(x=>key(x)===selectedKey)||matches.filter(x=>!finished(x)).slice(-1)[0]||matches.slice(-1)[0]||null;if(current)render();else $("matchTitle").textContent="Δεν υπάρχουν αγώνες στο Excel";listMatches()}catch(e){status.textContent="Αδυναμία σύνδεσης";status.className="status warn";$("insight").textContent="Δεν ήταν διαθέσιμα τα δεδομένα. Δοκίμασε ξανά αργότερα."}}
async function boot(){try{let d=await getJSON("/api/session");if(d.authenticated){$("login").classList.add("hide");$("app").classList.remove("hide");await refresh()}else{$("login").classList.remove("hide")}}catch(e){$("login").classList.remove("hide")}}
$("loginForm").addEventListener("submit",async e=>{e.preventDefault();$("loginError").textContent="Σύνδεση…";try{let d=await getJSON("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:$("password").value})});if(!d.ok){$("loginError").textContent=d.error==="not_configured"?"Η πρόσβαση δεν έχει ενεργοποιηθεί ακόμα.":d.error==="too_many_attempts"?"Πολλές προσπάθειες. Δοκίμασε σε 10 λεπτά.":"Λάθος κωδικός.";return}$("password").value="";$("loginError").textContent="";$("login").classList.add("hide");$("app").classList.remove("hide");await refresh()}catch(e){$("loginError").textContent="Δεν ήταν δυνατή η σύνδεση."}});
$("logout").addEventListener("click",async()=>{await fetch("/api/logout",{method:"POST",credentials:"same-origin"});$("app").classList.add("hide");$("login").classList.remove("hide")});
$("reload").addEventListener("click",refresh);$("search").addEventListener("input",listMatches);$("leagueFilter").addEventListener("change",listMatches);
document.querySelectorAll("[data-tab]").forEach(b=>b.addEventListener("click",()=>{tab=b.dataset.tab;document.querySelectorAll("[data-tab]").forEach(z=>z.classList.toggle("active",z===b));listMatches()}));
document.querySelectorAll("[data-mode]").forEach(b=>b.addEventListener("click",()=>{mode=b.dataset.mode;document.querySelectorAll("[data-mode]").forEach(z=>z.setAttribute("aria-pressed",String(z===b)));renderHistory()}));
$("settingsToggle").addEventListener("click",()=>$("settings").classList.toggle("hide"));
document.querySelectorAll("[data-preset]").forEach(b=>b.addEventListener("click",()=>{let all=allLeagues();leaguesSelected=b.dataset.preset==="all"?all:b.dataset.preset==="none"?[]:all.filter(x=>!excluded.test(x));savedLeagues=leaguesSelected;store("sv_live_leagues",savedLeagues);paintSettings();renderHistory()}));
$("viewHistory").addEventListener("click",()=>{$("historyDetails").classList.toggle("hide");$("viewHistory").textContent=$("historyDetails").classList.contains("hide")?"Δες ματς & σκορ ▾":"Κρύψε τα ματς ▴";paintHistory()});
document.querySelectorAll("[data-history]").forEach(b=>b.addEventListener("click",()=>{historyTab=b.dataset.history;document.querySelectorAll("[data-history]").forEach(z=>z.classList.toggle("active",z===b));paintHistory()}));
$("opinion").addEventListener("click",opinion);
$("archiveToggle").addEventListener("click",()=>$("archive").classList.toggle("hide"));
$("saveOpinion").addEventListener("click",()=>{if(!current||finished(current)){alert("Δεν αποθηκεύουμε εκτίμηση αφού βγει τελικό σκορ.");return}if(!lastOpinion||lastOpinion.key!==key(current)){alert("Πάτησε πρώτα «Εσύ τι θα επέλεγες;»");return}journal=[lastOpinion,...journal].slice(0,250);store("sv_live_journal",journal);renderArchive();alert("Αποθηκεύτηκε στη συσκευή.")});
boot();
setInterval(()=>{if(!$("app").classList.contains("hide"))refresh()},600000);
