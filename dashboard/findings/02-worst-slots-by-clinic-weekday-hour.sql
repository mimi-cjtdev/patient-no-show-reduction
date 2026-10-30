-- Worst slots: clinic × weekday × hour
-- Tab: Findings · Visualization: Table (conditional formatting on No-show rate)
-- Every clinic-weekday-hour with enough appointments to judge, worst first.
-- Riverside's Monday 8am hour stands out at ~35%, about three times the network average.

SELECT clinic_name                                        AS "Clinic",
       weekday                                            AS "Day",
       printf('%d:00', start_hour)                        AS "Hour",
       SUM(has_outcome)                                   AS "Appointments",
       ROUND(1.0 * SUM(is_no_show) / SUM(has_outcome), 3) AS "No-show rate"
FROM   v_appointments
WHERE  has_outcome
  [[AND clinic_code = {{clinic}}]]
GROUP  BY clinic_name, weekday_num, weekday, start_hour
HAVING SUM(has_outcome) >= 100
ORDER  BY "No-show rate" DESC
LIMIT  15;
