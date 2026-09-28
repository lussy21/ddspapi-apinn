/**
 * MATCH ALERTS PRIVATE BACKEND
 * Standalone Google Apps Script.
 *
 * Core safety:
 * - Reads PINNACLE only.
 * - Never writes to PINNACLE.
 * - User accounts/sessions are stored only in Script Properties.
 * - A user must be APPROVED before login can return a usable session.
 */

const SPREADSHEET_ID = "1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM";
const SHEET_NAME = "PINNACLE";

// Change this later if you want. Do NOT give it to normal users.
// IMPORTANT: replace this ONLY inside your private Apps Script before deploying.
// Never commit your real admin code to GitHub.
const ADMIN_CODE = "CHANGE_THIS_IN_APPS_SCRIPT";

const SESSION_HOURS = 24 * 30; // 30 days
const DEFAULT_MAX_FREE_USERS = 2;
const REGISTRATION_MODE = "free"; // later: "subscription"

function doGet(e) {
  const p = e && e.parameter ? e.parameter : {};
  const action = String(p.action || "status");

  try {
    if (action === "status") return json_({ok:true, service:"match-alerts-private"});
    if (action === "alerts") return handleAlerts_(p);
    if (action === "adminPending") return handleAdminPending_(p);
    if (action === "adminApprove") return handleAdminApprove_(p);
    if (action === "adminRevoke") return handleAdminRevoke_(p);
    if (action === "adminDelete") return handleAdminDelete_(p);
    if (action === "adminSettings") return handleAdminSettings_(p);
    if (action === "adminSetMaxUsers") return handleAdminSetMaxUsers_(p);
    return json_({ok:false,error:"UNKNOWN_ACTION"});
  } catch (err) {
    return json_({ok:false,error:"SERVER_ERROR",message:String(err && err.message || err)});
  }
}

function doPost(e) {
  try {
    const data = parseBody_(e);
    const action = String(data.action || "");

    if (action === "register") return handleRegister_(data);
    if (action === "login") return handleLogin_(data);

    return json_({ok:false,error:"UNKNOWN_ACTION"});
  } catch (err) {
    return json_({ok:false,error:"SERVER_ERROR",message:String(err && err.message || err)});
  }
}

function handleRegister_(data) {
  const username = normalizeUsername_(data.username);
  const password = String(data.password || "");

  if (!validUsername_(username)) {
    return json_({ok:false,error:"BAD_USERNAME"});
  }
  if (password.length < 6) {
    return json_({ok:false,error:"PASSWORD_TOO_SHORT"});
  }

  const props = PropertiesService.getScriptProperties();
  const key = userKey_(username);

  if (props.getProperty(key)) {
    return json_({ok:false,error:"USER_EXISTS"});
  }

  const currentUsers = countUsers_();
  const maxFreeUsers = getMaxFreeUsers_();
  if (REGISTRATION_MODE === "free" && currentUsers >= maxFreeUsers) {
    return json_({
      ok:false,
      error:"REGISTRATION_FULL",
      message:"Οι δωρεάν εγγραφές έχουν συμπληρωθεί."
    });
  }

  const salt = Utilities.getUuid();
  const record = {
    username: username,
    salt: salt,
    hash: hashPassword_(password, salt),
    approved: true,
    createdAt: new Date().toISOString(),
    revoked: false
  };

  props.setProperty(key, JSON.stringify(record));
  return json_({
    ok:true,
    status:"ACTIVE",
    remainingFreeSlots: Math.max(0, getMaxFreeUsers_() - countUsers_())
  });
}

function getMaxFreeUsers_() {
  const props = PropertiesService.getScriptProperties();
  const raw = props.getProperty("CONFIG::MAX_FREE_USERS");
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? Math.floor(n) : DEFAULT_MAX_FREE_USERS;
}

function handleAdminSettings_(p) {
  if (!isAdmin_(p.adminCode)) return json_({ok:false,error:"ADMIN_UNAUTHORIZED"});
  const used = countUsers_();
  const max = getMaxFreeUsers_();
  return json_({
    ok:true,
    registrationMode:REGISTRATION_MODE,
    usedUsers:used,
    maxUsers:max,
    freeSlots:Math.max(0,max-used)
  });
}

function handleAdminSetMaxUsers_(p) {
  if (!isAdmin_(p.adminCode)) return json_({ok:false,error:"ADMIN_UNAUTHORIZED"});

  const n = Number(p.maxUsers);
  if (!Number.isFinite(n) || n < 0 || n > 10000) {
    return json_({ok:false,error:"BAD_MAX_USERS"});
  }

  const maxUsers = Math.floor(n);
  PropertiesService.getScriptProperties()
    .setProperty("CONFIG::MAX_FREE_USERS", String(maxUsers));

  const used = countUsers_();
  return json_({
    ok:true,
    usedUsers:used,
    maxUsers:maxUsers,
    freeSlots:Math.max(0,maxUsers-used)
  });
}

function countUsers_() {
  const props = PropertiesService.getScriptProperties().getProperties();
  return Object.keys(props).filter(function(k) {
    return k.indexOf("USER::") === 0;
  }).length;
}

function handleLogin_(data) {
  const username = normalizeUsername_(data.username);
  const password = String(data.password || "");

  const props = PropertiesService.getScriptProperties();
  const raw = props.getProperty(userKey_(username));
  if (!raw) return json_({ok:false,error:"INVALID_LOGIN"});

  const user = JSON.parse(raw);
  if (user.revoked) return json_({ok:false,error:"ACCESS_REVOKED"});
  if (!user.approved) return json_({ok:false,error:"PENDING_APPROVAL"});

  if (hashPassword_(password, user.salt) !== user.hash) {
    return json_({ok:false,error:"INVALID_LOGIN"});
  }

  const token = makeToken_();
  const expiresAt = Date.now() + SESSION_HOURS * 60 * 60 * 1000;

  props.setProperty(sessionKey_(token), JSON.stringify({
    username: username,
    expiresAt: expiresAt
  }));

  return json_({
    ok:true,
    token:token,
    username:username,
    expiresAt:new Date(expiresAt).toISOString()
  });
}

function handleAlerts_(p) {
  const auth = requireSession_(String(p.token || ""));
  if (!auth.ok) return json_(auth);

  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) return json_({ok:false,error:"PINNACLE_NOT_FOUND"});

  const lastRow = sheet.getLastRow();
  if (lastRow < 3) {
    return json_({ok:true,alerts:[],count:0,updatedAt:new Date().toISOString()});
  }

  const values = sheet.getRange(3,1,lastRow-2,16).getDisplayValues();
  const alerts = [];

  values.forEach(function(row) {
    const league = String(row[0] || "").trim();
    const home = String(row[1] || "").trim();
    const away = String(row[2] || "").trim();
    const alert = String(row[14] || "").trim();
    const result = String(row[15] || "").trim();

    if (!league || !home || !away || !alert || result) return;

    alerts.push({
      league:league,
      home:home,
      away:away,
      alert:alert
    });
  });

  return json_({
    ok:true,
    username:auth.username,
    count:alerts.length,
    updatedAt:new Date().toISOString(),
    alerts:alerts
  });
}

function handleAdminPending_(p) {
  if (!isAdmin_(p.adminCode)) return json_({ok:false,error:"ADMIN_UNAUTHORIZED"});

  const props = PropertiesService.getScriptProperties().getProperties();
  const users = [];

  Object.keys(props).forEach(function(k) {
    if (k.indexOf("USER::") !== 0) return;
    const u = JSON.parse(props[k]);
    users.push({
      username:u.username,
      approved:!!u.approved,
      revoked:!!u.revoked,
      createdAt:u.createdAt || ""
    });
  });

  users.sort(function(a,b){ return String(a.createdAt).localeCompare(String(b.createdAt)); });
  return json_({ok:true,users:users});
}

function handleAdminApprove_(p) {
  if (!isAdmin_(p.adminCode)) return json_({ok:false,error:"ADMIN_UNAUTHORIZED"});
  return setUserAccess_(p.username, true, false);
}

function handleAdminRevoke_(p) {
  if (!isAdmin_(p.adminCode)) return json_({ok:false,error:"ADMIN_UNAUTHORIZED"});
  return setUserAccess_(p.username, false, true);
}

function handleAdminDelete_(p) {
  if (!isAdmin_(p.adminCode)) return json_({ok:false,error:"ADMIN_UNAUTHORIZED"});

  const username = normalizeUsername_(p.username);
  const props = PropertiesService.getScriptProperties();
  const key = userKey_(username);

  if (!props.getProperty(key)) return json_({ok:false,error:"USER_NOT_FOUND"});

  invalidateSessionsForUser_(username);
  props.deleteProperty(key);

  const used = countUsers_();
  const max = getMaxFreeUsers_();

  return json_({
    ok:true,
    username:username,
    deleted:true,
    usedUsers:used,
    maxUsers:max,
    freeSlots:Math.max(0,max-used)
  });
}

function setUserAccess_(usernameRaw, approved, revoked) {
  const username = normalizeUsername_(usernameRaw);
  const props = PropertiesService.getScriptProperties();
  const key = userKey_(username);
  const raw = props.getProperty(key);
  if (!raw) return json_({ok:false,error:"USER_NOT_FOUND"});

  const u = JSON.parse(raw);
  u.approved = approved;
  u.revoked = revoked;
  u.updatedAt = new Date().toISOString();
  props.setProperty(key, JSON.stringify(u));

  if (revoked) {
    invalidateSessionsForUser_(username);
  }

  return json_({ok:true,username:username,approved:approved,revoked:revoked});
}

function requireSession_(token) {
  if (!token) return {ok:false,error:"LOGIN_REQUIRED"};

  const props = PropertiesService.getScriptProperties();
  const raw = props.getProperty(sessionKey_(token));
  if (!raw) return {ok:false,error:"INVALID_SESSION"};

  const session = JSON.parse(raw);
  if (!session.expiresAt || Date.now() > Number(session.expiresAt)) {
    props.deleteProperty(sessionKey_(token));
    return {ok:false,error:"SESSION_EXPIRED"};
  }

  const userRaw = props.getProperty(userKey_(session.username));
  if (!userRaw) return {ok:false,error:"USER_NOT_FOUND"};

  const user = JSON.parse(userRaw);
  if (!user.approved || user.revoked) {
    return {ok:false,error:"ACCESS_DENIED"};
  }

  return {ok:true,username:session.username};
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

function parseBody_(e) {
  if (!e || !e.postData) return {};

  const type = String(e.postData.type || "").toLowerCase();
  const raw = String(e.postData.contents || "");

  if (type.indexOf("application/json") >= 0 && raw) {
    return JSON.parse(raw);
  }

  return e.parameter || {};
}

function normalizeUsername_(v) {
  return String(v || "").trim().toLowerCase();
}

function validUsername_(v) {
  return /^[a-z0-9._-]{3,32}$/.test(v);
}

function userKey_(username) {
  return "USER::" + username;
}

function sessionKey_(token) {
  return "SESSION::" + token;
}

function hashPassword_(password, salt) {
  const bytes = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    salt + "::" + password,
    Utilities.Charset.UTF_8
  );

  return bytes.map(function(b) {
    const v = (b < 0 ? b + 256 : b).toString(16);
    return v.length === 1 ? "0" + v : v;
  }).join("");
}

function makeToken_() {
  return Utilities.getUuid().replace(/-/g,"") +
         Utilities.getUuid().replace(/-/g,"");
}

function isAdmin_(code) {
  return String(code || "") === ADMIN_CODE;
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
