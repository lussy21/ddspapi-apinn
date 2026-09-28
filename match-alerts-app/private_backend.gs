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
    else if (action === "adminSettings") payload = adminSettings_(p);
    else if (action === "adminUsers") payload = adminUsers_(p);
    else if (action === "adminSetMaxUsers") payload = adminSetMaxUsers_(p);
    else if (action === "adminRevoke") payload = adminRevoke_(p);
    else if (action === "adminRestore") payload = adminRestore_(p);
    else if (action === "adminDelete") payload = adminDelete_(p);
    else payload = {ok:false,error:"UNKNOWN_ACTION"};
  } catch (err) {
    payload = {ok:false,error:"SERVER_ERROR"};
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
    expiresAt:new Date(expiresAt).toISOString()
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

  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) return {ok:false,error:"PINNACLE_NOT_FOUND"};

  const lastRow = sheet.getLastRow();
  if (lastRow < 3) {
    return {ok:true,username:auth.username,count:0,updatedAt:new Date().toISOString(),alerts:[]};
  }

  const values = sheet.getRange(3,1,lastRow-2,16).getDisplayValues();
  const out = [];

  values.forEach(function(row) {
    const league = String(row[0] || "").trim();
    const home = String(row[1] || "").trim();
    const away = String(row[2] || "").trim();
    const favoriteSide = String(row[3] || "").trim();
    const alert = String(row[14] || "").trim();
    const result = String(row[15] || "").trim();

    if (!league || !home || !away || !alert || result) return;

    out.push({
      league:league,
      home:home,
      away:away,
      favoriteSide:favoriteSide,
      alert:alert
    });
  });

  return {
    ok:true,
    username:auth.username,
    count:out.length,
    updatedAt:new Date().toISOString(),
    alerts:out
  };
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
    freeSlots:Math.max(0,max-used)
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
        verifiedAt:u.verifiedAt || ""
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

  return {ok:true,username:s.username};
}

function countActiveUsers_() {
  const props = PropertiesService.getScriptProperties().getProperties();
  let n = 0;
  Object.keys(props).forEach(function(k) {
    if (k.indexOf("USER::") !== 0) return;
    try {
      const u = JSON.parse(props[k]);
      if (u.verified && !u.revoked) n++;
    } catch (_) {}
  });
  return n;
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
