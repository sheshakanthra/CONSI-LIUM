-- Runs once on first cluster init (mounted into the postgres image's
-- /docker-entrypoint-initdb.d). WHY here rather than in app migrations:
-- CREATE EXTENSION needs superuser, which the app's runtime role should not
-- have. Doing it at bootstrap keeps the application DB role least-privileged.
CREATE EXTENSION IF NOT EXISTS vector;
