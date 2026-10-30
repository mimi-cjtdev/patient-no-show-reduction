"""
No-show risk score, worked out when an appointment is booked.

Deliberately simple rules rather than a model, so front desk staff can see why a
patient is flagged high risk. The weights come from the Apr–Jul phone-booking history
(see dashboard/findings/); the Risk tab checks every band against what actually happened.
"""
from datetime import datetime

BANDS = [(40, "high"), (20, "medium"), (0, "low")]


def score(start_at: datetime, booked_at: datetime, new_patient: bool, prior_no_shows: int):
    """Returns (score 0-100, band, reasons)."""
    points, reasons = 0, []
    if prior_no_shows:
        add = 30 if prior_no_shows == 1 else 45
        points += add
        reasons.append(f"{prior_no_shows} past no-show{'s' if prior_no_shows > 1 else ''}")
    if new_patient:
        points += 20
        reasons.append("new patient")
    lead_days = (start_at.date() - booked_at.date()).days
    if lead_days > 14:
        points += 15
        reasons.append(f"booked {lead_days} days ahead")
    if start_at.hour < 9:
        points += 10
        reasons.append("before 9am")
    if start_at.weekday() == 0:
        points += 5
        reasons.append("Monday")
    points = min(points, 100)
    band = next(name for floor, name in BANDS if points >= floor)
    return points, band, reasons
