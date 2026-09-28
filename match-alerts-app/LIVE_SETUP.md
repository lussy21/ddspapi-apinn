# Match Alerts — Live read-only connector

This Google Apps Script is intentionally separate from the core betting scripts.

It only:
- opens spreadsheet 1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM
- reads PINNACLE A:P
- returns rows where column O has an alert and column P is empty
- exposes only league/home/away/alert

It never writes to the spreadsheet.

Deployment:
1. Create a new standalone Apps Script project.
2. Paste read_only_webapp.gs into Code.gs.
3. Deploy > New deployment > Web app.
4. Execute as: Me.
5. Who has access: Anyone.
6. Copy the /exec URL and provide it to ChatGPT.
