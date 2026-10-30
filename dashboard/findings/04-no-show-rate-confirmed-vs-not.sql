-- No-show rate: confirmed vs not confirmed
-- Tab: Findings · Visualization: Bar
-- Since the launch. One click on "I'll be there" in a reminder email is the strongest signal we have.

SELECT CASE WHEN was_confirmed THEN 'Confirmed' ELSE 'Did not confirm' END AS "Patient",
       SUM(has_outcome)                                   AS "Appointments",
       ROUND(1.0 * SUM(is_no_show) / SUM(has_outcome), 3) AS "No-show rate"
FROM   v_appointments
WHERE  period = 'after launch'
  AND  has_outcome
  [[AND clinic_code = {{clinic}}]]
GROUP  BY 1
ORDER  BY 1;
