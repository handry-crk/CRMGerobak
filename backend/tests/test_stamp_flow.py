"""Skenario acceptance dari build spec: stamp, aturan harian, reward, voucher, redeem, role admin."""
import uuid
from datetime import timedelta

import pytest

from app import db as dbmod
from app.utils import add_days, iso, now_utc, today_wib

pytestmark = pytest.mark.asyncio


def rid():
    return uuid.uuid4().hex[:16]


async def stamp(client, token, **kw):
    body = {"qrToken": token, "requestId": rid(), **kw}
    r = await client.post("/api/stamp", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def backdate_last_stamp(member_id, minutes):
    db = dbmod.get_db()
    last = await db.stamps.find_one({"memberId": member_id, "granted": True}, sort=[("at", -1)])
    await db.stamps.update_one({"_id": last["_id"]}, {"$set": {"at": iso(now_utc() - timedelta(minutes=minutes))}})


async def test_new_member_first_stamp_and_welcome_voucher(client, outlets):
    tok = outlets[0]["qrToken"]
    first = await stamp(client, tok)
    assert first["needPhone"] is True

    res = await stamp(client, tok, phone="081234567890")
    assert res["granted"] and res["isNewMember"]
    assert res["stampsActive"] == 1 and res["stampsTotal"] == 1
    assert res["member"]["maskedPhone"].startswith("+62812")
    assert "Stamp pertama" in res["headline"]
    wv = res["welcomeVoucher"]
    assert wv and wv["type"] == "balik_lagi" and wv["status"] == "scheduled"
    assert wv["validFrom"] == add_days(today_wib(), 3)
    assert wv["validTo"] == add_days(wv["validFrom"], 7)

    db = dbmod.get_db()
    m = await db.members.find_one({"phone": "+6281234567890"})
    assert m is not None


async def test_bad_phone_rejected(client, outlets):
    r = await client.post("/api/stamp", json={"qrToken": outlets[0]["qrToken"], "requestId": rid(), "phone": "12345"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "bad_phone"


async def test_same_outlet_same_day_not_granted(client, outlets):
    tok = outlets[0]["qrToken"]
    res = await stamp(client, tok, phone="081234567890")
    dev = res["deviceToken"]
    again = await stamp(client, tok, deviceToken=dev)
    assert again["needPhone"] is False
    assert again["granted"] is False and again["reason"] == "already_today"
    assert again["stampsActive"] == 1
    assert "udah masuk" in again["headline"]


async def test_min_gap_and_daily_limit(client, outlets):
    a, b, c = (o["qrToken"] for o in outlets[:3])
    res = await stamp(client, a, phone="081234567890")
    dev, mid = res["deviceToken"], res["member"]["id"]

    await backdate_last_stamp(mid, 10)
    r2 = await stamp(client, b, deviceToken=dev)
    assert r2["granted"] is False and r2["reason"] == "too_fast"

    await backdate_last_stamp(mid, 25)
    r3 = await stamp(client, b, deviceToken=dev)
    assert r3["granted"] is True and r3["stampsActive"] == 2

    await backdate_last_stamp(mid, 25)
    r4 = await stamp(client, c, deviceToken=dev)
    assert r4["granted"] is False and r4["reason"] == "over_limit"


async def test_idempotent_request_id(client, outlets):
    tok = outlets[0]["qrToken"]
    req = rid()
    r1 = await client.post("/api/stamp", json={"qrToken": tok, "requestId": req, "phone": "081234567890"})
    r2 = await client.post("/api/stamp", json={"qrToken": tok, "requestId": req, "deviceToken": r1.json()["deviceToken"]})
    assert r2.json()["granted"] is True  # hasil asli dikembalikan, bukan "already_today"
    db = dbmod.get_db()
    assert await db.stamps.count_documents({}) == 1


async def test_five_stamps_issue_reward_and_redeem_flow(client, outlets):
    db = dbmod.get_db()
    await db.settings.update_one({"_id": "main"}, {"$set": {"rewardRedeemAfterDays": 0}})  # H+1 diuji di test_antifraud
    res = await stamp(client, outlets[0]["qrToken"], phone="081234567890")
    dev, mid = res["deviceToken"], res["member"]["id"]
    # Simulasikan 4 hari sebelumnya sudah stamp di outlet lain
    for i in range(1, 5):
        await db.members.update_one({"_id": mid}, {"$set": {"stampsActive": i}})
    r = await stamp(client, outlets[1]["qrToken"], deviceToken=dev)
    # stampsActive 4 + 1 = 5 → reward; tapi aturan jeda 20 menit berlaku → backdate dulu
    if not r["granted"]:
        await backdate_last_stamp(mid, 30)
        r = await stamp(client, outlets[1]["qrToken"], deviceToken=dev)
    assert r["granted"] and r["rewardIssued"] is True
    assert r["stampsActive"] == 0
    reward = next(v for v in r["vouchers"] if v["type"] == "stamp_reward")
    assert reward["status"] == "active" and reward["validTo"] == add_days(today_wib(), 30)

    headers = {"X-Device-Token": dev}
    # Redeem tanpa sesi outlet (outlet ke-4 belum pernah di-scan) → ditolak
    bad = await client.post(f"/api/voucher/{reward['id']}/redeem", json={"qrToken": outlets[3]["qrToken"]}, headers=headers)
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "no_outlet"
    # Redeem di outlet yang baru saja di-scan → sukses
    ok = await client.post(f"/api/voucher/{reward['id']}/redeem", json={"qrToken": outlets[1]["qrToken"]}, headers=headers)
    assert ok.status_code == 200, ok.text
    data = ok.json()
    assert data["status"] == "used" and len(data["redeemCode"]) == 4 and data["usedOutletName"] == outlets[1]["name"]
    # Kedua kali → sudah ditukar
    dup = await client.post(f"/api/voucher/{reward['id']}/redeem", json={"qrToken": outlets[1]["qrToken"]}, headers=headers)
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "used"


async def test_scheduled_voucher_cannot_redeem_yet(client, outlets):
    res = await stamp(client, outlets[0]["qrToken"], phone="081234567890")
    wv = res["welcomeVoucher"]
    r = await client.post(f"/api/voucher/{wv['id']}/redeem", json={"qrToken": outlets[0]["qrToken"]}, headers={"X-Device-Token": res["deviceToken"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_yet"


async def test_geofence_flags_but_grants(client, outlets):
    o = outlets[0]
    res = await stamp(client, o["qrToken"], phone="081234567890", lat=o["lat"] + 0.02, lng=o["lng"])  # ±2 km
    assert res["granted"] is True
    db = dbmod.get_db()
    s = await db.stamps.find_one({})
    assert "jauh" in s["flags"] and s["distanceM"] > 300


async def test_flagged_member_appears_in_summary(client, admin, outlets):
    db = dbmod.get_db()
    res = await stamp(client, outlets[0]["qrToken"], phone="081234567890")
    mid = res["member"]["id"]
    for i in range(3):
        await db.stamps.insert_one({"_id": f"stp_x{i}", "memberId": mid, "outletId": outlets[0]["id"], "outletCode": "X", "area": "Bandung",
                                    "at": iso(now_utc()), "day": today_wib(), "hour": 12, "flags": ["jauh"], "granted": True})
    r = await client.get("/api/admin/summary", headers=admin)
    assert r.status_code == 200
    flagged = r.json()["flagged"]
    assert any(f["id"] == mid and f["jauh7d"] >= 3 for f in flagged)


async def test_feedback_and_profile(client, outlets):
    res = await stamp(client, outlets[0]["qrToken"], phone="081234567890")
    h = {"X-Device-Token": res["deviceToken"]}
    r = await client.post("/api/feedback", json={"qrToken": outlets[0]["qrToken"], "stampId": res["stampId"], "rating": 5, "tag": "Enak banget"}, headers=h)
    assert r.status_code == 200
    r = await client.post("/api/profile", json={"name": "Dina", "source": "Instagram"}, headers=h)
    assert r.status_code == 200 and r.json()["member"]["name"] == "Dina"
    me = await client.get("/api/me", headers=h)
    assert me.status_code == 200 and me.json()["member"]["profileDone"] is True
    assert len(me.json()["history"]) == 1


async def test_rotate_qr_replaces_old_token(client, admin, outlets):
    o = outlets[0]
    r = await client.post(f"/api/admin/outlets/{o['id']}/rotate-qr", headers=admin)
    assert r.status_code == 200
    new_tok = r.json()["qrToken"]
    assert new_tok != o["qrToken"]
    old = await client.get(f"/api/outlet/{o['qrToken']}")
    assert old.status_code == 410 and old.json()["detail"]["code"] == "qr_replaced"
    new = await client.get(f"/api/outlet/{new_tok}")
    assert new.status_code == 200
    pdf = await client.get(f"/api/admin/outlets/{o['id']}/sticker.pdf", headers=admin)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


async def test_admin_roles_area_and_masking(client, admin, outlets):
    db = dbmod.get_db()
    await stamp(client, outlets[4]["qrToken"], phone="081234567890")  # Depok
    await stamp(client, outlets[0]["qrToken"], phone="081298765432")  # Bandung
    # Buat user Area Bandung & Viewer
    r = await client.post("/api/admin/users", json={"name": "Area Bdg", "role": "Area", "areas": ["Bandung"], "pin": "2222"}, headers=admin)
    assert r.status_code == 200
    r = await client.post("/api/admin/users", json={"name": "Viewer", "role": "Viewer", "pin": "3333"}, headers=admin)
    assert r.status_code == 200
    area_tok = (await client.post("/api/admin/login", json={"name": "Area Bdg", "pin": "2222"})).json()["token"]
    view_tok = (await client.post("/api/admin/login", json={"name": "Viewer", "pin": "3333"})).json()["token"]
    ah, vh = {"Authorization": f"Bearer {area_tok}"}, {"Authorization": f"Bearer {view_tok}"}

    outs = (await client.get("/api/admin/outlets", headers=ah)).json()
    assert all(o["area"] == "Bandung" for o in outs) and len(outs) == 4
    mem = (await client.get("/api/admin/members", headers=ah)).json()
    assert mem["total"] == 1 and "****" in mem["items"][0]["phone"]
    mem_v = (await client.get("/api/admin/members", headers=vh)).json()
    assert mem_v["total"] == 2 and all("****" in m["phone"] for m in mem_v["items"])
    mem_full = (await client.get("/api/admin/members", headers=admin)).json()
    assert all("****" not in m["phone"] for m in mem_full["items"])
    # Export hanya CRM Lead/Manager
    assert (await client.get("/api/admin/export/members.csv", headers=vh)).status_code == 403
    exp = await client.get("/api/admin/export/members.csv", headers=admin)
    assert exp.status_code == 200 and "+6281234567890" in exp.text


async def test_pin_lockout(client):
    for i in range(5):
        r = await client.post("/api/admin/login", json={"name": "Admin", "pin": "0000"})
    assert r.status_code == 423
    r = await client.post("/api/admin/login", json={"name": "Admin", "pin": "1234"})
    assert r.status_code == 423


async def test_metrics_api_key(client, outlets):
    await stamp(client, outlets[0]["qrToken"], phone="081234567890")
    assert (await client.get("/api/public-metrics/crm")).status_code == 401
    r = await client.get("/api/public-metrics/crm", headers={"X-Api-Key": "test-key"})
    assert r.status_code == 200 and r.json()["member"] == 1 and r.json()["stamps"] == 1


async def test_jobs_activate_and_expire(client, admin, outlets):
    db = dbmod.get_db()
    res = await stamp(client, outlets[0]["qrToken"], phone="081234567890")
    wv = res["welcomeVoucher"]
    await db.vouchers.update_one({"_id": wv["id"]}, {"$set": {"validFrom": today_wib()}})
    r = await client.post("/api/admin/jobs/activate/run", headers=admin)
    assert r.json()["activated"] == 1
    await db.vouchers.update_one({"_id": wv["id"]}, {"$set": {"validTo": add_days(today_wib(), -1)}})
    r = await client.post("/api/admin/jobs/expire/run", headers=admin)
    assert r.json()["expired"] == 1
    r = await client.post("/api/admin/jobs/digest/run", headers=admin)
    assert r.status_code == 200 and r.json()["kpi"]["newMembers"] == 1
    r = await client.post("/api/admin/jobs/weekly/run", headers=admin)
    assert r.status_code == 200
