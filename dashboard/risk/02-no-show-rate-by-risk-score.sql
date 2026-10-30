-- No-show rate by risk score
-- Tab: Risk · Visualization: Line (x: Risk score, y: No-show rate)
-- Finer-grained version of the band chart, in steps of 10 points.

SELECT (risk_score / 10) * 10                             AS "Risk score",
       SUM(has_outcome)                                   AS "Appointments",
       ROUND(1.0 * SUM(is_no_show) / SUM(has_outcome), 3) AS "No-show rate"
FROM   v_appointments
WHERE  has_outcome
  [[AND clinic_code = {{clinic}}]]
GROUP  BY 1
HAVING SUM(has_outcome) >= 50
ORDER  BY 1;
