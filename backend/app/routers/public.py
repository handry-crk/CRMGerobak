"""Endpoint publik untuk halaman customer (scan QR, stamp, feedback, voucher, profil)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from ..db import (FEEDBACK_TAGS, PRODUCT_TAGS, PRODUCT_TAGS_BY_GROUP, RATING_GROUPS, RATING_SCALE, SERVICE_TAGS,
                  SERVICE_TAGS_BY_GROUP, SOURCES, get_db, get_settings, rating_group)
from ..security import client_ip, current_member, enforce_rate
from ..services import stamp as stamp_svc
from ..services.stamp import StampError, member_public, outlet_public
from ..services.voucher import RedeemError, member_vouchers, redeem_voucher
from ..utils import iso, new_id, normalize_phone, now_utc

router = APIRouter(prefix="/api", tags=["public"])


class StampIn(BaseModel):
    qrToken: str
    requestId: str = Field(min_length=6, max_length=64)
    phone: str | None = None
    deviceToken: str | None = None
    lat: float | None = None
    lng: float | None = None
    promoCode: str | None = None
    optIn: bool | None = None
    name: str | None = Field(default=None, max_length=40)


class FeedbackIn(BaseModel):
    qrToken: str
    stampId: str | None = None
    rating: int = Field(ge=1, le=5)            # rasa cimol
    service: int | None = Field(default=None, ge=1, le=5)  # pelayanan crew
    tags: list[str] = []
    comment: str | None = Field(default=None, max_length=140)
    productNote: str | None = Field(default=None, max_length=140)  # ketik manual saat rasa Kecewa/Kurang
    serviceNote: str | None = Field(default=None, max_length=140)  # ketik manual saat pelayanan Kecewa/Kurang


class ProfileIn(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    source: str | None = None
    skipped: bool = False


class RedeemIn(BaseModel):
    qrToken: str


class SwitchIn(BaseModel):
    phone: str


@router.get("/outlet/{qr_token}")
async def get_outlet(qr_token: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    settings = await get_settings(db)
    try:
        outlet = await stamp_svc.outlet_by_token(db, qr_token)
    except StampError as e:
        raise HTTPException(e.status, {"code": e.code, "message": e.message})
    return outlet_public(outlet, settings)


@router.post("/stamp")
async def post_stamp(body: StampIn, request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    ip = client_ip(request)
    enforce_rate(f"ip:{ip}", 30)
    if body.phone:
        enforce_rate(f"phone:{normalize_phone(body.phone) or body.phone}", 10)
    settings = await get_settings(db)
    try:
        return await stamp_svc.process_stamp(
            db, settings, body.qrToken, body.requestId, body.phone, body.deviceToken,
            body.lat, body.lng, body.promoCode, ip, body.optIn, body.name,
        )
    except StampError as e:
        raise HTTPException(e.status, {"code": e.code, "message": e.message})


@router.post("/feedback")
async def post_feedback(body: FeedbackIn, member: dict = Depends(current_member), db: AsyncIOMotorDatabase = Depends(get_db)):
    outlet = await db.outlets.find_one({"qrToken": body.qrToken})
    if not outlet:
        raise HTTPException(404, {"code": "qr_unknown", "message": "QR tidak dikenal."})
    allowed = set(PRODUCT_TAGS_BY_GROUP[rating_group(body.rating)])
    if body.service:
        allowed |= set(SERVICE_TAGS_BY_GROUP[rating_group(body.service)])
    tags = [t for t in body.tags if t in allowed][:6]
    fields = {
        "rating": body.rating, "ratingGroup": rating_group(body.rating),
        "service": body.service, "serviceGroup": rating_group(body.service) if body.service else None,
        "tags": tags, "tag": tags[0] if tags else None,
        "productNote": (body.productNote or "").strip() or None if body.rating <= 2 else None,
        "serviceNote": (body.serviceNote or "").strip() or None if (body.service or 5) <= 2 else None,
        "complete": body.service is not None,
    }
    fields["comment"] = " · ".join(x for x in [
        f"Rasa: {fields['productNote']}" if fields["productNote"] else None,
        f"Pelayanan: {fields['serviceNote']}" if fields["serviceNote"] else None,
        (body.comment or "").strip() or None,
    ] if x) or None
    if body.stampId and await db.feedback.find_one({"stampId": body.stampId}):
        await db.feedback.update_one({"stampId": body.stampId}, {"$set": fields})
        return {"ok": True, "complete": fields["complete"]}
    await db.feedback.insert_one({
        "_id": new_id("fbk"), "memberId": member["_id"], "outletId": outlet["_id"], "outletCode": outlet["code"],
        "area": outlet["area"], "stampId": body.stampId, "at": iso(now_utc()), **fields,
    })
    return {"ok": True, "complete": fields["complete"]}


@router.post("/profile")
async def post_profile(body: ProfileIn, member: dict = Depends(current_member), db: AsyncIOMotorDatabase = Depends(get_db)):
    upd: dict = {}
    if body.skipped:
        await db.members.update_one({"_id": member["_id"]}, {"$inc": {"profileSkips": 1}})
        return {"ok": True}
    if body.name is not None:
        upd["name"] = body.name.strip()[:40] or None
    if body.source is not None:
        if body.source not in SOURCES:
            raise HTTPException(422, {"code": "bad_source", "message": "Pilihan tidak dikenal."})
        upd["source"] = body.source
    if upd:
        await db.members.update_one({"_id": member["_id"]}, {"$set": upd})
    fresh = await db.members.find_one({"_id": member["_id"]})
    return {"ok": True, "member": member_public(fresh)}


@router.post("/voucher/{voucher_id}/redeem")
async def post_redeem(voucher_id: str, body: RedeemIn, member: dict = Depends(current_member), db: AsyncIOMotorDatabase = Depends(get_db)):
    settings = await get_settings(db)
    try:
        return await redeem_voucher(db, member, voucher_id, body.qrToken, settings)
    except RedeemError as e:
        raise HTTPException(409, {"code": e.code, "message": e.message})


@router.get("/me")
async def get_me(member: dict = Depends(current_member), db: AsyncIOMotorDatabase = Depends(get_db)):
    settings = await get_settings(db)
    vouchers = await member_vouchers(db, member["_id"], include_history=True)
    stamps = db.stamps.find({"memberId": member["_id"], "granted": True}).sort("at", -1).limit(30)
    history = []
    async for s in stamps:
        outlet = await db.outlets.find_one({"_id": s["outletId"]}, {"name": 1})
        history.append({"at": s["at"], "day": s["day"], "outletName": outlet["name"] if outlet else s.get("outletCode")})
    return {
        "member": member_public(member),
        "stampsPerReward": settings["stampsPerReward"],
        "rewardTitle": settings["rewardTitle"],
        "vouchers": vouchers,
        "history": history,
        "sources": list(SOURCES),
    }


@router.post("/me/opt-out")
async def opt_out(member: dict = Depends(current_member), db: AsyncIOMotorDatabase = Depends(get_db)):
    new_val = not member.get("optIn", True)
    await db.members.update_one({"_id": member["_id"]}, {"$set": {"optIn": new_val}})
    return {"ok": True, "optIn": new_val}


@router.post("/me/switch-device")
async def switch_device(body: SwitchIn, request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Lanjutkan akun di HP baru dengan mengetik nomor (v1 tanpa OTP; lihat Iterasi 1)."""
    enforce_rate(f"ip:{client_ip(request)}", 10)
    phone = normalize_phone(body.phone)
    if not phone:
        raise HTTPException(422, {"code": "bad_phone", "message": "Nomor WhatsApp-nya belum pas, Kak."})
    member = await db.members.find_one({"phone": phone})
    if not member:
        raise HTTPException(404, {"code": "not_member", "message": "Nomor ini belum terdaftar. Scan QR di gerobak dulu ya."})
    token, _ = await stamp_svc.attach_device(db, member, None)
    return {"deviceToken": token, "member": member_public(member)}


@router.get("/meta")
async def meta():
    return {"sources": list(SOURCES), "feedbackTags": list(FEEDBACK_TAGS), "productTags": list(PRODUCT_TAGS),
            "serviceTags": list(SERVICE_TAGS), "productTagsByGroup": {k: list(v) for k, v in PRODUCT_TAGS_BY_GROUP.items()},
            "serviceTagsByGroup": {k: list(v) for k, v in SERVICE_TAGS_BY_GROUP.items()},
            "ratingScale": RATING_SCALE, "ratingGroups": RATING_GROUPS}
