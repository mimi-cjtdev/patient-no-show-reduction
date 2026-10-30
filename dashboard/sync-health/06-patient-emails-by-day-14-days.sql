-- Patient emails by day (14 days)
-- Tab: Sync Health · Visualization: Bar, stacked (x: Day, series: Kind)
-- Confirmations, reminders and waitlist offers. Anything with result 'failed: ...' is retried next hour.

SELECT date(sent_at)                                         AS "Day",
       kind                                                  AS "Kind",
       SUM(result NOT LIKE 'failed%')                        AS "Sent",
       SUM(result LIKE 'failed%')                            AS "Failed"
FROM   reminders
WHERE  sent_at >= date((SELECT today FROM v_clock), '-14 days')
GROUP  BY 1, 2
ORDER  BY 1, 2;
