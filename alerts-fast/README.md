# Alerts Fast

Standalone read-only viewer planned for the existing cached `owner-lite-feed` endpoint.

The production Admin, scoring logic, cron jobs and upstream services must not be modified.

Authentication uses the existing owner gateway. Data is advisory and up to ten minutes old; always display the last update timestamp.
