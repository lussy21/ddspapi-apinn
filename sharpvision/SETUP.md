# SharpVision — personal deployment

This is a **new, isolated** read-only service. It does not modify the existing Sheets cron, Apps Script betting system, or other Render services. All dashboard source code lives in \`sharpvision/\`.

## Production environment variables

- \`SV_VIEW_PASSWORD\`: long private login passphrase (never commit).
- \`SV_SESSION_SECRET\`: random session signing secret (never commit).
- \`SV_FEED_KEY\`: random token also configured as the Apps Script property \`SHARPVISION_FEED_KEY\`.
- \`SV_FEED_URL\`: deployed Google Apps Script **/exec** HTTPS URL after setup.

Render settings:
- Build: \`pip install -r sharpvision/requirements.txt\`
- Start: \`gunicorn --chdir sharpvision server:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 70\`
- Type: Web Service; region Frankfurt; free plan for trial; explicit branch \`sharpvision-personal-live\`.

## Connect the existing private PINNACLE sheet

1. Open https://script.google.com/home/projects/create and create a **NEW, standalone** Apps Script project for SharpVision.
2. Paste the contents of \`SheetFeed.gs\` into the new standalone project. **Do not add it to any existing Apps Script project**, which may contain a separate doGet handler or scheduled automation.
3. Project Settings > Script Properties > add \`SHARPVISION_FEED_KEY\` containing exactly the Render \`SV_FEED_KEY\`.
4. Deploy > **New deployment > Web app**, run as the spreadsheet owner, access **Anyone**. Only a request with the secret key returns data; other requests receive an unauthorized response. Treat the /exec URL and secret as sensitive.
5. Set Render environment \`SV_FEED_URL\` to the deployed /exec URL. Wait for redeploy. The app will then read new PINNACLE values with a 9-minute backend cache (source updates separately every 10 min).

Security note: the Google Apps Script deployment endpoint is reachable publicly but requires a separate high-entropy token. To avoid an 'Anyone' deployment entirely, use a Google Cloud service-account-based backend instead. Never make the private spreadsheet public, add tokens to GitHub, or embed tokens in the browser frontend.

## What live means here

The app reads the rows of PINNACLE that the existing scheduled writer fills. No separate fixture provider is wired; the **Without score** tab means no final result in Sheet, not confirmed matches on today's date. The application records local preferences and predictions in the browser on that device only. Historical search and results come from the Sheet. Estimates are heuristic, not calibrated probabilities. The Render free service may sleep when idle, causing a cold-start delay.
