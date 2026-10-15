# SharpVision — προσωπικός online καθρέφτης του Excel

The PINNACLE Google Sheet is the source of truth. This isolated service never writes to it.

## Render service

- Workspace: odds papi
- Service: sharpvision-personal
- Branch: sharpvision-personal-live
- Front end: https://sharpvision-personal.onrender.com
- Existing \`SV_FEED_URL\`, \`SV_FEED_KEY\`, \`SV_VIEW_PASSWORD\` and \`SV_SESSION_SECRET\` remain configured in Render. Do not post any secrets in chat, GitHub, or screenshots.

The Render app uses a 9-minute cache (the original Excel pipeline updates roughly every 10 minutes).

## Enable exact Excel parity (one-time Apps Script update)

The **old** deployed Google Apps Script outputs only A:Y (25 columns), so Excel's source percentile cells BL/BM and the actual applied conditional colors are absent. The Python service and browser work with the older feed while waiting for the new deployment, but can only approximate some colors. **To obtain exact source values and colors:**

1. Open the user's **separate** \`SharpVision Feed\` Apps Script project, **not** their original scheduled updater or alerts.
2. Replace only the code in \`Κώδικας.gs\` with the complete contents of \`sharpvision/SheetFeed.gs\`. Save.
3. Keep \`appsscript.json\` **unchanged**. It should already contain \`spreadsheets.readonly\` and \`script.external_request\` scopes. Keep Script Property \`SHARPVISION_FEED_KEY\` **unchanged**.
4. In Apps Script: Deploy → Manage deployments → edit the existing web app → Version: New version → Deploy. Keep Execute as Me and Who has access Anyone (separate secret required).
5. The Web app /exec URL remains unchanged if updating the existing deployment. **Do not** create a separate new deployment.
6. Open the existing SharpVision website and refresh. The app will then use exact original cell values, Google Sheet conditional colors and BL/BM league percentile cells.

The new feed uses the Google Sheets REST API with read-only OAuth to retrieve native formatted values from A:CD and effective conditional formatting from the relevant K:P and U:Y cell ranges. It returns only non-white fill colors to limit payload size. If the optional style read fails, the match values still load and the app falls back to previously configured color levels.

## Source-of-truth columns

A League, B Home, C Away, D F(H/A); E–G Favorite Odds (Open / 90 / Last), H–J Contra+0.5 odds; K Current Turnover, L Favorite %, M Contra %, N SofaScore, O Alert, P Final Score; T/U/V 11:00 turnover/favorite/contra; W/X/Y 90-min turnover/favorite/contra; BL (0-based 63) 90-minute league turnover percentile, BM (0-based 64) current league turnover percentile.

The original conditional formatting: K turnover <=35 light blue; >35–75 orange; >75–87 red; >87 dark burgundy. W (90-minute turnover) uses <=35 blue; >35–75 orange; >75–88 red; >88 dark burgundy. L/U/X favorite >=82 red, 75–<82 orange. M/V/Y contra >=32 red, 26–<32 orange. N SofaScore >=82 red, 75–<82 yellow. Alerts and results take the actual source cell colors.

## Historical scanner vs. Excel

"Similar past matches" is an additional feature that does not literally exist as a PINNACLE cell. Every match, score, odds and snapshot must originate from the same Sheet, and only completed results are used in historical outcomes. Similarity is a transparent heuristic and is labeled preliminary when needed stages are absent. It is **not** equivalent to an Excel alert or a calibrated win probability.

Google Apps Script feed has no standalone event schedule: the app reads new values supplied by the existing sheet updater.
