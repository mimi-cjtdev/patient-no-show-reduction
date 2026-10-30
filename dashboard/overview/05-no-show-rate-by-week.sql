-- No-show rate by week
-- Tab: Overview · Visualization: Line (x: Week, y: No-show rate), goal line at 0.10
-- Reminders, confirm links and the waitlist went live on 20 Jul (milestones table).

SELECT week_start                                         AS "Week",
       ROUND(1.0 * SUM(is_no_show) / SUM(has_outcome), 3) AS "No-show rate",
       SUM(has_outcome)                                   AS "Appointments"
FROM   v_appointments
WHERE  has_outcome
  [[AND clinic_code = {{clinic}}]]
GROUP  BY week_start
ORDER  BY week_start;
