-- High-risk, unconfirmed (next 7 days)
-- Tab: Overview · Visualization: Number
-- Upcoming appointments the front desk should phone: high risk band and not confirmed yet.

SELECT COUNT(*) AS "High-risk, unconfirmed"
FROM   v_appointments
WHERE  start_at >= (SELECT now_local FROM v_clock)
  AND  appt_date < date((SELECT today FROM v_clock), '+7 days')
  AND  status = 'booked'
  AND  risk_band = 'high'
  [[AND clinic_code = {{clinic}}]];
