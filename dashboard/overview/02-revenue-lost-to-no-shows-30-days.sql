-- Revenue lost to no-shows (last 30 days)
-- Tab: Overview · Visualization: Number ($)
-- The visit fee of every slot that went unused because the patient didn't come.

SELECT SUM(fee) AS "Revenue lost"
FROM   v_appointments
WHERE  appt_date >= date((SELECT today FROM v_clock), '-30 days')
  AND  status = 'no_show'
  [[AND clinic_code = {{clinic}}]];
