-- Failed runs (7 days)
-- Tab: Sync Health · Visualization: Number

SELECT COUNT(*) AS "Failed runs"
FROM   sync_runs
WHERE  status = 'failed'
  AND  started_at >= datetime((SELECT now_local FROM v_clock), '-7 days');
