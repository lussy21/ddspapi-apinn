/**
 * MATCH ALERTS PRIVATE BACKEND
 * Standalone Google Apps Script.
 *
 * Safety:
 * - PINNACLE is READ ONLY.
 * - Accounts/config live only in Script Properties.
 * - Passwords are never stored as plain text.
 * - Email must be verified before a user becomes active.
 * - Free-seat limit is configurable from Admin.
 */

const SPREADSHEET_ID = "1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM";
const SHEET_NAME = "PINNACLE";
const APP_ORIGIN = "https://match-alerts-private.onrender.com";

// IMPORTANT: replace ONLY in your private Apps Script before deployment.
const ADMIN_CODE = "CHANGE_THIS_IN_APPS_SCRIPT";

const DEFAULT_MAX_FREE_USERS = 2;
const SESSION_HOURS = 24 * 30;       // 30 days
const VERIFY_MINUTES = 15;
const PASSWORD_ROUNDS = 5000;

function doGet(e) {
  const p = e && e.parameter ? e.parameter : {};
  const action = String(p.action || "status");

  try {
    if (action === "status") {
      return json_({ok:true, service:"match-alerts-private"});
    }
    return json_({ok:false,error:"POST_REQUIRED"});
  } catch (err) {
    return json_({ok:false,error:"SERVER_ERROR"});
  }
}

function doPost(e) {
  const p = e && e.parameter ? e.parameter : {};
  const action = String(p.action || "");
  let payload;

  try {
    if (action === "register") payload = register_(p);
    else if (action === "verify") payload = verify_(p);
    else if (action === "resend") payload = resend_(p);
    else if (action === "login") payload = login_(p);
    else if (action === "logout") payload = logout_(p);
    else if (action === "alerts") payload = alerts_(p);
    else if (action === "playedAdd") payload = playedAdd_(p);
    else if (action === "playedHistory") payload = playedHistory_(p);
    else if (action === "pushSubscribe") payload = pushSubscribe_(p);
    else if (action === "memberMessages") payload = memberMessages_(p);
    else if (action === "memberMessageRead") payload = memberMessageRead_(p);
    else if (action === "adminMessageCreate") payload = adminMessageCreate_(p);
    else if (action === "adminPushTargets") payload = adminPushTargets_(p);
    else if (action === "adminPushDelete") payload = adminPushDelete_(p);
    else if (action === "adminAutomationSetup") payload = adminAutomationSetup_(p);
    else if (action === "automationPushTargets") payload = automationPushTargets_(p);
    else if (action === "automationPushDelete") payload = automationPushDelete_(p);
    else if (action === "supportSend") payload = supportSend_(p);
    else if (action === "adminSupport") payload = adminSupport_(p);
    else if (action === "adminSupportClose") payload = adminSupportClose_(p);
    else if (action === "adminSettings") payload = adminSettings_(p);
    else if (action === "adminUsers") payload = adminUsers_(p);
    else if (action === "adminPlayedHistory") payload = adminPlayedHistory_(p);
    else if (action === "adminSignals") payload = adminSignals_(p);
    else if (action === "adminSetMaxUsers") payload = adminSetMaxUsers_(p);
    else if (action === "adminAddDays") payload = adminAddDays_(p);
    else if (action === "adminAddDaysAll") payload = adminAddDaysAll_(p);
    else if (action === "adminRevoke") payload = adminRevoke_(p);
    else if (action === "adminRestore") payload = adminRestore_(p);
    else if (action === "adminDelete") payload = adminDelete_(p);
    else payload = {ok:false,error:"UNKNOWN_ACTION"};
  } catch (err) {
    if (action === "alerts") {
      const message = String(err && err.message ? err.message : err || "");
      let stage = "ALERTS_UNKNOWN";
      if (/openById|Spreadsheet|permission|access/i.test(message)) stage = "ALERTS_SHEET_OPEN";
      else if (/getSheetByName/i.test(message)) stage = "ALERTS_SHEET_LOOKUP";
      else if (/getRange|getDisplayValues|range/i.test(message)) stage = "ALERTS_SHEET_READ";
      else if (/normalizeAlertName|alertRating/i.test(message)) stage = "ALERTS_PROCESSING";
      payload = {ok:false,error:stage};
    } else {
      payload = {ok:false,error:"SERVER_ERROR"};
    }
  }

  if (String(p.bridge || "") === "1") return bridge_(payload, p.requestId);
  return json_(payload);
}

function register_(p) {
  cleanupPending_();

  const username = normalizeUsername_(p.username);
  const email = normalizeEmail_(p.email);
  const password = String(p.password || "");

  if (!validUsername_(username)) return {ok:false,error:"BAD_USERNAME"};
  if (!validEmail_(email)) return {ok:false,error:"BAD_EMAIL"};
  if (password.length < 8) return {ok:false,error:"PASSWORD_TOO_SHORT"};

  const props = PropertiesService.getScriptProperties();

  if (props.getProperty(userKey_(username))) {
    return {ok:false,error:"USER_EXISTS"};
  }
  if (findUserByEmail_(email)) {
    return {ok:false,error:"EMAIL_EXISTS"};
  }

  if (countActiveUsers_() >= getMaxFreeUsers_()) {
    return {ok:false,error:"REGISTRATION_FULL"};
  }

  // We do not consume a seat until email verification succeeds.
  const salt = Utilities.getUuid();
  const code = verificationCode_();
  const record = {
    username: username,
    email: email,
    salt: salt,
    hash: hashPassword_(password, salt),
    verified: false,
    revoked: false,
    createdAt: new Date().toISOString(),
    verifyHash: hashVerification_(code, email),
    verifyExpiresAt: Date.now() + VERIFY_MINUTES * 60 * 1000
  };

  props.setProperty(userKey_(username), JSON.stringify(record));
  sendVerificationEmail_(email, username, code);

  return {
    ok:true,
    status:"EMAIL_VERIFICATION_REQUIRED",
    username:username,
    emailMasked:maskEmail_(email),
    expiresMinutes:VERIFY_MINUTES
  };
}

function verify_(p) {
  cleanupPending_();

  const username = normalizeUsername_(p.username);
  const code = String(p.code || "").trim();
  if (!/^\d{6}$/.test(code)) return {ok:false,error:"BAD_CODE"};

  const props = PropertiesService.getScriptProperties();
  const key = userKey_(username);
  const raw = props.getProperty(key);
  if (!raw) return {ok:false,error:"USER_NOT_FOUND"};

  const u = JSON.parse(raw);
  if (u.verified) return {ok:true,status:"ACTIVE"};
  if (!u.verifyExpiresAt || Date.now() > Number(u.verifyExpiresAt)) {
    return {ok:false,error:"CODE_EXPIRED"};
  }
  if (hashVerification_(code, u.email) !== u.verifyHash) {
    return {ok:false,error:"INVALID_CODE"};
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const active = countActiveUsers_();
    const max = getMaxFreeUsers_();
    if (active >= max) {
      return {ok:false,error:"REGISTRATION_FULL"};
    }

    u.verified = true;
    u.verifiedAt = new Date().toISOString();
    delete u.verifyHash;
    delete u.verifyExpiresAt;
    props.setProperty(key, JSON.stringify(u));

    return {
      ok:true,
      status:"ACTIVE",
      remainingFreeSlots:Math.max(0,max-countActiveUsers_())
    };
  } finally {
    lock.releaseLock();
  }
}

function resend_(p) {
  cleanupPending_();

  const username = normalizeUsername_(p.username);
  const props = PropertiesService.getScriptProperties();
  const key = userKey_(username);
  const raw = props.getProperty(key);
  if (!raw) return {ok:false,error:"USER_NOT_FOUND"};

  const u = JSON.parse(raw);
  if (u.verified) return {ok:false,error:"ALREADY_VERIFIED"};

  const code = verificationCode_();
  u.verifyHash = hashVerification_(code, u.email);
  u.verifyExpiresAt = Date.now() + VERIFY_MINUTES * 60 * 1000;
  props.setProperty(key, JSON.stringify(u));
  sendVerificationEmail_(u.email, u.username, code);

  return {
    ok:true,
    status:"CODE_RESENT",
    emailMasked:maskEmail_(u.email),
    expiresMinutes:VERIFY_MINUTES
  };
}

function login_(p) {
  const username = normalizeUsername_(p.username);
  const password = String(p.password || "");

  const props = PropertiesService.getScriptProperties();
  const raw = props.getProperty(userKey_(username));
  if (!raw) return {ok:false,error:"INVALID_LOGIN"};

  const u = JSON.parse(raw);
  if (!u.verified) return {ok:false,error:"EMAIL_NOT_VERIFIED"};
  if (u.revoked) return {ok:false,error:"ACCESS_REVOKED"};
  if (subscriptionExpired_(u)) return {ok:false,error:"SUBSCRIPTION_EXPIRED"};

  if (hashPassword_(password, u.salt) !== u.hash) {
    return {ok:false,error:"INVALID_LOGIN"};
  }

  const token = makeToken_();
  const expiresAt = Date.now() + SESSION_HOURS * 60 * 60 * 1000;

  props.setProperty(sessionKey_(token), JSON.stringify({
    username:username,
    expiresAt:expiresAt
  }));

  return {
    ok:true,
    token:token,
    username:username,
    expiresAt:new Date(expiresAt).toISOString(),
    subscriptionEndsAt:u.subscriptionEndsAt || ""
  };
}

function logout_(p) {
  const token = String(p.token || "");
  if (token) PropertiesService.getScriptProperties().deleteProperty(sessionKey_(token));
  return {ok:true};
}

function alerts_(p) {
  const auth = requireSession_(String(p.token || ""));
  if (!auth.ok) return auth;

  // READ ONLY. For the first live bridge we return only what the app needs:
  // active alerts from PINNACLE column O. No historical/statistical rescans here.
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const pin = ss.getSheetByName(SHEET_NAME);
  if (!pin) return {ok:false,error:"SHEET_READ_FAILED"};

  const pinLast = pin.getLastRow();
  if (pinLast < 3) {
    return {
      ok:true,
      live:true,
      count:0,
      alerts:[],
      username:auth.username,
      subscriptionEndsAt:auth.subscriptionEndsAt || "",
      updatedAt:new Date().toISOString()
    };
  }

  const pinRows = pin.getRange(3, 1, pinLast - 2, 16).getDisplayValues();
  // BY is a hidden, app-only kickoff field written by the core in Greece time.
  const kickoffRows = pin.getRange(3, 77, pinLast - 2, 1).getDisplayValues();
  const out = [];

  pinRows.forEach(function(row, idx) {
    const league = String(row[0] || "").trim();
    const home = String(row[1] || "").trim();
    const away = String(row[2] || "").trim();
    const favoriteSide = String(row[3] || "").trim();
    const rawAlert = String(row[14] || "").trim();
    const currentAlert = normalizeAlertName_(rawAlert);
    const result = String(row[15] || "").trim();

    if (!league || !home || !away || !currentAlert || result) return;

    const records = alertRecords_(pinRows, league, currentAlert);
    const kickoff = String((kickoffRows[idx] && kickoffRows[idx][0]) || "").trim();
    const selectionId = selectionId_(league, home, away, currentAlert, kickoff);
    out.push({
      league:league,
      home:home,
      away:away,
      favoriteSide:favoriteSide,
      alert:currentAlert,
      rating:alertRating_(rawAlert),
      leagueRecord:records.leagueRecord,
      allStatsRecord:records.allStatsRecord,
      kickoff:kickoff,
      selectionId:selectionId,
      played:!!PropertiesService.getScriptProperties().getProperty(playedKey_(auth.username, selectionId))
    });
  });

  return {
    ok:true,
    live:true,
    count:out.length,
    alerts:out,
    username:auth.username,
    subscriptionEndsAt:auth.subscriptionEndsAt || "",
    updatedAt:new Date().toISOString()
  };
}


function selectionId_(league, home, away, alertName, kickoff) {
  const raw = [
    String(league || "").trim(),
    String(home || "").trim(),
    String(away || "").trim(),
    String(alertName || "").trim(),
    String(kickoff || "").trim()
  ].join("|");
  const digest = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    raw,
    Utilities.Charset.UTF_8
  );
  return Utilities.base64EncodeWebSafe(digest).replace(/=+$/g, "").slice(0, 22);
}

function playedKey_(username, selectionId) {
  return "PLAYED::" + normalizeUsername_(username) + "::" + String(selectionId || "");
}

function playedAdd_(p) {
  const auth = requireSession_(String(p.token || ""));
  if (!auth.ok) return auth;

  const wantedId = String(p.selectionId || "").trim();
  if (!wantedId) return {ok:false,error:"BAD_SELECTION"};

  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const pin = ss.getSheetByName(SHEET_NAME);
  if (!pin) return {ok:false,error:"SHEET_READ_FAILED"};

  const pinLast = pin.getLastRow();
  if (pinLast < 3) return {ok:false,error:"SELECTION_NOT_ACTIVE"};

  const pinRows = pin.getRange(3, 1, pinLast - 2, 16).getDisplayValues();
  const kickoffRows = pin.getRange(3, 77, pinLast - 2, 1).getDisplayValues();
  let selected = null;

  for (let idx = 0; idx < pinRows.length; idx++) {
    const row = pinRows[idx];
    const league = String(row[0] || "").trim();
    const home = String(row[1] || "").trim();
    const away = String(row[2] || "").trim();
    const favoriteSide = String(row[3] || "").trim();
    const currentAlert = normalizeAlertName_(row[14]);
    const result = String(row[15] || "").trim();
    const kickoff = String((kickoffRows[idx] && kickoffRows[idx][0]) || "").trim();

    if (!league || !home || !away || !currentAlert || result) continue;
    const id = selectionId_(league, home, away, currentAlert, kickoff);
    if (id !== wantedId) continue;

    selected = {
      id:id,
      username:auth.username,
      league:league,
      home:home,
      away:away,
      favoriteSide:favoriteSide,
      alert:currentAlert,
      kickoff:kickoff,
      createdAt:new Date().toISOString()
    };
    break;
  }

  if (!selected) return {ok:false,error:"SELECTION_NOT_ACTIVE"};

  const props = PropertiesService.getScriptProperties();
  const key = playedKey_(auth.username, selected.id);
  if (!props.getProperty(key)) props.setProperty(key, JSON.stringify(selected));

  return {ok:true,id:selected.id};
}

function playedHistory_(p) {
  const auth = requireSession_(String(p.token || ""));
  if (!auth.ok) return auth;

  const props = PropertiesService.getScriptProperties();
  const prefix = "PLAYED::" + normalizeUsername_(auth.username) + "::";
  const allProps = props.getProperties();
  const saved = [];

  Object.keys(allProps).forEach(function(key) {
    if (key.indexOf(prefix) !== 0) return;
    try {
      const item = JSON.parse(allProps[key]);
      if (item && item.id) saved.push(item);
    } catch (_) {}
  });

  if (!saved.length) {
    return {ok:true,items:[],count:0,username:auth.username};
  }

  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const pin = ss.getSheetByName(SHEET_NAME);
  if (!pin) return {ok:false,error:"SHEET_READ_FAILED"};

  const pinLast = pin.getLastRow();
  const pinRows = pinLast >= 3 ? pin.getRange(3, 1, pinLast - 2, 16).getDisplayValues() : [];
  const kickoffRows = pinLast >= 3 ? pin.getRange(3, 77, pinLast - 2, 1).getDisplayValues() : [];

  const rowById = {};
  pinRows.forEach(function(row, idx) {
    const league = String(row[0] || "").trim();
    const home = String(row[1] || "").trim();
    const away = String(row[2] || "").trim();
    const currentAlert = normalizeAlertName_(row[14]);
    const kickoff = String((kickoffRows[idx] && kickoffRows[idx][0]) || "").trim();
    if (!league || !home || !away || !currentAlert) return;
    rowById[selectionId_(league, home, away, currentAlert, kickoff)] = row;
  });

  const items = saved.map(function(item) {
    const row = rowById[item.id] || null;
    let score = "";
    let status = "pending";

    if (row) {
      const parsed = resultScore_(row[15]);
      const won = alertSuccess_(row, item.alert);
      if (parsed) score = parsed[0] + "-" + parsed[1];
      if (won === true) status = "win";
      else if (won === false) status = "loss";
    }

    return {
      id:item.id,
      league:item.league,
      home:item.home,
      away:item.away,
      favoriteSide:item.favoriteSide,
      alert:item.alert,
      kickoff:item.kickoff,
      createdAt:item.createdAt,
      score:score,
      status:status
    };
  });

  items.sort(function(a,b) {
    const ta = Date.parse(a.kickoff || a.createdAt || "") || 0;
    const tb = Date.parse(b.kickoff || b.createdAt || "") || 0;
    return tb - ta;
  });

  return {ok:true,items:items.slice(0,250),count:items.length,username:auth.username};
}

function normalizeAlertName_(value) {
  const text = String(value || "").trim();
  const marker = " · ";
  if (text.indexOf(marker) >= 0) {
    const parts = text.split(marker);
    if (parts.length > 1 && parts[1].indexOf("/10") >= 0) return parts[0].trim();
  }
  return text;
}

function alertRating_(value) {
  const text = String(value || "").trim();
  const m = text.match(/·\s*([0-9]+(?:[.,][0-9]+)?\/10)\s*$/);
  return m ? m[1] : "";
}

function resultScore_(value) {
  const m = String(value || "").trim().match(/^(\d+)\s*-\s*(\d+)/);
  if (!m) return null;
  return [Number(m[1]), Number(m[2])];
}

function alertSuccess_(row, alertName) {
  const side = String(row[3] || "").trim().toUpperCase();
  const score = resultScore_(row[15]);
  if (!score || (side !== "H" && side !== "A")) return null;

  const favoriteWon = side === "H" ? score[0] > score[1] : score[1] > score[0];
  const alert = String(alertName || "").toUpperCase();

  if (alert.indexOf("ΚΟΝΤΡΑ") >= 0) return !favoriteWon;
  if (
    alert.indexOf("ΦΑΒ") >= 0 ||
    alert.indexOf("ΤΖΙΡΟΣ") >= 0
  ) return favoriteWon;

  return null;
}

function alertRecords_(rows, league, alertName) {
  let leagueWins = 0;
  let leagueTotal = 0;
  let allWins = 0;
  let allTotal = 0;

  rows.forEach(function(row) {
    const rowAlert = normalizeAlertName_(row[14]);
    if (rowAlert !== alertName) return;

    const success = alertSuccess_(row, alertName);
    if (success === null) return;

    allTotal++;
    if (success) allWins++;

    if (String(row[0] || "").trim() === league) {
      leagueTotal++;
      if (success) leagueWins++;
    }
  });

  return {
    leagueRecord:String(leagueWins) + "/" + String(leagueTotal),
    allStatsRecord:String(allWins) + "/" + String(allTotal)
  };
}



function messageKey_(id) {
  return "MESSAGE::" + String(id || "");
}

function messageReadKey_(username, id) {
  return "MESSAGE_READ::" + normalizeUsername_(username) + "::" + String(id || "");
}

function adminMessageCreate_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};

  const title = String(p.title || "").trim();
  const body = String(p.body || "").trim();
  if (!title || !body || title.length > 80 || body.length > 220) {
    return {ok:false,error:"BAD_MESSAGE"};
  }

  const now = new Date();
  const id = String(now.getTime()) + "-" + Utilities.getUuid().replace(/-/g,"").slice(0,10);
  const item = {
    id:id,
    title:title,
    body:body,
    createdAt:now.toISOString()
  };

  const props = PropertiesService.getScriptProperties();
  props.setProperty(messageKey_(id), JSON.stringify(item));
  cleanupMessages_();

  return {ok:true,message:item};
}

function memberMessages_(p) {
  const auth = requireSession_(String(p.token || ""));
  if (!auth.ok) return auth;

  const props = PropertiesService.getScriptProperties();
  const all = props.getProperties();
  const items = [];

  Object.keys(all).forEach(function(key) {
    if (key.indexOf("MESSAGE::") !== 0) return;
    try {
      const item = JSON.parse(all[key]);
      if (item && item.id && item.title && item.body) items.push(item);
    } catch (_) {}
  });

  items.sort(function(a,b) {
    return String(b.createdAt || "").localeCompare(String(a.createdAt || ""));
  });

  const latest = items.slice(0,10).map(function(item) {
    return {
      id:item.id,
      title:item.title,
      body:item.body,
      createdAt:item.createdAt,
      read:!!props.getProperty(messageReadKey_(auth.username, item.id))
    };
  });

  let unreadCount = 0;
  latest.forEach(function(item){ if (!item.read) unreadCount++; });

  return {
    ok:true,
    messages:latest,
    count:latest.length,
    unreadCount:unreadCount
  };
}

function memberMessageRead_(p) {
  const auth = requireSession_(String(p.token || ""));
  if (!auth.ok) return auth;

  const id = String(p.id || "").trim();
  if (!id) return {ok:false,error:"BAD_MESSAGE"};
  const props = PropertiesService.getScriptProperties();
  if (!props.getProperty(messageKey_(id))) return {ok:false,error:"MESSAGE_NOT_FOUND"};

  props.setProperty(messageReadKey_(auth.username, id), new Date().toISOString());
  return {ok:true,id:id};
}

function cleanupMessages_() {
  const props = PropertiesService.getScriptProperties();
  const all = props.getProperties();
  const items = [];

  Object.keys(all).forEach(function(key) {
    if (key.indexOf("MESSAGE::") !== 0) return;
    try {
      const item = JSON.parse(all[key]);
      if (item && item.id) items.push({key:key,id:item.id,createdAt:String(item.createdAt || "")});
      else props.deleteProperty(key);
    } catch (_) {
      props.deleteProperty(key);
    }
  });

  items.sort(function(a,b){ return b.createdAt.localeCompare(a.createdAt); });
  const removed = items.slice(10);
  if (!removed.length) return;

  const removedIds = {};
  removed.forEach(function(item) {
    removedIds[item.id] = true;
    props.deleteProperty(item.key);
  });

  const after = props.getProperties();
  Object.keys(after).forEach(function(key) {
    if (key.indexOf("MESSAGE_READ::") !== 0) return;
    const parts = key.split("::");
    const id = parts.length >= 3 ? parts[parts.length - 1] : "";
    if (removedIds[id]) props.deleteProperty(key);
  });
}

function pushKey_(username, endpoint) {
  const digest = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    String(endpoint || ""),
    Utilities.Charset.UTF_8
  );
  const id = Utilities.base64EncodeWebSafe(digest).replace(/=+$/g,"").slice(0,24);
  return "PUSH::" + normalizeUsername_(username) + "::" + id;
}

function pushSubscribe_(p) {
  const auth = requireSession_(String(p.token || ""));
  if (!auth.ok) return auth;

  const endpoint = String(p.endpoint || "").trim();
  const p256dh = String(p.p256dh || "").trim();
  const authKey = String(p.auth || "").trim();

  if (!/^https:\/\//i.test(endpoint) || endpoint.length > 1800) return {ok:false,error:"BAD_PUSH_SUBSCRIPTION"};
  if (!p256dh || !authKey || p256dh.length > 400 || authKey.length > 200) return {ok:false,error:"BAD_PUSH_SUBSCRIPTION"};

  const props = PropertiesService.getScriptProperties();
  const key = pushKey_(auth.username, endpoint);
  const previous = props.getProperty(key);
  let createdAt = new Date().toISOString();
  if (previous) {
    try {
      const old = JSON.parse(previous);
      if (old && old.createdAt) createdAt = old.createdAt;
    } catch (_) {}
  }

  props.setProperty(key, JSON.stringify({
    username:auth.username,
    endpoint:endpoint,
    keys:{p256dh:p256dh,auth:authKey},
    createdAt:createdAt,
    updatedAt:new Date().toISOString()
  }));

  cleanupPush_();
  return {ok:true};
}

function adminPushTargets_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};
  const props = PropertiesService.getScriptProperties().getProperties();
  const targets = [];

  Object.keys(props).forEach(function(key) {
    if (key.indexOf("PUSH::") !== 0) return;
    try {
      const item = JSON.parse(props[key]);
      if (item && item.endpoint && item.keys && item.keys.p256dh && item.keys.auth) {
        targets.push({
          key:key,
          username:item.username || "",
          endpoint:item.endpoint,
          keys:{p256dh:item.keys.p256dh,auth:item.keys.auth}
        });
      }
    } catch (_) {}
  });

  return {ok:true,count:targets.length,targets:targets};
}

function adminPushDelete_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};
  const key = String(p.key || "");
  if (key.indexOf("PUSH::") !== 0) return {ok:false,error:"BAD_PUSH_KEY"};
  PropertiesService.getScriptProperties().deleteProperty(key);
  return {ok:true};
}

function adminAutomationSetup_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};

  const secret = String(p.secret || "").trim();
  if (secret.length < 32 || secret.length > 256) {
    return {ok:false,error:"BAD_AUTOMATION_SECRET"};
  }

  PropertiesService.getScriptProperties()
    .setProperty("CONFIG::AUTO_PUSH_SECRET", secret);

  return {ok:true,configured:true};
}

function automationAuthorized_(secretRaw) {
  const wanted = PropertiesService.getScriptProperties()
    .getProperty("CONFIG::AUTO_PUSH_SECRET");
  const got = String(secretRaw || "").trim();
  return !!wanted && wanted === got;
}

function automationPushTargets_(p) {
  if (!automationAuthorized_(p.secret)) {
    return {ok:false,error:"AUTOMATION_UNAUTHORIZED"};
  }

  const props = PropertiesService.getScriptProperties().getProperties();
  const targets = [];

  Object.keys(props).forEach(function(key) {
    if (key.indexOf("PUSH::") !== 0) return;
    try {
      const item = JSON.parse(props[key]);
      if (!item || !item.endpoint || !item.keys || !item.keys.p256dh || !item.keys.auth) return;

      const username = normalizeUsername_(item.username || "");
      const userRaw = props[userKey_(username)];
      if (!userRaw) return;

      const u = JSON.parse(userRaw);
      if (!u.verified || u.revoked || subscriptionExpired_(u)) return;

      targets.push({
        key:key,
        username:username,
        endpoint:item.endpoint,
        keys:{p256dh:item.keys.p256dh,auth:item.keys.auth}
      });
    } catch (_) {}
  });

  return {ok:true,count:targets.length,targets:targets};
}

function automationPushDelete_(p) {
  if (!automationAuthorized_(p.secret)) {
    return {ok:false,error:"AUTOMATION_UNAUTHORIZED"};
  }
  const key = String(p.key || "");
  if (key.indexOf("PUSH::") !== 0) return {ok:false,error:"BAD_PUSH_KEY"};
  PropertiesService.getScriptProperties().deleteProperty(key);
  return {ok:true};
}

function cleanupPush_() {
  const props = PropertiesService.getScriptProperties();
  const all = props.getProperties();
  const rows = [];
  Object.keys(all).forEach(function(key) {
    if (key.indexOf("PUSH::") !== 0) return;
    try {
      const item = JSON.parse(all[key]);
      rows.push({key:key,updatedAt:String(item.updatedAt || item.createdAt || "")});
    } catch (_) {
      props.deleteProperty(key);
    }
  });
  rows.sort(function(a,b){return String(b.updatedAt).localeCompare(String(a.updatedAt));});
  rows.slice(500).forEach(function(x){props.deleteProperty(x.key);});
}

function supportSend_(p) {
  const auth = requireSession_(p.token);
  if (!auth.ok) return auth;

  const topic = String(p.topic || "Άλλο").trim().slice(0, 80);
  const message = String(p.message || "").trim();
  if (message.length < 10 || message.length > 1200) {
    return {ok:false,error:"BAD_SUPPORT_MESSAGE"};
  }

  const props = PropertiesService.getScriptProperties();
  const now = Date.now();
  const lastKey = "SUPPORT_LAST::" + auth.username;
  const lastAt = Number(props.getProperty(lastKey) || "0");
  if (lastAt && now - lastAt < 60 * 1000) {
    return {ok:false,error:"SUPPORT_RATE_LIMIT"};
  }

  const userRaw = props.getProperty(userKey_(auth.username));
  const user = userRaw ? JSON.parse(userRaw) : {};
  const id = Utilities.getUuid();
  const record = {
    id:id,
    username:auth.username,
    email:String(user.email || ""),
    topic:topic || "Άλλο",
    message:message,
    status:"new",
    createdAt:new Date(now).toISOString()
  };

  props.setProperty("SUPPORT::" + String(now) + "::" + id, JSON.stringify(record));
  props.setProperty(lastKey, String(now));
  cleanupSupport_();

  return {ok:true,ticketId:id};
}

function adminSupport_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};

  const props = PropertiesService.getScriptProperties().getProperties();
  const messages = [];

  Object.keys(props).forEach(function(k) {
    if (k.indexOf("SUPPORT::") !== 0) return;
    try {
      const item = JSON.parse(props[k]);
      messages.push({
        id:item.id || "",
        username:item.username || "",
        email:item.email || "",
        topic:item.topic || "Άλλο",
        message:item.message || "",
        status:item.status || "new",
        createdAt:item.createdAt || ""
      });
    } catch (_) {}
  });

  messages.sort(function(a,b){
    return String(b.createdAt).localeCompare(String(a.createdAt));
  });

  return {
    ok:true,
    newCount:messages.filter(function(x){return x.status !== "closed";}).length,
    messages:messages
  };
}

function adminSupportClose_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};

  const id = String(p.id || "").trim();
  if (!id) return {ok:false,error:"BAD_SUPPORT_ID"};

  const propsService = PropertiesService.getScriptProperties();
  const props = propsService.getProperties();
  let foundKey = "";

  Object.keys(props).some(function(k) {
    if (k.indexOf("SUPPORT::") !== 0) return false;
    try {
      const item = JSON.parse(props[k]);
      if (String(item.id || "") === id) {
        foundKey = k;
        return true;
      }
    } catch (_) {}
    return false;
  });

  if (!foundKey) return {ok:false,error:"SUPPORT_NOT_FOUND"};

  const item = JSON.parse(props[foundKey]);
  item.status = "closed";
  item.closedAt = new Date().toISOString();
  propsService.setProperty(foundKey, JSON.stringify(item));

  return {ok:true,id:id,status:"closed"};
}

function cleanupSupport_() {
  const propsService = PropertiesService.getScriptProperties();
  const props = propsService.getProperties();
  const keys = Object.keys(props)
    .filter(function(k){return k.indexOf("SUPPORT::") === 0;})
    .sort();

  while (keys.length > 250) {
    propsService.deleteProperty(keys.shift());
  }
}

function adminSettings_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};

  const used = countActiveUsers_();
  const pending = countPendingUsers_();
  const max = getMaxFreeUsers_();

  return {
    ok:true,
    usedUsers:used,
    pendingUsers:pending,
    maxUsers:max,
    freeSlots:Math.max(0,max-used),
    subscriptionDays:true,
    autoPushConfigured:!!PropertiesService.getScriptProperties().getProperty("CONFIG::AUTO_PUSH_SECRET"),
    internalSignals:true,
    memberHistory:true
  };
}

function adminSignals_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};

  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const pin = ss.getSheetByName(SHEET_NAME);
  if (!pin) return {ok:false,error:"SHEET_READ_FAILED"};

  const pinLast = pin.getLastRow();
  if (pinLast < 3) {
    return {ok:true,count:0,signals:[],updatedAt:new Date().toISOString()};
  }

  const rows = pin.getRange(3, 1, pinLast - 2, 16).getDisplayValues();
  const kickoffRows = pin.getRange(3, 77, pinLast - 2, 1).getDisplayValues();
  const signals = [];

  rows.forEach(function(row, idx) {
    const league = String(row[0] || "").trim();
    const home = String(row[1] || "").trim();
    const away = String(row[2] || "").trim();
    const favoriteSide = String(row[3] || "").trim().toUpperCase();
    const rawAlert = String(row[14] || "").trim();
    const alert = normalizeAlertName_(rawAlert);
    const result = String(row[15] || "").trim();

    if (!league || !home || !away || !alert || result) return;
    if (favoriteSide !== "H" && favoriteSide !== "A") return;

    const isContra = /ΚΟΝΤΡΑ|CONTRA/i.test(alert);
    const pickSide = isContra
      ? (favoriteSide === "H" ? "A" : "H")
      : favoriteSide;

    const customerPick = isContra
      ? (pickSide === "H" ? "1X" : "2X")
      : (pickSide === "H" ? "1" : "2");

    const records = alertRecords_(rows, league, alert);

    signals.push({
      league:league,
      home:home,
      away:away,
      favoriteSide:favoriteSide,
      favoriteTeam:favoriteSide === "H" ? home : away,
      internalAlert:alert,
      rawAlert:rawAlert,
      rating:alertRating_(rawAlert),
      leagueRecord:records.leagueRecord,
      allStatsRecord:records.allStatsRecord,
      customerPick:customerPick,
      customerTeam:pickSide === "H" ? home : away,
      kickoff:String((kickoffRows[idx] && kickoffRows[idx][0]) || "").trim()
    });
  });

  signals.sort(function(a,b) {
    const ta = Date.parse(a.kickoff || "") || 0;
    const tb = Date.parse(b.kickoff || "") || 0;
    return ta - tb;
  });

  return {
    ok:true,
    count:signals.length,
    signals:signals,
    updatedAt:new Date().toISOString()
  };
}

function adminPlayedHistory_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};

  const username = normalizeUsername_(p.username);
  if (!validUsername_(username)) return {ok:false,error:"BAD_USERNAME"};

  const propsService = PropertiesService.getScriptProperties();
  const userRaw = propsService.getProperty(userKey_(username));
  if (!userRaw) return {ok:false,error:"USER_NOT_FOUND"};

  const u = JSON.parse(userRaw);
  const allProps = propsService.getProperties();
  const prefix = "PLAYED::" + username + "::";
  const saved = [];

  Object.keys(allProps).forEach(function(key) {
    if (key.indexOf(prefix) !== 0) return;
    try {
      const item = JSON.parse(allProps[key]);
      if (item && item.id) saved.push(item);
    } catch (_) {}
  });

  let rowById = {};
  if (saved.length) {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const pin = ss.getSheetByName(SHEET_NAME);
    if (!pin) return {ok:false,error:"SHEET_READ_FAILED"};

    const pinLast = pin.getLastRow();
    const pinRows = pinLast >= 3 ? pin.getRange(3, 1, pinLast - 2, 16).getDisplayValues() : [];
    const kickoffRows = pinLast >= 3 ? pin.getRange(3, 77, pinLast - 2, 1).getDisplayValues() : [];

    pinRows.forEach(function(row, idx) {
      const league = String(row[0] || "").trim();
      const home = String(row[1] || "").trim();
      const away = String(row[2] || "").trim();
      const currentAlert = normalizeAlertName_(row[14]);
      const kickoff = String((kickoffRows[idx] && kickoffRows[idx][0]) || "").trim();
      if (!league || !home || !away || !currentAlert) return;
      rowById[selectionId_(league, home, away, currentAlert, kickoff)] = row;
    });
  }

  let wins = 0;
  let losses = 0;
  let pending = 0;

  const items = saved.map(function(item) {
    const row = rowById[item.id] || null;
    const alert = String(item.alert || "").trim();
    const favoriteSide = String(item.favoriteSide || (row ? row[3] : "") || "").trim().toUpperCase();
    const rawAlert = row ? String(row[14] || "").trim() : alert;
    const isContra = /ΚΟΝΤΡΑ|CONTRA/i.test(alert);
    const pickSide = isContra
      ? (favoriteSide === "H" ? "A" : favoriteSide === "A" ? "H" : "")
      : favoriteSide;
    const customerPick = isContra
      ? (pickSide === "H" ? "1X" : pickSide === "A" ? "2X" : "")
      : (pickSide === "H" ? "1" : pickSide === "A" ? "2" : "");
    const customerTeam = pickSide === "H" ? item.home : pickSide === "A" ? item.away : "";

    let score = "";
    let status = "pending";
    if (row) {
      const parsed = resultScore_(row[15]);
      const won = alertSuccess_(row, alert);
      if (parsed) score = parsed[0] + "-" + parsed[1];
      if (won === true) status = "win";
      else if (won === false) status = "loss";
    }

    if (status === "win") wins++;
    else if (status === "loss") losses++;
    else pending++;

    return {
      id:item.id,
      league:item.league,
      home:item.home,
      away:item.away,
      favoriteSide:favoriteSide,
      internalAlert:alert,
      rating:alertRating_(rawAlert),
      customerPick:customerPick,
      customerTeam:customerTeam,
      kickoff:item.kickoff,
      addedAt:item.createdAt,
      score:score,
      status:status
    };
  });

  items.sort(function(a,b) {
    const ta = Date.parse(a.addedAt || a.kickoff || "") || 0;
    const tb = Date.parse(b.addedAt || b.kickoff || "") || 0;
    return tb - ta;
  });

  const expiryMs = Date.parse(String(u.subscriptionEndsAt || ""));
  const remainingDays = Number.isFinite(expiryMs)
    ? Math.max(0, Math.ceil((expiryMs - Date.now()) / (24 * 60 * 60 * 1000)))
    : null;

  return {
    ok:true,
    user:{
      username:u.username,
      email:u.email || "",
      verified:!!u.verified,
      revoked:!!u.revoked,
      createdAt:u.createdAt || "",
      verifiedAt:u.verifiedAt || "",
      subscriptionEndsAt:u.subscriptionEndsAt || "",
      subscriptionExpired:subscriptionExpired_(u),
      remainingDays:remainingDays
    },
    summary:{
      total:items.length,
      wins:wins,
      losses:losses,
      pending:pending
    },
    items:items.slice(0,250)
  };
}

function adminUsers_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};

  const props = PropertiesService.getScriptProperties().getProperties();
  const users = [];

  Object.keys(props).forEach(function(k) {
    if (k.indexOf("USER::") !== 0) return;
    try {
      const u = JSON.parse(props[k]);
      users.push({
        username:u.username,
        email:u.email || "",
        verified:!!u.verified,
        revoked:!!u.revoked,
        createdAt:u.createdAt || "",
        verifiedAt:u.verifiedAt || "",
        subscriptionEndsAt:u.subscriptionEndsAt || "",
        subscriptionExpired:subscriptionExpired_(u)
      });
    } catch (_) {}
  });

  users.sort(function(a,b){
    return String(b.createdAt).localeCompare(String(a.createdAt));
  });

  return {ok:true,users:users};
}

function adminSetMaxUsers_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};

  const n = Number(p.maxUsers);
  if (!Number.isFinite(n) || n < 0 || n > 10000) {
    return {ok:false,error:"BAD_MAX_USERS"};
  }

  const maxUsers = Math.floor(n);
  PropertiesService.getScriptProperties()
    .setProperty("CONFIG::MAX_FREE_USERS", String(maxUsers));

  return adminSettings_(p);
}

function adminAddDays_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};
  return addSubscriptionDays_(p.username, p.days);
}

function adminAddDaysAll_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};

  const days = Number(p.days);
  if (!Number.isFinite(days) || days < 1 || days > 3650 || Math.floor(days) !== days) {
    return {ok:false,error:"BAD_DAYS"};
  }

  const propsService = PropertiesService.getScriptProperties();
  const props = propsService.getProperties();
  const now = Date.now();
  let updated = 0;
  let skippedNoExpiry = 0;
  let skippedExpired = 0;

  Object.keys(props).forEach(function(k) {
    if (k.indexOf("USER::") !== 0) return;
    try {
      const u = JSON.parse(props[k]);
      if (!u.verified || u.revoked) return;

      const current = Date.parse(String(u.subscriptionEndsAt || ""));
      if (!Number.isFinite(current)) {
        skippedNoExpiry++;
        return;
      }
      if (current <= now) {
        skippedExpired++;
        return;
      }

      u.subscriptionEndsAt = new Date(current + days * 24 * 60 * 60 * 1000).toISOString();
      u.updatedAt = new Date().toISOString();
      propsService.setProperty(k, JSON.stringify(u));
      updated++;
    } catch (_) {}
  });

  return {ok:true,days:days,updated:updated,skippedNoExpiry:skippedNoExpiry,skippedExpired:skippedExpired};
}

function addSubscriptionDays_(usernameRaw, daysRaw) {
  const username = normalizeUsername_(usernameRaw);
  const days = Number(daysRaw);
  if (!validUsername_(username)) return {ok:false,error:"BAD_USERNAME"};
  if (!Number.isFinite(days) || days < 1 || days > 3650 || Math.floor(days) !== days) {
    return {ok:false,error:"BAD_DAYS"};
  }

  const props = PropertiesService.getScriptProperties();
  const key = userKey_(username);
  const raw = props.getProperty(key);
  if (!raw) return {ok:false,error:"USER_NOT_FOUND"};

  const u = JSON.parse(raw);
  if (!u.verified) return {ok:false,error:"USER_NOT_VERIFIED"};

  const now = Date.now();
  const current = Date.parse(String(u.subscriptionEndsAt || ""));
  const base = Number.isFinite(current) && current > now ? current : now;
  u.subscriptionEndsAt = new Date(base + days * 24 * 60 * 60 * 1000).toISOString();
  u.updatedAt = new Date().toISOString();
  props.setProperty(key, JSON.stringify(u));

  return {
    ok:true,
    username:username,
    daysAdded:days,
    subscriptionEndsAt:u.subscriptionEndsAt
  };
}

function adminRevoke_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};
  return setUserAccess_(p.username, true);
}

function adminRestore_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};
  return setUserAccess_(p.username, false);
}

function setUserAccess_(usernameRaw, revoked) {
  const username = normalizeUsername_(usernameRaw);
  const props = PropertiesService.getScriptProperties();
  const key = userKey_(username);
  const raw = props.getProperty(key);
  if (!raw) return {ok:false,error:"USER_NOT_FOUND"};

  const u = JSON.parse(raw);
  u.revoked = revoked;
  u.updatedAt = new Date().toISOString();
  props.setProperty(key, JSON.stringify(u));

  if (revoked) invalidateSessionsForUser_(username);

  return {
    ok:true,
    username:username,
    revoked:revoked
  };
}

function adminDelete_(p) {
  if (!isAdmin_(p.adminCode)) return {ok:false,error:"ADMIN_UNAUTHORIZED"};

  const username = normalizeUsername_(p.username);
  const props = PropertiesService.getScriptProperties();
  const key = userKey_(username);

  if (!props.getProperty(key)) return {ok:false,error:"USER_NOT_FOUND"};

  invalidateSessionsForUser_(username);
  props.deleteProperty(key);

  return {
    ok:true,
    deleted:true,
    username:username
  };
}

function requireSession_(token) {
  if (!token) return {ok:false,error:"LOGIN_REQUIRED"};

  const props = PropertiesService.getScriptProperties();
  const raw = props.getProperty(sessionKey_(token));
  if (!raw) return {ok:false,error:"INVALID_SESSION"};

  const s = JSON.parse(raw);
  if (!s.expiresAt || Date.now() > Number(s.expiresAt)) {
    props.deleteProperty(sessionKey_(token));
    return {ok:false,error:"SESSION_EXPIRED"};
  }

  const userRaw = props.getProperty(userKey_(s.username));
  if (!userRaw) return {ok:false,error:"USER_NOT_FOUND"};

  const u = JSON.parse(userRaw);
  if (!u.verified || u.revoked) return {ok:false,error:"ACCESS_DENIED"};
  if (subscriptionExpired_(u)) {
    props.deleteProperty(sessionKey_(token));
    return {ok:false,error:"SUBSCRIPTION_EXPIRED"};
  }

  return {ok:true,username:s.username,subscriptionEndsAt:u.subscriptionEndsAt || ""};
}

function countActiveUsers_() {
  const props = PropertiesService.getScriptProperties().getProperties();
  let n = 0;
  Object.keys(props).forEach(function(k) {
    if (k.indexOf("USER::") !== 0) return;
    try {
      const u = JSON.parse(props[k]);
      if (u.verified && !u.revoked && !subscriptionExpired_(u)) n++;
    } catch (_) {}
  });
  return n;
}

function subscriptionExpired_(u) {
  const raw = String((u && u.subscriptionEndsAt) || "").trim();
  if (!raw) return false;
  const t = Date.parse(raw);
  return Number.isFinite(t) && Date.now() >= t;
}

function countPendingUsers_() {
  const props = PropertiesService.getScriptProperties().getProperties();
  let n = 0;
  Object.keys(props).forEach(function(k) {
    if (k.indexOf("USER::") !== 0) return;
    try {
      const u = JSON.parse(props[k]);
      if (!u.verified) n++;
    } catch (_) {}
  });
  return n;
}

function getMaxFreeUsers_() {
  const raw = PropertiesService.getScriptProperties()
    .getProperty("CONFIG::MAX_FREE_USERS");
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? Math.floor(n) : DEFAULT_MAX_FREE_USERS;
}

function cleanupPending_() {
  const propsService = PropertiesService.getScriptProperties();
  const props = propsService.getProperties();
  const now = Date.now();

  Object.keys(props).forEach(function(k) {
    if (k.indexOf("USER::") !== 0) return;
    try {
      const u = JSON.parse(props[k]);
      if (!u.verified && u.verifyExpiresAt && now > Number(u.verifyExpiresAt) + 24*60*60*1000) {
        propsService.deleteProperty(k);
      }
    } catch (_) {}
  });
}

function findUserByEmail_(email) {
  const props = PropertiesService.getScriptProperties().getProperties();
  const target = normalizeEmail_(email);

  for (const k in props) {
    if (k.indexOf("USER::") !== 0) continue;
    try {
      const u = JSON.parse(props[k]);
      if (normalizeEmail_(u.email) === target) return u;
    } catch (_) {}
  }
  return null;
}

function invalidateSessionsForUser_(username) {
  const propsService = PropertiesService.getScriptProperties();
  const props = propsService.getProperties();

  Object.keys(props).forEach(function(k) {
    if (k.indexOf("SESSION::") !== 0) return;
    try {
      const s = JSON.parse(props[k]);
      if (s.username === username) propsService.deleteProperty(k);
    } catch (_) {}
  });
}

function sendVerificationEmail_(email, username, code) {
  const subject = "Match Alerts - Κωδικός επιβεβαίωσης";
  const body =
    "Γεια σου " + username + ",\n\n" +
    "Ο κωδικός επιβεβαίωσης για το Match Alerts είναι:\n\n" +
    code + "\n\n" +
    "Ο κωδικός λήγει σε " + VERIFY_MINUTES + " λεπτά.\n\n" +
    "Αν δεν έκανες εσύ την εγγραφή, αγνόησε αυτό το email.";

  MailApp.sendEmail(email, subject, body);
}

function verificationCode_() {
  return String(Math.floor(100000 + Math.random() * 900000));
}

function hashVerification_(code, email) {
  return digestHex_("VERIFY::" + normalizeEmail_(email) + "::" + code);
}

function hashPassword_(password, salt) {
  let value = salt + "::" + password;
  for (let i = 0; i < PASSWORD_ROUNDS; i++) {
    value = digestHex_(value + "::" + salt);
  }
  return value;
}

function digestHex_(value) {
  const bytes = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    String(value),
    Utilities.Charset.UTF_8
  );

  return bytes.map(function(b) {
    const v = (b < 0 ? b + 256 : b).toString(16);
    return v.length === 1 ? "0" + v : v;
  }).join("");
}

function normalizeUsername_(v) {
  return String(v || "").trim().toLowerCase();
}

function normalizeEmail_(v) {
  return String(v || "").trim().toLowerCase();
}

function validUsername_(v) {
  return /^[a-z0-9._-]{3,32}$/.test(v);
}

function validEmail_(v) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v) && v.length <= 160;
}

function maskEmail_(email) {
  const parts = String(email || "").split("@");
  if (parts.length !== 2) return "";
  const name = parts[0];
  const masked = name.length <= 2
    ? name.charAt(0) + "*"
    : name.charAt(0) + "*".repeat(Math.min(5,name.length-2)) + name.charAt(name.length-1);
  return masked + "@" + parts[1];
}

function userKey_(username) {
  return "USER::" + username;
}

function sessionKey_(token) {
  return "SESSION::" + token;
}

function makeToken_() {
  return Utilities.getUuid().replace(/-/g,"") +
         Utilities.getUuid().replace(/-/g,"");
}

function isAdmin_(code) {
  return String(code || "") === ADMIN_CODE;
}

function bridge_(payload, requestId) {
  const message = JSON.stringify({
    source:"MATCH_ALERTS_API",
    requestId:String(requestId || ""),
    payload:payload
  }).replace(/</g,"\\u003c");

  const html =
    "<!doctype html><meta charset='utf-8'><script>" +
    "parent.postMessage(" + message + "," + JSON.stringify(APP_ORIGIN) + ");" +
    "<\/script>";

  return HtmlService.createHtmlOutput(html)
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
