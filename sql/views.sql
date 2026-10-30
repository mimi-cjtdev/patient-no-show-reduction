-- Analytics views the Metabase dashboard is built on.
-- No-show rate = no-shows / (arrived + no-shows): cancellations are excluded, because a
-- cancellation is the outcome we want instead of a no-show (the slot can be offered again).

-- The clinic's current time, whatever time zone the database is being read in
DROP VIEW IF EXISTS v_clock;
CREATE VIEW v_clock AS
WITH shift AS (
    SELECT COALESCE((SELECT printf('%+d minutes', utc_offset_minutes) FROM clinic_clock), 'localtime') AS m
)
SELECT datetime('now', m) AS now_local,
       date('now', m)     AS today
FROM   shift;


DROP VIEW IF EXISTS v_appointments;
CREATE VIEW v_appointments AS
SELECT a.*,
       c.clinic_name,
       p.provider_name,
       p.role,
       vt.fee,
       date(a.start_at)                                                   AS appt_date,
       date(a.start_at, '-6 days', 'weekday 1')                           AS week_start,   -- Monday
       CAST(strftime('%w', a.start_at) AS INTEGER)                        AS weekday_num,  -- 0 = Sunday
       substr('SunMonTueWedThuFriSat', 1 + 3 * strftime('%w', a.start_at), 3) AS weekday,
       CAST(strftime('%H', a.start_at) AS INTEGER)                        AS start_hour,
       CAST(julianday(date(a.start_at)) - julianday(date(a.booked_at)) AS INTEGER) AS lead_days,
       -- reminders, confirm links and the waitlist apply to bookings made after the launch
       CASE WHEN a.booked_at >= (SELECT on_date FROM milestones LIMIT 1)
            THEN 'after launch' ELSE 'before launch' END                  AS period,
       a.status IN ('arrived', 'no_show')                                 AS has_outcome,
       a.status = 'no_show'                                               AS is_no_show,
       a.confirmed_at IS NOT NULL                                         AS was_confirmed
FROM   appointments a
JOIN   clinics     c  USING (clinic_code)
JOIN   providers   p  USING (provider_id)
JOIN   visit_types vt USING (visit_type);


-- One row per clinic per day: capacity, what happened, and what it cost
DROP VIEW IF EXISTS v_daily_clinic;
CREATE VIEW v_daily_clinic AS
WITH capacity AS (
    SELECT clinic_code, date(start_at) AS appt_date, COUNT(*) AS slots
    FROM   slots
    GROUP  BY 1, 2
), outcomes AS (
    SELECT clinic_code, appt_date,
           SUM(status = 'arrived')                         AS arrived,
           SUM(status = 'no_show')                         AS no_shows,
           SUM(status = 'cancelled')                       AS cancelled,
           SUM(CASE WHEN status = 'no_show' THEN fee END)  AS revenue_lost,
           SUM(CASE WHEN status = 'arrived' THEN fee END)  AS revenue
    FROM   v_appointments
    GROUP  BY 1, 2
)
SELECT c.clinic_code, cl.clinic_name, c.appt_date, c.slots,
       COALESCE(o.arrived, 0)      AS arrived,
       COALESCE(o.no_shows, 0)     AS no_shows,
       COALESCE(o.cancelled, 0)    AS cancelled,
       COALESCE(o.revenue, 0)      AS revenue,
       COALESCE(o.revenue_lost, 0) AS revenue_lost
FROM   capacity c
JOIN   clinics cl USING (clinic_code)
LEFT   JOIN outcomes o USING (clinic_code, appt_date);


-- Every cancellation, and whether someone else took the slot afterwards
DROP VIEW IF EXISTS v_cancellations;
CREATE VIEW v_cancellations AS
SELECT a.appointment_id, a.clinic_code, a.clinic_name, a.visit_type, a.start_at, a.cancelled_at, a.period,
       a.fee,
       ROUND((julianday(a.start_at) - julianday(a.cancelled_at)) * 24, 1) AS hours_notice,
       r.appointment_id                                                    AS refilled_by,
       r.booked_via                                                        AS refilled_via,
       r.appointment_id IS NOT NULL                                        AS was_refilled
FROM   v_appointments a
LEFT   JOIN appointments r
       ON  r.slot_id = a.slot_id
       AND r.appointment_id <> a.appointment_id
       AND r.status <> 'cancelled'
       AND r.booked_at >= a.cancelled_at
WHERE  a.status = 'cancelled'
  AND  a.cancelled_at IS NOT NULL;
