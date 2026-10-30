-- Rows waiting for a fix
-- Tab: Sync Health · Visualization: Number

SELECT COUNT(*) AS "Rows waiting for a fix"
FROM   sync_errors
WHERE  resolved_at IS NULL;
