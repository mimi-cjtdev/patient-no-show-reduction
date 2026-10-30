-- Rejected rows by error type (30 days)
-- Tab: Sync Health · Visualization: Bar (horizontal)

SELECT error_type AS "Error type",
       COUNT(*)   AS "Rows"
FROM   sync_errors
WHERE  first_seen_at >= datetime((SELECT now_local FROM v_clock), '-30 days')
GROUP  BY error_type
ORDER  BY 2 DESC;
