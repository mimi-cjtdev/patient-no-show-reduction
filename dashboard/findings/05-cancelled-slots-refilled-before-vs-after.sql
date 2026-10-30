-- Cancelled slots re-filled: before vs after the waitlist
-- Tab: Findings · Visualization: Bar
-- Before the launch a cancelled slot was only re-filled if someone happened to phone in.

SELECT period                                             AS "Cancelled",
       COUNT(*)                                           AS "Cancellations",
       SUM(was_refilled)                                  AS "Re-filled",
       SUM(refilled_via = 'waitlist')                     AS "Via waitlist offer",
       ROUND(AVG(was_refilled), 3)                        AS "Re-fill rate",
       SUM(CASE WHEN was_refilled THEN fee END)           AS "Revenue recovered"
FROM   v_cancellations
WHERE  start_at < (SELECT now_local FROM v_clock)
  [[AND clinic_code = {{clinic}}]]
GROUP  BY period
ORDER  BY period DESC;
