-- Last sync
-- Tab: Sync Health · Visualization: Table (one row)

SELECT MAX(finished_at)                                           AS "Last sync",
       ROUND((julianday((SELECT now_local FROM v_clock)) - julianday(MAX(finished_at))) * 24 * 60) AS "Minutes ago"
FROM   sync_runs
WHERE  status = 'success';
