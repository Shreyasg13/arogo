"""
db/travel.py — I2 travel supply planner. Given a trip's start and end dates,
work out how many pills of each medicine you'll need while away, whether your
current stock covers it, and which medicines to refill before you leave.

Everything is derived from the medicine's own schedule and stock count. PRN
(as-needed) medicines are excluded — there's no fixed rate to predict, and
guessing one would be exactly the kind of invented number Arogo doesn't show.
"""
import datetime as _dt

from .core import valid_date, user_today
from .medicines import list_medicines


def _count_active_days(start, end, med):
    """How many days in [start, end] this med is actually taken, honouring a
    weekday schedule or an N-day interval."""
    sd = med.get("schedule_days")     # None or list[int], Mon=0
    iv = med.get("interval_days")     # None or int
    total_days = (end - start).days + 1

    if iv and iv > 1:
        # Anchor the cycle to the med's own start date when known, so the phase
        # lines up with reality; otherwise assume a dose on the trip's first day.
        anchor = start
        sdate = med.get("start_date")
        if sdate and valid_date(sdate):
            try:
                anchor = _dt.date.fromisoformat(sdate)
            except ValueError:
                anchor = start
        return sum(1 for i in range(total_days)
                   if ((start + _dt.timedelta(days=i)) - anchor).days % iv == 0)

    if sd:
        sset = {d for d in sd if 0 <= d < 7}
        return sum(1 for i in range(total_days)
                   if (start + _dt.timedelta(days=i)).weekday() in sset)

    return total_days   # plain daily


def plan_travel_supply(start_date: str, end_date: str) -> dict:
    """Return per-medicine pill needs for the trip plus a refill-before-you-go
    list. `available` is None when a medicine isn't tracking its pill count —
    we can show what to pack but can't judge a shortfall."""
    if not valid_date(start_date) or not valid_date(end_date):
        return {"ok": False, "reason": "bad_dates"}
    try:
        start = _dt.date.fromisoformat(start_date)
        end = _dt.date.fromisoformat(end_date)
    except ValueError:
        return {"ok": False, "reason": "bad_dates"}
    if end < start:
        return {"ok": False, "reason": "end_before_start"}
    if (end - start).days > 365:
        return {"ok": False, "reason": "trip_too_long"}

    trip_days = (end - start).days + 1
    items, refill_needed = [], []

    for med in list_medicines():
        if not med.get("active", True):
            continue
        if med.get("frequency") == "as_needed" or not (med.get("times") or []):
            continue   # PRN: no predictable rate

        doses_per_day = max(len(med.get("times") or []), 1)
        per_dose = med.get("pills_per_dose") or 1
        active_days = _count_active_days(start, end, med)
        needed = active_days * doses_per_day * per_dose

        pc = med.get("pill_count")
        available = None if pc is None else int(pc)
        shortfall = None if available is None else max(0, needed - available)

        item = {
            "id": med["id"],
            "name": med.get("name") or "Medicine",
            "needed": int(needed),
            "available": available,
            "shortfall": shortfall,
            "covered": None if available is None else shortfall == 0,
        }
        items.append(item)
        if shortfall and shortfall > 0:
            refill_needed.append({"name": item["name"], "shortfall": shortfall,
                                  "needed": item["needed"], "available": available})

    items.sort(key=lambda x: ((x["shortfall"] or 0) == 0, x["name"].lower()))
    refill_needed.sort(key=lambda x: -x["shortfall"])

    return {
        "ok": True,
        "start": start_date,
        "end": end_date,
        "trip_days": trip_days,
        "items": items,
        "total_pills": sum(i["needed"] for i in items),
        "refill_needed": refill_needed,
        "all_covered": all(i["covered"] is not False for i in items),
    }
