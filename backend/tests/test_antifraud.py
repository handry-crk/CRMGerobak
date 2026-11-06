"""Lapis 1 + 3 anti-fraud crew: redeem H+1, kuota penukaran, nomor crew tanpa voucher & di luar KPI, rekonsiliasi."""
import uuid

import pytest

from app import db as dbmod
from app.utils import add_days, today_wib

pytestmark = pytest.mark.asyncio


async def stamp(client, token, **kw):
    r = await client.post("/api/stamp", json={"qrToken": token, "requestId": uuid.uuid4().hex[:16], **kw})
    assert r.status_code == 200, r.text
    return r.json()


async def make_reward(client, outlets, phone):
    """Member dengan 4 stamp aktif lalu stamp ke-5 → reward."""
    db = dbmod.get_db()
    res = await stamp(client, outlets[0]["qrToken"], phone=phone, name="Dina")
    await db.members.update_one({"_id": res["member"]["id"]}, {"$set": {"stampsActive": 4}})
    await db.settings.update_one({"_id": "main"}, {"$set": {"minMinutesBetweenStamps": 0}})
    r = await stamp(client, outlets[1]["qrToken"], deviceToken=res["deviceToken"])
    return r, res["deviceToken"]


async def test_reward_redeem_h_plus_1(client, outlets):
    r, dev = await make_reward(client, outlets, "081234567890")
    assert r["rewardIssued"]
    reward = next(v for v in r["vouchers"] if v["type"] == "stamp_reward")
    assert reward["status"] == "scheduled" and reward["validFrom"] == add_days(today_wib(), 1)
    bad = await client.post(f"/api/voucher/{reward['id']}/redeem", json={"qrToken": outlets[1]["qrToken"]}, headers={"X-Device-Token": dev})
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "not_yet"


async def test_redeem_quota_per_outlet(client, admin, outlets):
    db = dbmod.get_db()
    await db.settings.update_one({"_id": "main"}, {"$set": {"rewardRedeemAfterDays": 0, "maxRedemptionsPerOutletPerDay": 1}})
    r1, d1 = await make_reward(client, outlets, "081234567890")
    r2, d2 = await make_reward(client, outlets, "081234567891")
    v1 = next(v for v in r1["vouchers"] if v["type"] == "stamp_reward")
    v2 = next(v for v in r2["vouchers"] if v["type"] == "stamp_reward")
    ok = await client.post(f"/api/voucher/{v1['id']}/redeem", json={"qrToken": outlets[1]["qrToken"]}, headers={"X-Device-Token": d1})
    assert ok.status_code == 200
    full = await client.post(f"/api/voucher/{v2['id']}/redeem", json={"qrToken": outlets[1]["qrToken"]}, headers={"X-Device-Token": d2})
    assert full.status_code == 409 and full.json()["detail"]["code"] == "quota"
    rec = await client.get("/api/admin/reconciliation", headers=admin)
    assert rec.status_code == 200 and rec.json()["alerts"][0]["type"] == "redeem_quota"
    # voucher kedua tetap aktif
    v = await db.vouchers.find_one({"_id": v2["id"]})
    assert v["status"] == "active"


async def test_staff_number_no_voucher_and_excluded_from_kpi(client, admin, outlets):
    r = await client.post("/api/admin/staff", json={"phone": "0899 0000 111", "name": "Crew Braga", "outletCode": "bdg-brg-01"}, headers=admin)
    assert r.status_code == 200 and r.json()["phone"] == "08990000111"
    res = await stamp(client, outlets[0]["qrToken"], phone="08990000111", name="Dina")
    assert res["granted"] and res["member"]["isStaff"] and res["welcomeVoucher"] is None and res["askFeedback"] is False
    assert "crew" in res["headline"].lower()
    db = dbmod.get_db()
    await db.members.update_one({"_id": res["member"]["id"]}, {"$set": {"stampsActive": 4}})
    await db.settings.update_one({"_id": "main"}, {"$set": {"minMinutesBetweenStamps": 0}})
    r5 = await stamp(client, outlets[1]["qrToken"], deviceToken=res["deviceToken"])
    assert r5["granted"] and r5["rewardIssued"] is False and r5["vouchers"] == []
    # Pelanggan asli
    await stamp(client, outlets[0]["qrToken"], phone="081234567890", name="Dina")
    s = (await client.get("/api/admin/summary", headers=admin)).json()["kpi"]
    assert s["newMembers"] == 1 and s["stamps"] == 1


async def test_adding_staff_marks_existing_member(client, admin, outlets):
    res = await stamp(client, outlets[0]["qrToken"], phone="081234567890", name="Dina")
    assert res["welcomeVoucher"]
    r = await client.post("/api/admin/staff", json={"phone": "081234567890"}, headers=admin)
    assert r.status_code == 200
    db = dbmod.get_db()
    m = await db.members.find_one({"_id": res["member"]["id"]})
    assert m["isStaff"] is True
    assert (await db.vouchers.find_one({"memberId": m["_id"]}))["status"] == "expired"
    staff_id = r.json()["id"]
    assert (await client.delete(f"/api/admin/staff/{staff_id}", headers=admin)).status_code == 200
    assert (await db.members.find_one({"_id": m["_id"]}))["isStaff"] is False


async def test_reconciliation_rows(client, admin, outlets):
    db = dbmod.get_db()
    await db.settings.update_one({"_id": "main"}, {"$set": {"rewardRedeemAfterDays": 0}})
    r, d = await make_reward(client, outlets, "081234567890")
    v = next(x for x in r["vouchers"] if x["type"] == "stamp_reward")
    assert (await client.post(f"/api/voucher/{v['id']}/redeem", json={"qrToken": outlets[1]["qrToken"]}, headers={"X-Device-Token": d})).status_code == 200
    oid = outlets[1]["id"]
    today = today_wib()
    await client.post(f"/api/admin/outlets/{oid}/transactions", json={"day": today, "rewardsGiven": 3}, headers=admin)
    rec = (await client.get("/api/admin/reconciliation", headers=admin)).json()
    row = next(x for x in rec["rows"] if x["outletId"] == oid and x["day"] == today)
    assert row["redeemed"] == 1 and row["rewardsGiven"] == 3 and row["diff"] == 2 and row["status"] == "hadiah_lebih"
    assert len(rec["mismatch"]) == 1
