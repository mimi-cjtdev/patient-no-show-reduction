-- Cancelled slots re-filled (last 30 days)
-- Tab: Overview · Visualization: Number (%)
-- Share of cancelled appointments whose slot someone else then booked (mostly through a waitlist offer).

SELECT ROUND(AVG(was_refilled), 3) AS "Cancelled slots re-filled"
FROM   v_cancellations
WHERE  date(start_at) >= date((SELECT today FROM v_clock), '-30 days')
  AND  start_at < (SELECT now_local FROM v_clock)
  [[AND clinic_code = {{clinic}}]];
