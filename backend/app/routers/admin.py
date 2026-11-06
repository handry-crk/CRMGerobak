"""Dashboard admin: ringkasan, outlet, member, voucher/campaign, rating, QR & stiker, pengaturan, job."""
from __future__ import annotations

import csv
import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from ..config import config
from ..db import ADMIN_ROLES, AREAS, DEFAULT_SETTINGS, get_db, get_settings
from ..security import (
    admin_login, admin_public, area_filter, can_see_full_phone, current_admin, new_pin_hash, require_roles,
)
from ..services import analytics
from ..services.jobs import JOBS
from ..services.sticker import sticker_pdf, tentcard_pdf
from ..services.voucher import create_campaign_vouchers, create_reward_voucher, voucher_public
from ..utils import add_days, iso, mask_phone, new_id, new_qr_token, normalize_phone, now_utc, today_wib

router = APIRouter(prefix="/api/admin", tags=["admin"])
PRIV = require_roles("CRM Lead", "Manager")
LEAD = require_roles("CRM Lead")
WRITE = require_roles("CRM Lead", "Manager", "Area")


async def audit(db, user: dict, action: str, target: str | None = None, detail: dict | None = None):
    await db.audit_log.insert_one({
        "_id": new_id("aud"), "who": user["name"], "whoId": user["_id"], "action": action,
        "target": target, "detail": detail or {}, "at": iso(now_utc()),
    })


def outlet_url(qr_token: str) -> str:
    return f"{config.public_base_url.rstrip('/')}/s/{qr_token}"


def outlet_admin(o: dict) -> dict:
    return {
        "id": o["_id"], "code": o["code"], "name": o["name"], "area": o["area"], "city": o.get("city"),
        "address": o.get("address"), "lat": o.get("lat"), "lng": o.get("lng"), "priceZone": o.get("priceZone"),
        "qrToken": o["qrToken"], "url": outlet_url(o["qrToken"]), "active": o.get("active", True),
        "createdAt": o.get("createdAt"), "qrRotatedAt": o.get("qrRotatedAt"),
    }


def member_admin(m: dict, full_phone: bool) -> dict:
    return {
        "id": m["_id"], "phone": m["phone"] if full_phone else mask_phone(m["phone"]), "name": m.get("name"),
        "city": m.get("city"), "source": m.get("source"), "joinedAt": m.get("joinedAt"), "joinedDay": m.get("joinedDay"),
        "visits": m.get("visits", 0), "stampsActive": m.get("stampsActive", 0), "stampsTotal": m.get("stampsTotal", 0),
        "rewardsEarned": m.get("rewardsEarned", 0), "lastVisitAt": m.get("lastVisitAt"), "optIn": m.get("optIn", True),
        "blocked": m.get("blocked", False), "devices": len(m.get("deviceTokens") or []), "firstOutletId": m.get("firstOutletId"),
    }


# ---------- Auth ----------

class LoginIn(BaseModel):
    name: str
    pin: str


@router.post("/login")
async def login(body: LoginIn, db: AsyncIOMotorDatabase = Depends(get_db)):
    return await admin_login(db, body.name.strip(), body.pin.strip())


@router.get("/login/names")
async def login_names(db: AsyncIOMotorDatabase = Depends(get_db)):
    return [u["name"] async for u in db.admin_users.find({"active": True}, {"name": 1}).sort("name", 1)]


@router.get("/me")
async def me(user: dict = Depends(current_admin)):
    return admin_public(user)


@router.get("/meta")
async def meta(user: dict = Depends(current_admin)):
    return {"areas": list(AREAS), "roles": list(ADMIN_ROLES), "publicBaseUrl": config.public_base_url}


# ---------- Ringkasan ----------

@router.get("/summary")
async def summary(
    from_: str | None = Query(default=None, alias="from"), to: str | None = None, area: str | None = None,
    user: dict = Depends(current_admin), db: AsyncIOMotorDatabase = Depends(get_db),
):
    to = to or today_wib()
    from_ = from_ or add_days(to, -29)
    data = await analytics.summary(db, from_, to, area, area_filter(user))
    if not can_see_full_phone(user):
        for f in data["flagged"]:
            f["phone"] = mask_phone(f["phone"])
    data["velocity"] = await analytics.velocity_alerts(db)
    return data


# ---------- Outlet ----------

class OutletIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=2, max_length=80)
    area: str
    city: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    priceZone: str = "bandung"
    active: bool = True


class TxIn(BaseModel):
    day: str
    transactions: int = Field(ge=0)
    revenue: int = Field(ge=0, default=0)


@router.get("/outlets")
async def list_outlets(user: dict = Depends(current_admin), db: AsyncIOMotorDatabase = Depends(get_db)):
    return [outlet_admin(o) async for o in db.outlets.find(area_filter(user)).sort("code", 1)]


@router.post("/outlets")
async def create_outlet(body: OutletIn, user: dict = Depends(PRIV), db: AsyncIOMotorDatabase = Depends(get_db)):
    if body.area not in AREAS:
        raise HTTPException(422, {"code": "bad_area", "message": "Area tidak dikenal."})
    if await db.outlets.find_one({"code": body.code.upper()}):
        raise HTTPException(409, {"code": "dup_code", "message": "Kode outlet sudah ada."})
    doc = {"_id": new_id("out"), **body.model_dump(), "code": body.code.upper(), "qrToken": new_qr_token(),
           "oldTokens": [], "createdAt": iso(now_utc())}
    await db.outlets.insert_one(doc)
    await audit(db, user, "outlet.create", doc["_id"], {"code": doc["code"]})
    return outlet_admin(doc)


@router.put("/outlets/{outlet_id}")
async def update_outlet(outlet_id: str, body: OutletIn, user: dict = Depends(PRIV), db: AsyncIOMotorDatabase = Depends(get_db)):
    o = await db.outlets.find_one({"_id": outlet_id})
    if not o:
        raise HTTPException(404, {"code": "not_found", "message": "Outlet tidak ditemukan."})
    dup = await db.outlets.find_one({"code": body.code.upper(), "_id": {"$ne": outlet_id}})
    if dup:
        raise HTTPException(409, {"code": "dup_code", "message": "Kode outlet sudah ada."})
    await db.outlets.update_one({"_id": outlet_id}, {"$set": {**body.model_dump(), "code": body.code.upper()}})
    await audit(db, user, "outlet.update", outlet_id, body.model_dump())
    return outlet_admin(await db.outlets.find_one({"_id": outlet_id}))


@router.get("/outlets/{outlet_id}")
async def outlet_detail(outlet_id: str, from_: str | None = Query(default=None, alias="from"), to: str | None = None,
                        user: dict = Depends(current_admin), db: AsyncIOMotorDatabase = Depends(get_db)):
    o = await db.outlets.find_one({"_id": outlet_id, **area_filter(user)})
    if not o:
        raise HTTPException(404, {"code": "not_found", "message": "Outlet tidak ditemukan."})
    to = to or today_wib()
    from_ = from_ or add_days(to, -29)
    detail = await analytics.outlet_detail(db, o, from_, to)
    return {"outlet": outlet_admin(o), **detail}


@router.post("/outlets/{outlet_id}/rotate-qr")
async def rotate_qr(outlet_id: str, user: dict = Depends(PRIV), db: AsyncIOMotorDatabase = Depends(get_db)):
    o = await db.outlets.find_one({"_id": outlet_id})
    if not o:
        raise HTTPException(404, {"code": "not_found", "message": "Outlet tidak ditemukan."})
    token = new_qr_token()
    await db.outlets.update_one({"_id": outlet_id}, {"$set": {"qrToken": token, "qrRotatedAt": iso(now_utc())},
                                                    "$push": {"oldTokens": o["qrToken"]}})
    await audit(db, user, "outlet.rotate_qr", outlet_id, {"old": o["qrToken"], "new": token})
    return outlet_admin(await db.outlets.find_one({"_id": outlet_id}))


@router.post("/outlets/{outlet_id}/transactions")
async def set_transactions(outlet_id: str, body: TxIn, user: dict = Depends(WRITE), db: AsyncIOMotorDatabase = Depends(get_db)):
    o = await db.outlets.find_one({"_id": outlet_id, **area_filter(user)})
    if not o:
        raise HTTPException(404, {"code": "not_found", "message": "Outlet tidak ditemukan."})
    await db.outlet_transactions.update_one(
        {"outletId": outlet_id, "day": body.day},
        {"$set": {"transactions": body.transactions, "revenue": body.revenue, "updatedBy": user["name"], "updatedAt": iso(now_utc())}},
        upsert=True,
    )
    return {"ok": True}


@router.get("/outlets/{outlet_id}/sticker.pdf")
async def sticker(outlet_id: str, variant: str = "a6", user: dict = Depends(current_admin), db: AsyncIOMotorDatabase = Depends(get_db)):
    o = await db.outlets.find_one({"_id": outlet_id, **area_filter(user)})
    if not o:
        raise HTTPException(404, {"code": "not_found", "message": "Outlet tidak ditemukan."})
    settings = await get_settings(db)
    fn = tentcard_pdf if variant == "tent" else sticker_pdf
    pdf = fn(o, outlet_url(o["qrToken"]), settings)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="stiker-{o["code"]}-{variant}.pdf"'})


@router.get("/stickers.zip")
async def stickers_zip(area: str | None = None, user: dict = Depends(current_admin), db: AsyncIOMotorDatabase = Depends(get_db)):
    q = area_filter(user)
    if area:
        q["area"] = area
    settings = await get_settings(db)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        async for o in db.outlets.find({**q, "active": True}):
            z.writestr(f"stiker-{o['code']}.pdf", sticker_pdf(o, outlet_url(o["qrToken"]), settings))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="stiker-{area or "semua"}.zip"'})


@router.post("/outlets/import")
async def import_outlets(file: UploadFile, user: dict = Depends(PRIV), db: AsyncIOMotorDatabase = Depends(get_db)):
    """CSV: code,name,area,city,address,lat,lng,priceZone (koma atau titik koma)."""
    raw = (await file.read()).decode("utf-8-sig")
    dialect = csv.Sniffer().sniff(raw[:2048], delimiters=";,")
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    created, updated, errors = 0, 0, []
    for i, row in enumerate(reader, start=2):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        code = row.get("code", "").upper()
        if not code or not row.get("name") or row.get("area") not in AREAS:
            errors.append(f"Baris {i}: code/name/area tidak valid")
            continue
        doc = {
            "name": row["name"], "area": row["area"], "city": row.get("city") or row["area"], "address": row.get("address"),
            "lat": float(row["lat"].replace(",", ".")) if row.get("lat") else None,
            "lng": float(row["lng"].replace(",", ".")) if row.get("lng") else None,
            "priceZone": row.get("priceZone") or ("bandung" if row["area"] == "Bandung" else "jabodetabek"), "active": True,
        }
        existing = await db.outlets.find_one({"code": code})
        if existing:
            await db.outlets.update_one({"_id": existing["_id"]}, {"$set": doc})
            updated += 1
        else:
            await db.outlets.insert_one({"_id": new_id("out"), "code": code, **doc, "qrToken": new_qr_token(), "oldTokens": [], "createdAt": iso(now_utc())})
            created += 1
    await audit(db, user, "outlet.import", None, {"created": created, "updated": updated})
    return {"created": created, "updated": updated, "errors": errors}


# ---------- Member ----------

@router.get("/members")
async def list_members(q: str | None = None, flagged: bool = False, page: int = 1, size: int = 50,
                       user: dict = Depends(current_admin), db: AsyncIOMotorDatabase = Depends(get_db)):
    query: dict = {}
    af = area_filter(user)
    if af:
        ids = [o["_id"] async for o in db.outlets.find(af, {"_id": 1})]
        query["firstOutletId"] = {"$in": ids}
    if q:
        phone = normalize_phone(q)
        if phone:
            query["phone"] = phone
        else:
            query["$or"] = [{"name": {"$regex": q, "$options": "i"}}, {"phone": {"$regex": q.replace("+", "\\+")}}]
    total = await db.members.count_documents(query)
    cur = db.members.find(query).sort("lastVisitAt", -1).skip((page - 1) * size).limit(size)
    full = can_see_full_phone(user)
    return {"total": total, "page": page, "items": [member_admin(m, full) async for m in cur]}


@router.get("/members/{member_id}")
async def member_detail(member_id: str, user: dict = Depends(current_admin), db: AsyncIOMotorDatabase = Depends(get_db)):
    m = await db.members.find_one({"_id": member_id})
    if not m:
        raise HTTPException(404, {"code": "not_found", "message": "Member tidak ditemukan."})
    outlets = {o["_id"]: o["name"] async for o in db.outlets.find({}, {"name": 1})}
    stamps = [{"at": s["at"], "outlet": outlets.get(s["outletId"], s.get("outletCode")), "granted": s["granted"],
               "reason": s.get("reason"), "flags": s.get("flags", []), "distanceM": s.get("distanceM"), "promoCode": s.get("promoCode")}
              async for s in db.stamps.find({"memberId": member_id}).sort("at", -1).limit(100)]
    vouchers = [voucher_public(v) async for v in db.vouchers.find({"memberId": member_id}).sort("createdAt", -1)]
    feedback = [{"at": f["at"], "outlet": outlets.get(f["outletId"]), "rating": f["rating"], "tag": f.get("tag"), "comment": f.get("comment")}
                async for f in db.feedback.find({"memberId": member_id}).sort("at", -1)]
    return {"member": member_admin(m, can_see_full_phone(user)), "stamps": stamps, "vouchers": vouchers, "feedback": feedback}


class AdjustIn(BaseModel):
    delta: int = Field(ge=-5, le=5)
    reason: str = Field(min_length=3, max_length=200)


class ManualVoucherIn(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    valueRp: int = Field(ge=0)
    minSpendRp: int = Field(ge=0, default=0)
    validDays: int = Field(ge=1, le=90, default=14)
    reason: str = Field(min_length=3, max_length=200)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


@router.post("/members/{member_id}/adjust-stamps")
async def adjust_stamps(member_id: str, body: AdjustIn, user: dict = Depends(LEAD), db: AsyncIOMotorDatabase = Depends(get_db)):
    m = await db.members.find_one({"_id": member_id})
    if not m:
        raise HTTPException(404, {"code": "not_found", "message": "Member tidak ditemukan."})
    settings = await get_settings(db)
    new_active = int(m.get("stampsActive", 0)) + body.delta
    reward = None
    if new_active >= int(settings["stampsPerReward"]):
        reward = await create_reward_voucher(db, member_id, settings)
        new_active -= int(settings["stampsPerReward"])
    new_active = max(0, new_active)
    await db.members.update_one({"_id": member_id}, {"$set": {"stampsActive": new_active}, "$inc": {"stampsTotal": max(body.delta, 0)}})
    await audit(db, user, "member.adjust_stamps", member_id, {"delta": body.delta, "reason": body.reason, "reward": bool(reward)})
    return {"ok": True, "stampsActive": new_active, "rewardIssued": bool(reward)}


@router.post("/members/{member_id}/voucher")
async def manual_voucher(member_id: str, body: ManualVoucherIn, user: dict = Depends(LEAD), db: AsyncIOMotorDatabase = Depends(get_db)):
    if not await db.members.find_one({"_id": member_id}):
        raise HTTPException(404, {"code": "not_found", "message": "Member tidak ditemukan."})
    today = today_wib()
    doc = {"_id": new_id("vch"), "memberId": member_id, "type": "campaign", "title": body.title, "valueRp": body.valueRp,
           "minSpendRp": body.minSpendRp, "validFrom": today, "validTo": add_days(today, body.validDays), "status": "active",
           "campaignCode": "MANUAL", "createdAt": iso(now_utc()), "createdBy": user["name"]}
    await db.vouchers.insert_one(doc)
    await audit(db, user, "member.manual_voucher", member_id, {"title": body.title, "reason": body.reason})
    return voucher_public(doc)


@router.post("/members/{member_id}/block")
async def block_member(member_id: str, body: ReasonIn, user: dict = Depends(LEAD), db: AsyncIOMotorDatabase = Depends(get_db)):
    m = await db.members.find_one({"_id": member_id})
    if not m:
        raise HTTPException(404, {"code": "not_found", "message": "Member tidak ditemukan."})
    new_val = not m.get("blocked", False)
    await db.members.update_one({"_id": member_id}, {"$set": {"blocked": new_val}})
    await audit(db, user, "member.block" if new_val else "member.unblock", member_id, {"reason": body.reason})
    return {"ok": True, "blocked": new_val}


@router.delete("/members/{member_id}")
async def delete_member(member_id: str, reason: str = Query(min_length=3), user: dict = Depends(LEAD), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Hapus = anonimkan (nomor diganti hash, perangkat dilepas); stamp agregat tetap untuk statistik."""
    m = await db.members.find_one({"_id": member_id})
    if not m:
        raise HTTPException(404, {"code": "not_found", "message": "Member tidak ditemukan."})
    await db.members.update_one({"_id": member_id}, {"$set": {
        "phone": f"deleted:{member_id}", "name": None, "deviceTokens": [], "optIn": False,
        "blocked": True, "deletedAt": iso(now_utc())}})
    await db.vouchers.update_many({"memberId": member_id, "status": {"$in": ["active", "scheduled"]}}, {"$set": {"status": "expired"}})
    await audit(db, user, "member.delete", member_id, {"reason": reason})
    return {"ok": True}


# ---------- Voucher & campaign ----------

class CampaignIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    title: str = Field(min_length=3, max_length=80)
    valueRp: int = Field(ge=0)
    minSpendRp: int = Field(ge=0, default=0)
    validFrom: str
    validTo: str
    segment: str = "semua"  # semua | area | dorman30 | minVisits
    area: str | None = None
    minVisits: int | None = None


@router.get("/vouchers/stats")
async def voucher_stats(user: dict = Depends(current_admin), db: AsyncIOMotorDatabase = Depends(get_db)):
    out: dict = {}
    async for row in db.vouchers.aggregate([{"$group": {"_id": {"type": "$type", "status": "$status"}, "n": {"$sum": 1}}}]):
        out.setdefault(row["_id"]["type"], {})[row["_id"]["status"]] = row["n"]
    campaigns = [c async for c in db.campaigns.find({}).sort("createdAt", -1)]
    for c in campaigns:
        c["id"] = c.pop("_id")
        c["used"] = await db.vouchers.count_documents({"campaignCode": c["code"], "status": "used"})
    return {"byType": out, "campaigns": campaigns}


@router.post("/campaigns")
async def create_campaign(body: CampaignIn, user: dict = Depends(PRIV), db: AsyncIOMotorDatabase = Depends(get_db)):
    code = body.code.upper()
    if await db.campaigns.find_one({"code": code}):
        raise HTTPException(409, {"code": "dup", "message": "Kode campaign sudah ada."})
    q: dict = {"blocked": {"$ne": True}, "optIn": True}
    if body.segment == "area":
        ids = [o["_id"] async for o in db.outlets.find({"area": body.area}, {"_id": 1})]
        q["firstOutletId"] = {"$in": ids}
    elif body.segment == "dorman30":
        q["lastVisitAt"] = {"$lt": add_days(today_wib(), -30)}
    elif body.segment == "minVisits":
        q["visits"] = {"$gte": int(body.minVisits or 1)}
    member_ids = [m["_id"] async for m in db.members.find(q, {"_id": 1})]
    camp = {"_id": new_id("cmp"), **body.model_dump(), "code": code, "issued": len(member_ids), "createdAt": iso(now_utc()), "createdBy": user["name"]}
    await db.campaigns.insert_one(camp)
    n = await create_campaign_vouchers(db, camp, member_ids)
    await audit(db, user, "campaign.create", camp["_id"], {"code": code, "issued": n})
    camp["id"] = camp.pop("_id")
    return camp


# ---------- Rating ----------

@router.get("/feedback")
async def list_feedback(from_: str | None = Query(default=None, alias="from"), to: str | None = None, max_rating: int | None = None,
                        user: dict = Depends(current_admin), db: AsyncIOMotorDatabase = Depends(get_db)):
    to = to or today_wib()
    from_ = from_ or add_days(to, -29)
    q: dict = {"at": {"$gte": from_, "$lte": to + "T23:59:59Z"}, **area_filter(user)}
    if max_rating:
        q["rating"] = {"$lte": max_rating}
    outlets = {o["_id"]: o["name"] async for o in db.outlets.find({}, {"name": 1})}
    items, per_outlet, dist, tags = [], {}, {i: 0 for i in range(1, 6)}, {}
    async for f in db.feedback.find(q).sort("at", -1).limit(500):
        items.append({"at": f["at"], "outlet": outlets.get(f["outletId"]), "area": f.get("area"), "rating": f["rating"], "tag": f.get("tag"), "comment": f.get("comment")})
        po = per_outlet.setdefault(f["outletId"], {"outlet": outlets.get(f["outletId"]), "n": 0, "sum": 0})
        po["n"] += 1
        po["sum"] += f["rating"]
        dist[f["rating"]] += 1
        if f.get("tag"):
            tags[f["tag"]] = tags.get(f["tag"], 0) + 1
    per = sorted(({"outlet": v["outlet"], "n": v["n"], "avg": round(v["sum"] / v["n"], 2)} for v in per_outlet.values()), key=lambda r: -r["n"])
    return {"items": items, "perOutlet": per, "distribution": dist, "tags": tags}


# ---------- Pengaturan & admin users ----------

@router.get("/settings")
async def read_settings(user: dict = Depends(PRIV), db: AsyncIOMotorDatabase = Depends(get_db)):
    s = await get_settings(db)
    s.pop("_id", None)
    return s


@router.put("/settings")
async def write_settings(body: dict, user: dict = Depends(LEAD), db: AsyncIOMotorDatabase = Depends(get_db)):
    allowed = {k for k in DEFAULT_SETTINGS if k != "_id"}
    upd = {k: v for k, v in body.items() if k in allowed}
    if "welcomeVoucher" in upd:
        upd["welcomeVoucher"] = {**DEFAULT_SETTINGS["welcomeVoucher"], **(upd["welcomeVoucher"] or {})}
    for k in ("stampsPerReward", "maxStampsPerOutletPerDay", "maxStampsPerDay", "minMinutesBetweenStamps", "geofenceM", "rewardVoucherValidDays", "redeemCountdownSec"):
        if k in upd:
            try:
                upd[k] = int(upd[k])
            except (TypeError, ValueError):
                raise HTTPException(422, {"code": "bad_value", "message": f"{k} harus angka."})
    if upd.get("stampsPerReward", 5) < 2:
        raise HTTPException(422, {"code": "bad_value", "message": "stampsPerReward minimal 2."})
    await db.settings.update_one({"_id": "main"}, {"$set": upd}, upsert=True)
    await audit(db, user, "settings.update", None, upd)
    s = await get_settings(db)
    s.pop("_id", None)
    return s


class AdminUserIn(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    role: str
    areas: list[str] = []
    pin: str | None = None
    email: str | None = None


@router.get("/users")
async def list_users(user: dict = Depends(PRIV), db: AsyncIOMotorDatabase = Depends(get_db)):
    return [{**admin_public(u), "email": u.get("email")} async for u in db.admin_users.find({}).sort("name", 1)]


@router.post("/users")
async def create_user(body: AdminUserIn, user: dict = Depends(LEAD), db: AsyncIOMotorDatabase = Depends(get_db)):
    if body.role not in ADMIN_ROLES:
        raise HTTPException(422, {"code": "bad_role", "message": "Role tidak dikenal."})
    if await db.admin_users.find_one({"name": body.name}):
        raise HTTPException(409, {"code": "dup", "message": "Nama sudah dipakai."})
    doc = {"_id": new_id("adm"), "name": body.name, "role": body.role, "areas": body.areas, "email": body.email,
           "pinHash": new_pin_hash(body.pin or "1234"), "active": True, "failedAttempts": 0, "lockedUntil": None, "createdAt": iso(now_utc())}
    await db.admin_users.insert_one(doc)
    await audit(db, user, "user.create", doc["_id"], {"name": body.name, "role": body.role})
    return admin_public(doc)


@router.put("/users/{user_id}")
async def update_user(user_id: str, body: AdminUserIn, user: dict = Depends(LEAD), db: AsyncIOMotorDatabase = Depends(get_db)):
    if body.role not in ADMIN_ROLES:
        raise HTTPException(422, {"code": "bad_role", "message": "Role tidak dikenal."})
    upd = {"name": body.name, "role": body.role, "areas": body.areas, "email": body.email}
    if body.pin:
        upd["pinHash"] = new_pin_hash(body.pin)
        upd["failedAttempts"] = 0
        upd["lockedUntil"] = None
    res = await db.admin_users.update_one({"_id": user_id}, {"$set": upd})
    if not res.matched_count:
        raise HTTPException(404, {"code": "not_found", "message": "User tidak ditemukan."})
    await audit(db, user, "user.update", user_id, {"role": body.role, "pinReset": bool(body.pin)})
    return admin_public(await db.admin_users.find_one({"_id": user_id}))


@router.post("/users/{user_id}/toggle-active")
async def toggle_user(user_id: str, user: dict = Depends(LEAD), db: AsyncIOMotorDatabase = Depends(get_db)):
    u = await db.admin_users.find_one({"_id": user_id})
    if not u:
        raise HTTPException(404, {"code": "not_found", "message": "User tidak ditemukan."})
    if u["_id"] == user["_id"]:
        raise HTTPException(400, {"code": "self", "message": "Tidak bisa menonaktifkan akun sendiri."})
    await db.admin_users.update_one({"_id": user_id}, {"$set": {"active": not u.get("active", True)}})
    await audit(db, user, "user.toggle_active", user_id)
    return admin_public(await db.admin_users.find_one({"_id": user_id}))


@router.get("/audit")
async def audit_list(user: dict = Depends(PRIV), db: AsyncIOMotorDatabase = Depends(get_db)):
    return [{**a, "id": a.pop("_id")} async for a in db.audit_log.find({}).sort("at", -1).limit(200)]


# ---------- Job & export ----------

@router.post("/jobs/{job}/run")
async def run_job(job: str, user: dict = Depends(PRIV)):
    fn = JOBS.get(job)
    if not fn:
        raise HTTPException(404, {"code": "not_found", "message": "Job tidak dikenal."})
    return await fn(force=True)


def _csv(rows: list[dict], headers: list[str]) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.DictWriter(buf, fieldnames=headers, delimiter=";", extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8")


@router.get("/export/{kind}.csv")
async def export(kind: str, from_: str | None = Query(default=None, alias="from"), to: str | None = None,
                 user: dict = Depends(PRIV), db: AsyncIOMotorDatabase = Depends(get_db)):
    to = to or today_wib()
    from_ = from_ or add_days(to, -89)
    outlets = {o["_id"]: o["code"] async for o in db.outlets.find({}, {"code": 1})}
    if kind == "members":
        rows = [{"id": m["_id"], "phone": m["phone"], "name": m.get("name"), "city": m.get("city"), "source": m.get("source"),
                 "joinedAt": m.get("joinedAt"), "firstOutlet": outlets.get(m.get("firstOutletId")), "visits": m.get("visits", 0),
                 "stampsActive": m.get("stampsActive", 0), "stampsTotal": m.get("stampsTotal", 0), "rewardsEarned": m.get("rewardsEarned", 0),
                 "lastVisitAt": m.get("lastVisitAt"), "optIn": m.get("optIn", True), "blocked": m.get("blocked", False)}
                async for m in db.members.find({})]
        resp = _csv(rows, list(rows[0].keys()) if rows else ["id"])
    elif kind == "stamps":
        rows = [{"id": s["_id"], "at": s["at"], "day": s["day"], "hour": s.get("hour"), "memberId": s["memberId"], "outlet": s.get("outletCode"),
                 "area": s.get("area"), "granted": s["granted"], "reason": s.get("reason"), "flags": ",".join(s.get("flags") or []),
                 "distanceM": s.get("distanceM"), "promoCode": s.get("promoCode"), "isNewMember": s.get("isNewMember")}
                async for s in db.stamps.find({"day": {"$gte": from_, "$lte": to}})]
        resp = _csv(rows, ["id", "at", "day", "hour", "memberId", "outlet", "area", "granted", "reason", "flags", "distanceM", "promoCode", "isNewMember"])
    elif kind == "feedback":
        rows = [{"at": f["at"], "memberId": f["memberId"], "outlet": f.get("outletCode"), "area": f.get("area"), "rating": f["rating"], "tag": f.get("tag"), "comment": f.get("comment")}
                async for f in db.feedback.find({"at": {"$gte": from_, "$lte": to + "T23:59:59Z"}})]
        resp = _csv(rows, ["at", "memberId", "outlet", "area", "rating", "tag", "comment"])
    elif kind == "vouchers":
        rows = [{"id": v["_id"], "memberId": v["memberId"], "type": v["type"], "title": v["title"], "valueRp": v.get("valueRp"), "validFrom": v["validFrom"],
                 "validTo": v["validTo"], "status": v["status"], "usedAt": v.get("usedAt"), "usedOutlet": v.get("usedOutletName"), "campaignCode": v.get("campaignCode")}
                async for v in db.vouchers.find({"createdAt": {"$gte": from_, "$lte": to + "T23:59:59Z"}})]
        resp = _csv(rows, ["id", "memberId", "type", "title", "valueRp", "validFrom", "validTo", "status", "usedAt", "usedOutlet", "campaignCode"])
    else:
        raise HTTPException(404, {"code": "not_found", "message": "Jenis export tidak dikenal."})
    resp.headers["Content-Disposition"] = f'attachment; filename="{kind}-{from_}-{to}.csv"'
    await audit(db, user, f"export.{kind}", None, {"from": from_, "to": to})
    return resp


# ---------- Data contoh ----------

@router.post("/seed")
async def seed(user: dict = Depends(LEAD), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Isi outlet pilot Braga; hanya bila belum ada outlet."""
    if await db.outlets.count_documents({}) > 0:
        raise HTTPException(409, {"code": "not_empty", "message": "Database sudah berisi outlet."})
    sample = [
        ("BDG-BRG-01", "Gerobak AA – Braga", "Bandung", "Bandung", -6.9175, 107.6098),
        ("BDG-BRG-02", "Gerobak AA – Asia Afrika", "Bandung", "Bandung", -6.9218, 107.6070),
        ("BDG-BRG-03", "Gerobak AA – Alun-alun", "Bandung", "Bandung", -6.9219, 107.6071),
        ("BDG-DGO-01", "Gerobak AA – Dago", "Bandung", "Bandung", -6.8853, 107.6134),
        ("JKT-MGD-01", "Gerobak AA – Margonda", "Depok", "Depok", -6.3860, 106.8290),
    ]
    docs = [{"_id": new_id("out"), "code": c, "name": n, "area": a, "city": ct, "address": None, "lat": la, "lng": ln,
             "priceZone": "bandung" if a == "Bandung" else "jabodetabek", "active": True, "qrToken": new_qr_token(), "oldTokens": [], "createdAt": iso(now_utc())}
            for c, n, a, ct, la, ln in sample]
    await db.outlets.insert_many(docs)
    await audit(db, user, "seed", None, {"outlets": len(docs)})
    return {"outlets": [outlet_admin(d) for d in docs]}
