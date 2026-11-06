"""Agregasi KPI untuk dashboard admin, digest, rekap mingguan, dan metrics API."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..utils import add_days, parse_iso, today_wib


def _pct(a: int | float, b: int | float) -> float | None:
    return round(a / b * 100, 1) if b else None


async def outlet_map(db: AsyncIOMotorDatabase, area_q: dict | None = None) -> dict[str, dict]:
    return {o["_id"]: o async for o in db.outlets.find(area_q or {})}


async def repeat_30d(db: AsyncIOMotorDatabase, outlet_ids: list[str] | None, from_day: str, to_day: str) -> dict:
    """Repeat 30D: member yang gabung ≥ 30 hari lalu (dalam rentang) dengan ≥ 2 kunjungan dalam 30 hari pertama."""
    cutoff = add_days(today_wib(), -30)
    q: dict = {"joinedDay": {"$gte": from_day, "$lte": min(to_day, cutoff)}}
    if outlet_ids is not None:
        q["firstOutletId"] = {"$in": outlet_ids}
    cohort = [m async for m in db.members.find(q, {"_id": 1, "joinedAt": 1})]
    if not cohort:
        return {"cohort": 0, "repeat": 0, "pct": None}
    ids = [m["_id"] for m in cohort]
    joined = {m["_id"]: parse_iso(m["joinedAt"]) for m in cohort}
    counts: Counter = Counter()
    async for s in db.stamps.find({"memberId": {"$in": ids}, "granted": True}, {"memberId": 1, "at": 1}):
        if parse_iso(s["at"]) <= joined[s["memberId"]] + timedelta(days=30):
            counts[s["memberId"]] += 1
    repeat = sum(1 for c in counts.values() if c >= 2)
    return {"cohort": len(cohort), "repeat": repeat, "pct": _pct(repeat, len(cohort))}


async def summary(db: AsyncIOMotorDatabase, from_day: str, to_day: str, area: str | None, area_q: dict) -> dict:
    oq = dict(area_q)
    if area:
        oq["area"] = area
    outlets = await outlet_map(db, oq)
    outlet_ids = list(outlets.keys())
    restrict = bool(area or area_q)

    stamp_q: dict = {"day": {"$gte": from_day, "$lte": to_day}, "granted": True}
    if restrict:
        stamp_q["outletId"] = {"$in": outlet_ids}
    stamps = [s async for s in db.stamps.find(stamp_q, {"memberId": 1, "outletId": 1, "day": 1, "hour": 1, "isNewMember": 1, "flags": 1, "promoCode": 1})]

    per_day: Counter = Counter()
    per_hour: Counter = Counter()
    per_outlet: Counter = Counter()
    members_per_outlet: dict[str, set] = defaultdict(set)
    weekly_new: Counter = Counter()
    weekly_ret: Counter = Counter()
    unique_members: set = set()
    promo_count = 0
    for s in stamps:
        per_day[s["day"]] += 1
        per_hour[s.get("hour", 0)] += 1
        per_outlet[s["outletId"]] += 1
        members_per_outlet[s["outletId"]].add(s["memberId"])
        unique_members.add(s["memberId"])
        wk = datetime.strptime(s["day"], "%Y-%m-%d").strftime("%G-W%V")
        if s.get("isNewMember"):
            weekly_new[wk] += 1
        else:
            weekly_ret[wk] += 1
        if s.get("promoCode"):
            promo_count += 1

    mem_q: dict = {"joinedDay": {"$gte": from_day, "$lte": to_day}}
    if restrict:
        mem_q["firstOutletId"] = {"$in": outlet_ids}
    new_members = await db.members.count_documents(mem_q)

    active_since = add_days(today_wib(), -30)
    act_q: dict = {"day": {"$gte": active_since}, "granted": True}
    if restrict:
        act_q["outletId"] = {"$in": outlet_ids}
    active_members = len(await db.stamps.distinct("memberId", act_q))

    # Transaksi manual per outlet-day → scan rate
    tx_q: dict = {"day": {"$gte": from_day, "$lte": to_day}}
    if restrict:
        tx_q["outletId"] = {"$in": outlet_ids}
    tx_total = 0
    async for t in db.outlet_transactions.find(tx_q):
        tx_total += int(t.get("transactions", 0))
    scan_rate = _pct(len(stamps), tx_total) if tx_total else None

    # Voucher
    vq_members: dict = {}
    if restrict:
        ids = [m["_id"] async for m in db.members.find({"firstOutletId": {"$in": outlet_ids}}, {"_id": 1})]
        vq_members = {"memberId": {"$in": ids}}
    v_range = {"createdAt": {"$gte": from_day, "$lte": to_day + "T23:59:59Z"}}
    reward_issued = await db.vouchers.count_documents({"type": "stamp_reward", **v_range, **vq_members})
    reward_used = await db.vouchers.count_documents({"type": "stamp_reward", "status": "used", **v_range, **vq_members})
    bl_issued = await db.vouchers.count_documents({"type": "balik_lagi", **v_range, **vq_members})
    bl_used = await db.vouchers.count_documents({"type": "balik_lagi", "status": "used", **v_range, **vq_members})

    # Rating
    fq: dict = {"at": {"$gte": from_day, "$lte": to_day + "T23:59:59Z"}}
    if restrict:
        fq["outletId"] = {"$in": outlet_ids}
    ratings = [f["rating"] async for f in db.feedback.find(fq, {"rating": 1})]
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

    rep = await repeat_30d(db, outlet_ids if restrict else None, from_day, to_day)

    # Hari buka per outlet (hari dengan ≥1 stamp) untuk stamps per open day
    open_days: dict[str, set] = defaultdict(set)
    for s in stamps:
        open_days[s["outletId"]].add(s["day"])
    outlet_rows = []
    for oid, o in outlets.items():
        n = per_outlet.get(oid, 0)
        od = len(open_days.get(oid, ()))
        outlet_rows.append({
            "id": oid, "code": o["code"], "name": o["name"], "area": o["area"],
            "stamps": n, "members": len(members_per_outlet.get(oid, ())),
            "openDays": od, "perOpenDay": round(n / od, 1) if od else 0,
        })
    outlet_rows.sort(key=lambda r: (-r["stamps"], r["name"]))

    days = []
    d = from_day
    while d <= to_day:
        days.append({"day": d, "stamps": per_day.get(d, 0)})
        d = add_days(d, 1)
    weeks = sorted(set(weekly_new) | set(weekly_ret))

    # Flag: member perlu dicek
    flagged = await flagged_members(db, outlet_ids if restrict else None)

    return {
        "range": {"from": from_day, "to": to_day, "area": area},
        "kpi": {
            "newMembers": new_members,
            "activeMembers30d": active_members,
            "stamps": len(stamps),
            "uniqueMembers": len(unique_members),
            "transactions": tx_total or None,
            "scanRatePct": scan_rate,
            "repeat30d": rep,
            "rewardIssued": reward_issued, "rewardUsed": reward_used, "redemptionPct": _pct(reward_used, reward_issued),
            "balikLagiIssued": bl_issued, "balikLagiUsed": bl_used, "balikLagiPct": _pct(bl_used, bl_issued),
            "avgRating": avg_rating, "ratings": len(ratings),
            "promoStamps": promo_count,
        },
        "charts": {
            "perDay": days,
            "perHour": [{"hour": h, "stamps": per_hour.get(h, 0)} for h in range(24)],
            "weekly": [{"week": w, "new": weekly_new.get(w, 0), "returning": weekly_ret.get(w, 0)} for w in weeks],
            "topOutlets": outlet_rows[:10],
            "bottomOutlets": sorted(outlet_rows, key=lambda r: (r["stamps"], r["name"]))[:10],
        },
        "outlets": outlet_rows,
        "flagged": flagged,
    }


async def flagged_members(db: AsyncIOMotorDatabase, outlet_ids: list[str] | None, days: int = 7) -> list[dict]:
    since = add_days(today_wib(), -days)
    q: dict = {"day": {"$gte": since}}
    if outlet_ids is not None:
        q["outletId"] = {"$in": outlet_ids}
    jauh: Counter = Counter()
    devices: Counter = Counter()
    async for s in db.stamps.find(q, {"memberId": 1, "flags": 1}):
        fl = s.get("flags") or []
        if "jauh" in fl:
            jauh[s["memberId"]] += 1
        if "device_baru" in fl:
            devices[s["memberId"]] += 1
    ids = {m for m, c in jauh.items() if c >= 3} | {m for m, c in devices.items() if c >= 3}
    out = []
    async for m in db.members.find({"_id": {"$in": list(ids)}}):
        out.append({
            "id": m["_id"], "phone": m["phone"], "name": m.get("name"), "blocked": m.get("blocked", False),
            "jauh7d": jauh.get(m["_id"], 0), "device7d": devices.get(m["_id"], 0), "visits": m.get("visits", 0),
        })
    return out


async def outlet_detail(db: AsyncIOMotorDatabase, outlet: dict, from_day: str, to_day: str) -> dict:
    stamps = [s async for s in db.stamps.find({"outletId": outlet["_id"], "day": {"$gte": from_day, "$lte": to_day}, "granted": True})]
    heat: dict[str, Counter] = defaultdict(Counter)
    for s in stamps:
        heat[s["day"]][s.get("hour", 0)] += 1
    feedback = [
        {"at": f["at"], "rating": f["rating"], "tag": f.get("tag"), "comment": f.get("comment")}
        async for f in db.feedback.find({"outletId": outlet["_id"]}).sort("at", -1).limit(50)
    ]
    ratings = [f["rating"] for f in feedback]
    tx = {t["day"]: t async for t in db.outlet_transactions.find({"outletId": outlet["_id"], "day": {"$gte": from_day, "$lte": to_day}})}
    members = len({s["memberId"] for s in stamps})
    return {
        "stamps": len(stamps), "members": members,
        "avgRating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "heatmap": [{"day": d, "hours": [heat[d].get(h, 0) for h in range(24)]} for d in sorted(heat)],
        "feedback": feedback,
        "transactions": [{"day": d, "transactions": t.get("transactions", 0), "revenue": t.get("revenue", 0)} for d, t in sorted(tx.items())],
        "flags": Counter(f for s in stamps for f in (s.get("flags") or [])),
    }


async def velocity_alerts(db: AsyncIOMotorDatabase) -> list[dict]:
    """Outlet dengan lonjakan stamp 10 menit terakhir > 3× rata-rata 30 hari (min 15)."""
    from ..utils import iso, now_utc
    now = now_utc()
    since10 = iso(now - timedelta(minutes=10))
    since30 = add_days(today_wib(), -30)
    recent: Counter = Counter()
    async for s in db.stamps.find({"at": {"$gte": since10}, "granted": True}, {"outletId": 1}):
        recent[s["outletId"]] += 1
    alerts = []
    for oid, n in recent.items():
        if n < 15:
            continue
        total30 = await db.stamps.count_documents({"outletId": oid, "day": {"$gte": since30}, "granted": True})
        avg10 = total30 / (30 * 24 * 6)
        if n > max(15, 3 * avg10):
            o = await db.outlets.find_one({"_id": oid})
            alerts.append({"outletId": oid, "outlet": o["name"] if o else oid, "last10min": n, "avg10min": round(avg10, 2)})
    return alerts
