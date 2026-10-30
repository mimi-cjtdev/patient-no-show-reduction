-- No-show rate (last 30 days)
-- Tab: Overview · Visualization: Number (%)
-- No-shows as a share of appointments that happened (arrived + no-show); cancellations don't count against it.
-- [[AND ... {{clinic}}]] is Metabase's optional filter: it only applies when the dashboard's Clinic filter is set.

SELECT ROUND(1.0 * SUM(is_no_show) / SUM(has_outcome), 3) AS "No-show rate"
FROM   v_appointments
WHERE  appt_date >= date((SELECT today FROM v_clock), '-30 days')
  AND  has_outcome
  [[AND clinic_code = {{clinic}}]];
