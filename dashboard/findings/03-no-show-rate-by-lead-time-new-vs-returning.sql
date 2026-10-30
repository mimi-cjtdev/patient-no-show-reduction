-- No-show rate by booking lead time: new vs returning patients
-- Tab: Findings · Visualization: Bar, grouped (x: Booked ahead, series: Patient)
-- New patients who book three or more weeks out are the least likely group to turn up.

SELECT CASE WHEN lead_days <= 2  THEN '1. 0–2 days'
            WHEN lead_days <= 14 THEN '2. 3–14 days'
            WHEN lead_days <= 20 THEN '3. 15–20 days'
            ELSE                      '4. 21+ days' END   AS "Booked ahead",
       CASE WHEN new_patient THEN 'New' ELSE 'Returning' END AS "Patient",
       SUM(has_outcome)                                   AS "Appointments",
       ROUND(1.0 * SUM(is_no_show) / SUM(has_outcome), 3) AS "No-show rate"
FROM   v_appointments
WHERE  has_outcome
  [[AND clinic_code = {{clinic}}]]
GROUP  BY 1, 2
ORDER  BY 1, 2;
