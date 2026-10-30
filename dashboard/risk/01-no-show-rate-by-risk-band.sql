-- No-show rate by risk band
-- Tab: Risk · Visualization: Bar
-- Checks the booking-time risk score (app/risk.py) against what actually happened: each band
-- should no-show more often than the one below it.

SELECT risk_band                                          AS "Risk band",
       SUM(has_outcome)                                   AS "Appointments",
       ROUND(1.0 * SUM(is_no_show) / SUM(has_outcome), 3) AS "No-show rate"
FROM   v_appointments
WHERE  has_outcome
  [[AND clinic_code = {{clinic}}]]
GROUP  BY risk_band
ORDER  BY CASE risk_band WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END;
