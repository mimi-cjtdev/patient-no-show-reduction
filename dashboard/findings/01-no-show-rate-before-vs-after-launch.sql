-- No-show rate before vs after the launch
-- Tab: Findings · Visualization: Bar
-- Bookings made before 20 Jul (phone only, no reminders) vs after (webapp, 72h + 24h email reminders,
-- confirm/cancel links, waitlist).

SELECT period                                             AS "Booked",
       SUM(has_outcome)                                   AS "Appointments",
       SUM(is_no_show)                                    AS "No-shows",
       ROUND(1.0 * SUM(is_no_show) / SUM(has_outcome), 3) AS "No-show rate",
       ROUND(1.0 * SUM(status = 'cancelled') / COUNT(*), 3) AS "Cancellation rate"
FROM   v_appointments
WHERE  start_at < (SELECT now_local FROM v_clock)
  [[AND clinic_code = {{clinic}}]]
GROUP  BY period
ORDER  BY period DESC;
