"""Metrics API (API key) untuk Service Excellence Dashboard & CRK Daily Tracker (KPI CRM Lead)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..config import config
from ..db import get_db
from ..services import analytics
from ..utils import add_days, today_wib

router = APIRouter(prefix="/api/public-metrics", tags=["metrics"])


def check_key(x_api_key: str | None = Header(default=None)):
    if not x_api_key or x_api_key != config.metrics_api_key:
        raise HTTPException(401, {"code": "bad_key", "message": "API key tidak valid."})


@router.get("/ratings", dependencies=[Depends(check_key)])
async def ratings(from_: str | None = Query(default=None, alias="from"), to: str | None = None, db: AsyncIOMotorDatabase = Depends(get_db)):
    to = to or today_wib()
    from_ = from_ or add_days(to, -29)
    outlets = {o["_id"]: o async for o in db.outlets.find({})}
    agg: dict = {}
    async for f in db.feedback.find({"at": {"$gte": from_, "$lte": to + "T23:59:59Z"}}):
        o = outlets.get(f["outletId"])
        row = agg.setdefault(f["outletId"], {"outletCode": o["code"] if o else None, "outlet": o["name"] if o else None,
                                              "area": f.get("area"), "n": 0, "sum": 0, "ns": 0, "sums": 0, "puas": 0, "tags": {}})
        row["n"] += 1
        row["sum"] += f["rating"]
        row["puas"] += 1 if f["rating"] >= 4 else 0
        if f.get("service"):
            row["ns"] += 1
            row["sums"] += f["service"]
        for t in f.get("tags") or ([f["tag"]] if f.get("tag") else []):
            row["tags"][t] = row["tags"].get(t, 0) + 1
    out = [{**r, "avg": round(r["sum"] / r["n"], 2), "avgService": round(r["sums"] / r["ns"], 2) if r["ns"] else None,
            "csatPct": round(r["puas"] / r["n"] * 100, 1)} for r in agg.values()]
    for r in out:
        for k in ("sum", "ns", "sums", "puas"):
            r.pop(k)
    return {"from": from_, "to": to, "outlets": out}


@router.get("/crm", dependencies=[Depends(check_key)])
async def crm(date: str | None = None, db: AsyncIOMotorDatabase = Depends(get_db)):
    """KPI CRM Lead di Daily Tracker: member (member baru) & loyalty (redemption loyalty) pada tanggal tsb."""
    day = date or today_wib()
    member = await db.members.count_documents({"joinedDay": day})
    loyalty = await db.vouchers.count_documents({"status": "used", "usedAt": {"$gte": day, "$lte": day + "T23:59:59Z"}})
    stamps = await db.stamps.count_documents({"day": day, "granted": True})
    return {"date": day, "member": member, "loyalty": loyalty, "stamps": stamps}


@router.get("/promo", dependencies=[Depends(check_key)])
async def promo(code: str, from_: str | None = Query(default=None, alias="from"), to: str | None = None, db: AsyncIOMotorDatabase = Depends(get_db)):
    to = to or today_wib()
    from_ = from_ or add_days(to, -29)
    code = code.upper()
    per: dict = {}
    async for s in db.stamps.find({"day": {"$gte": from_, "$lte": to}, "granted": True}, {"outletCode": 1, "day": 1, "promoCode": 1}):
        key = (s.get("outletCode"), s["day"])
        row = per.setdefault(key, {"outletCode": key[0], "day": key[1], "stamps": 0, "promo": 0})
        row["stamps"] += 1
        if (s.get("promoCode") or "") == code:
            row["promo"] += 1
    rows = sorted(per.values(), key=lambda r: (r["day"], r["outletCode"] or ""))
    total = sum(r["stamps"] for r in rows)
    promo_n = sum(r["promo"] for r in rows)
    return {"code": code, "from": from_, "to": to, "stamps": total, "promoStamps": promo_n,
            "takeRatePct": round(promo_n / total * 100, 1) if total else None, "rows": rows}


@router.get("/summary", dependencies=[Depends(check_key)])
async def summary(from_: str | None = Query(default=None, alias="from"), to: str | None = None, area: str | None = None, db: AsyncIOMotorDatabase = Depends(get_db)):
    to = to or today_wib()
    from_ = from_ or add_days(to, -29)
    data = await analytics.summary(db, from_, to, area, {})
    return {"range": data["range"], "kpi": data["kpi"]}
