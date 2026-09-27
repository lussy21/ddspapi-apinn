const SOFA_WORKER_URL =
  'https://raw.githubusercontent.com/lussy21/ddspapi-apinn/main/google_apps_script/SofaScoreWorker.gs';

function sofaRun_(functionName) {
  const response = UrlFetchApp.fetch(SOFA_WORKER_URL, {
    method: 'get',
    muteHttpExceptions: true
  });
  if (response.getResponseCode() !== 200) {
    throw new Error('Worker download failed: HTTP ' + response.getResponseCode());
  }
  const code = response.getContentText();
  eval(code + '\n' + functionName + '();');
}

function sofaTest() {
  sofaRun_('testSofaGoogleConnection');
}

function sofaScheduleTest() {
  sofaRun_('testSofaScheduleToday');
}

function sofaDaily() {
  sofaRun_('runSofaDaily');
}

function installSofaDaily() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'sofaDaily') {
      ScriptApp.deleteTrigger(t);
    }
  });

  ScriptApp.newTrigger('sofaDaily')
    .timeBased()
    .atHour(12)
    .nearMinute(30)
    .everyDays(1)
    .inTimezone('Europe/Athens')
    .create();
}

function removeSofaDaily() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'sofaDaily') {
      ScriptApp.deleteTrigger(t);
    }
  });
}
