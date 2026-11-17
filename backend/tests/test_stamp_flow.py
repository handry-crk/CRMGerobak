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

    res = await stamp(client, tok, phone="081234567890", name="Dina")
    assert res["granted"] and res["isNewMember"]
    assert res["stampsActive"] == 1 and res["stampsTotal"] == 1
    assert res["member"]["maskedPhone"] == "0812****890"
    assert "Stamp pertama" in res["headline"]
    wv = res["welcomeVoucher"]
    assert wv and wv["type"] == "balik_lagi" and wv["status"] == "scheduled"
    assert wv["validFrom"] == add_days(today_wib(), 3)
    assert wv["validTo"] == add_days(wv["validFrom"], 7)

    db = dbmod.get_db()
    m = await db.members.find_one({"phone": "081234567890"})
    assert m is not None


async def test_bad_phone_rejected(client, outlets):
    r = await client.post("/api/stamp", json={"qrToken": outlets[0]["qrToken"], "requestId": rid(), "phone": "12345"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "bad_phone"


async def test_same_outlet_same_day_not_granted(client, outlets):
    tok = outlets[0]["qrToken"]
    res = await stamp(client, tok, phone="081234567890", name="Dina")
    dev = res["deviceToken"]
    again = await stamp(client, tok, deviceToken=dev)
    assert again["needPhone"] is False
    assert again["granted"] is False and again["reason"] == "already_today"
    assert again["stampsActive"] == 1
    assert "udah masuk" in again["headline"]


async def test_min_gap_and_daily_limit(client, outlets):
    a, b, c = (o["qrToken"] for o in outlets[:3])
    res = await stamp(client, a, phone="081234567890", name="Dina")
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
    r1 = await client.post("/api/stamp", json={"qrToken": tok, "requestId": req, "phone": "081234567890", "name": "Dina"})
    r2 = await client.post("/api/stamp", json={"qrToken": tok, "requestId": req, "deviceToken": r1.json()["deviceToken"]})
    assert r2.json()["granted"] is True  # hasil asli dikembalikan, bukan "already_today"
    db = dbmod.get_db()
    assert await db.stamps.count_documents({}) == 1


async def test_five_stamps_issue_reward_and_redeem_flow(client, outlets):
    db = dbmod.get_db()
    await db.settings.update_one({"_id": "main"}, {"$set": {"rewardRedeemAfterDays": 0, "feedbackRequired": False}})  # H+1 diuji di test_antifraud
    res = await stamp(client, outlets[0]["qrToken"], phone="081234567890", name="Dina")
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
    res = await stamp(client, outlets[0]["qrToken"], phone="081234567890", name="Dina")
    wv = res["welcomeVoucher"]
    r = await client.post(f"/api/voucher/{wv['id']}/redeem", json={"qrToken": outlets[0]["qrToken"]}, headers={"X-Device-Token": res["deviceToken"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_yet"


async def test_geofence_flags_but_grants(client, outlets):
    o = outlets[0]
    res = await stamp(client, o["qrToken"], phone="081234567890", name="Dina", lat=o["lat"] + 0.02, lng=o["lng"])  # ±2 km
    assert res["granted"] is True
    db = dbmod.get_db()
    s = await db.stamps.find_one({})
    assert "jauh" in s["flags"] and s["distanceM"] > 300


async def test_flagged_member_appears_in_summary(client, admin, outlets):
    db = dbmod.get_db()
    res = await stamp(client, outlets[0]["qrToken"], phone="081234567890", name="Dina")
    mid = res["member"]["id"]
    for i in range(3):
        await db.stamps.insert_one({"_id": f"stp_x{i}", "memberId": mid, "outletId": outlets[0]["id"], "outletCode": "X", "area": "Bandung",
                                    "at": iso(now_utc()), "day": today_wib(), "hour": 12, "flags": ["jauh"], "granted": True})
    r = await client.get("/api/admin/summary", headers=admin)
    assert r.status_code == 200
    flagged = r.json()["flagged"]
    assert any(f["id"] == mid and f["jauh7d"] >= 3 for f in flagged)


async def test_feedback_and_profile(client, outlets):
    res = await stamp(client, outlets[0]["qrToken"], phone="081234567890", name="Dina")
    h = {"X-Device-Token": res["deviceToken"]}
    r = await client.post("/api/feedback", json={"stampId": res["stampId"], "service": 4, "tags": ["Crew ramah"]}, headers=h)
    assert r.status_code == 200 and r.json()["complete"] is True and r.json()["tasteDone"] is False
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
    await stamp(client, outlets[4]["qrToken"], phone="081234567890", name="Dina")  # Depok
    await stamp(client, outlets[0]["qrToken"], phone="081298765432", name="Dina")  # Bandung
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
    assert exp.status_code == 200 and "081234567890" in exp.text


async def test_pin_lockout(client):
    for i in range(5):
        r = await client.post("/api/admin/login", json={"name": "Admin", "pin": "0000"})
    assert r.status_code == 423
    r = await client.post("/api/admin/login", json={"name": "Admin", "pin": "1234"})
    assert r.status_code == 423


async def test_metrics_api_key(client, outlets):
    await stamp(client, outlets[0]["qrToken"], phone="081234567890", name="Dina")
    assert (await client.get("/api/public-metrics/crm")).status_code == 401
    r = await client.get("/api/public-metrics/crm", headers={"X-Api-Key": "test-key"})
    assert r.status_code == 200 and r.json()["member"] == 1 and r.json()["stamps"] == 1


async def test_jobs_activate_and_expire(client, admin, outlets):
    db = dbmod.get_db()
    res = await stamp(client, outlets[0]["qrToken"], phone="081234567890", name="Dina")
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


async def test_phone_formats_unified_to_08_and_name_required(client, outlets):
    tok = outlets[0]["qrToken"]
    # Tanpa nama → ditolak dengan pesan ramah
    r = await client.post("/api/stamp", json={"qrToken": tok, "requestId": rid(), "phone": "081234567890"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "need_name"
    # +62 / 62 / 08 → tersimpan 08
    res = await stamp(client, tok, phone="+62 812-3456-7890", name="Dina")
    db = dbmod.get_db()
    m = await db.members.find_one({"_id": res["member"]["id"]})
    assert m["phone"] == "081234567890" and m["name"] == "Dina"
    again = await client.post("/api/stamp", json={"qrToken": outlets[1]["qrToken"], "requestId": rid(), "phone": "6281234567890"})
    assert again.status_code == 200 and again.json()["member"]["id"] == m["_id"]  # nomor sama, bukan member baru
    assert again.json()["isNewMember"] is False


async def test_feedback_two_stage_service_now_taste_next_visit(client, outlets):
    db = dbmod.get_db()
    await db.settings.update_one({"_id": "main"}, {"$set": {"rewardRedeemAfterDays": 0, "minMinutesBetweenStamps": 0}})
    # Kunjungan 1: hanya pelayanan yang dinilai
    v1 = await stamp(client, outlets[0]["qrToken"], phone="081234567890", name="Dina")
    h = {"X-Device-Token": v1["deviceToken"]}
    assert v1["feedbackRequired"] is True and v1["pendingReview"] is None
    # Pelayanan hari ini boleh diisi sekarang (opsional), rasa belum
    await client.post("/api/feedback", json={"stampId": v1["stampId"], "service": 5, "tags": ["Crew ramah"]}, headers=h)
    # Kunjungan 2: kunjungan 1 masih butuh rasa
    await db.members.update_one({"_id": v1["member"]["id"]}, {"$set": {"stampsActive": 4}})
    v2 = await stamp(client, outlets[1]["qrToken"], deviceToken=v1["deviceToken"])
    pr = v2["pendingReview"]
    assert pr["stampId"] == v1["stampId"] and pr["needTaste"] is True and pr["needService"] is False
    reward = next(v for v in v2["vouchers"] if v["type"] == "stamp_reward")
    body = {"qrToken": outlets[1]["qrToken"]}
    # Kunjungan 1 belum dinilai lengkap → voucher belum bisa ditukar (pelayanan HARI INI tidak disyaratkan: belum bayar/dilayani)
    r = await client.post(f"/api/voucher/{reward['id']}/redeem", json=body, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "need_review"
    r = await client.post("/api/feedback", json={"stampId": v1["stampId"], "rating": 4, "tags": ["Enak banget", "Kurang panas", "Crew ramah"]}, headers=h)
    assert r.json()["tasteDone"] is True
    ok = await client.post(f"/api/voucher/{reward['id']}/redeem", json=body, headers=h)
    assert ok.status_code == 200 and ok.json()["crewInstruction"].startswith("Berikan")
    fb1 = await db.feedback.find_one({"stampId": v1["stampId"]})
    assert fb1["rating"] == 4 and fb1["service"] == 5 and fb1["ratingGroup"] == "puas" and fb1["tags"] == ["Enak banget", "Crew ramah"]
    # Kunjungan 3: kunjungan 2 belum dinilai sama sekali → dua-duanya ditanya
    v3 = await stamp(client, outlets[2]["qrToken"], deviceToken=v1["deviceToken"])
    assert v3["pendingReview"]["stampId"] == v2["stampId"] and v3["pendingReview"]["needTaste"] and v3["pendingReview"]["needService"]
    assert v3["granted"] is False  # batas 2 stamp/hari → kunjungan 3 tidak dihitung, jadi yang tertunda tetap kunjungan 2
    me = (await client.get("/api/me", headers=h)).json()
    assert me["pendingReview"]["stampId"] == v2["stampId"]
    # Voucher potongan: instruksi crew memuat nilai & min belanja
    wv = next(v for v in me["vouchers"] if v["type"] == "balik_lagi")
    assert wv["isDiscount"] and "3.000" in wv["crewInstruction"] and "15.000" in wv["crewInstruction"]


async def test_concurrent_double_scan_grants_once(client, outlets):
    import asyncio
    tok = outlets[0]["qrToken"]
    first = await stamp(client, tok, phone="081234567890", name="Dina")
    dev, mid = first["deviceToken"], first["member"]["id"]
    db = dbmod.get_db()
    # Hapus jejak hari ini agar aturan "already_today" tidak lebih dulu menolak; sisakan hanya kunci atomik
    await db.stamps.delete_many({"memberId": mid})
    await db.stamp_locks.delete_many({})
    await db.members.update_one({"_id": mid}, {"$set": {"stampsActive": 0, "stampsTotal": 0, "visits": 0}})
    body = lambda: {"qrToken": tok, "requestId": rid(), "deviceToken": dev}
    results = await asyncio.gather(*[client.post("/api/stamp", json=body()) for _ in range(5)])
    granted = [r.json()["granted"] for r in results]
    assert granted.count(True) == 1, granted
    m = await db.members.find_one({"_id": mid})
    assert m["stampsActive"] == 1


async def test_manager_full_access_crm_lead_operational(client, admin, outlets):
    me = (await client.get("/api/admin/me", headers=admin)).json()
    assert me["role"] == "Manager"
    r = await client.post("/api/admin/users", json={"name": "Lead CRM", "role": "CRM Lead", "pin": "4444"}, headers=admin)
    assert r.status_code == 200
    lead = {"Authorization": f"Bearer {(await client.post('/api/admin/login', json={'name': 'Lead CRM', 'pin': '4444'})).json()['token']}"}
    # CRM Lead: boleh operasional
    assert (await client.put("/api/admin/settings", json={"minMinutesBetweenStamps": 15}, headers=lead)).status_code == 200
    assert (await client.post("/api/admin/staff", json={"phone": "08990000111", "name": "Crew"}, headers=lead)).status_code == 200
    assert (await client.get("/api/admin/export/members.csv", headers=lead)).status_code == 200
    # CRM Lead: tidak boleh kelola admin & job
    assert (await client.post("/api/admin/users", json={"name": "X", "role": "Viewer", "pin": "1111"}, headers=lead)).status_code == 403
    assert (await client.post("/api/admin/jobs/backup/run", headers=lead)).status_code == 403


async def test_reset_pin_and_change_own_pin(client, admin):
    r = await client.post("/api/admin/users", json={"name": "Rani", "role": "Viewer", "pin": "5555"}, headers=admin)
    uid = r.json()["id"]
    # kunci akun Rani dulu
    for _ in range(5):
        await client.post("/api/admin/login", json={"name": "Rani", "pin": "0000"})
    assert (await client.post("/api/admin/login", json={"name": "Rani", "pin": "5555"})).status_code == 423
    # Manager reset → PIN sementara, kunci terbuka
    r = await client.post(f"/api/admin/users/{uid}/reset-pin", headers=admin)
    assert r.status_code == 200 and len(r.json()["pin"]) == 6
    temp = r.json()["pin"]
    login = await client.post("/api/admin/login", json={"name": "Rani", "pin": temp})
    assert login.status_code == 200 and login.json()["user"]["mustChangePin"] is True
    rh = {"Authorization": f"Bearer {login.json()['token']}"}
    # Rani ganti PIN sendiri
    assert (await client.post("/api/admin/me/pin", json={"oldPin": "9999", "newPin": "1212"}, headers=rh)).status_code == 401
    assert (await client.post("/api/admin/me/pin", json={"oldPin": temp, "newPin": "1212"}, headers=rh)).status_code == 200
    assert (await client.post("/api/admin/login", json={"name": "Rani", "pin": "1212"})).status_code == 200
    # Viewer tidak boleh reset PIN orang lain
    assert (await client.post(f"/api/admin/users/{uid}/reset-pin", headers=rh)).status_code == 403


async def test_create_user_requires_pin(client, admin):
    r = await client.post("/api/admin/users", json={"name": "Tanpa PIN", "role": "Viewer"}, headers=admin)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "pin_required"
    r = await client.post("/api/admin/users", json={"name": "Area Kosong", "role": "Area", "pin": "1111"}, headers=admin)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "area_required"


async def test_marketing_team_leader_role(client, admin):
    r = await client.post("/api/admin/users", json={"name": "Kintan Asokawati", "role": "Marketing Team Leader", "pin": "8888", "email": "kintan.asokawati@citarasakuliner.com"}, headers=admin)
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {(await client.post('/api/admin/login', json={'name': 'Kintan Asokawati', 'pin': '8888'})).json()['token']}"}
    assert (await client.get("/api/admin/settings", headers=h)).status_code == 200
    assert (await client.get("/api/admin/export/members.csv", headers=h)).status_code == 200
    assert (await client.post("/api/admin/users", json={"name": "X", "role": "Viewer", "pin": "1111"}, headers=h)).status_code == 403


async def test_campaign_max_issue_and_specific_numbers_and_wipe(client, admin, outlets):
    for ph in ["081200000001", "081200000002", "081200000003"]:
        await stamp(client, outlets[0]["qrToken"], phone=ph, name="T")
    base = {"title": "Tes", "valueRp": 1000, "validFrom": today_wib(), "validTo": add_days(today_wib(), 7)}
    r = await client.post("/api/admin/campaigns", json={**base, "code": "MAX2", "segment": "semua", "maxIssue": 2}, headers=admin)
    assert r.status_code == 200 and r.json()["issued"] == 2
    r = await client.post("/api/admin/campaigns", json={**base, "code": "NOMOR", "segment": "nomor", "phones": "0812-0000-0001, +6281200000003\n089999999999"}, headers=admin)
    assert r.status_code == 200 and r.json()["issued"] == 2 and r.json()["notFound"] == ["089999999999"]
    db = dbmod.get_db()
    assert await db.vouchers.count_documents({"campaignCode": "NOMOR"}) == 2
    # wipe
    bad = await client.post("/api/admin/wipe-test-data", json={"confirm": "hapus semua"}, headers=admin)
    assert bad.status_code == 422
    ok = await client.post("/api/admin/wipe-test-data", json={"confirm": "HAPUS"}, headers=admin)
    assert ok.status_code == 200 and ok.json()["removed"]["members"] == 3
    assert await db.members.count_documents({}) == 0 and await db.vouchers.count_documents({}) == 0
    assert await db.outlets.count_documents({}) == 5 and await db.admin_users.count_documents({}) >= 1


async def test_campaign_revoke_delete_and_void(client, admin, outlets):
    db = dbmod.get_db()
    await db.settings.update_one({"_id": "main"}, {"$set": {"feedbackRequired": False}})
    r1 = await stamp(client, outlets[0]["qrToken"], phone="081200000001", name="A")
    await stamp(client, outlets[0]["qrToken"], phone="081200000002", name="B")
    base = {"title": "Tes", "valueRp": 1000, "validFrom": today_wib(), "validTo": add_days(today_wib(), 7), "segment": "semua"}
    c1 = (await client.post("/api/admin/campaigns", json={**base, "code": "C1"}, headers=admin)).json()
    # member A menukar voucher C1
    v = await db.vouchers.find_one({"campaignCode": "C1", "memberId": r1["member"]["id"]})
    ok = await client.post(f"/api/voucher/{v['_id']}/redeem", json={"qrToken": outlets[0]["qrToken"]}, headers={"X-Device-Token": r1["deviceToken"]})
    assert ok.status_code == 200
    # hapus ditolak karena ada yang ditukar → tarik
    d = await client.delete(f"/api/admin/campaigns/{c1['id']}?reason=salah", headers=admin)
    assert d.status_code == 409
    rv = await client.post(f"/api/admin/campaigns/{c1['id']}/revoke", json={"reason": "salah nominal"}, headers=admin)
    assert rv.status_code == 200 and rv.json()["revoked"] == 1
    assert await db.vouchers.count_documents({"campaignCode": "C1", "status": "used"}) == 1
    assert await db.vouchers.count_documents({"campaignCode": "C1", "status": "expired"}) == 1
    # campaign tanpa penukaran → boleh dihapus total
    c2 = (await client.post("/api/admin/campaigns", json={**base, "code": "C2"}, headers=admin)).json()
    d = await client.delete(f"/api/admin/campaigns/{c2['id']}?reason=batal", headers=admin)
    assert d.status_code == 200 and d.json()["deleted"] == 2
    assert await db.campaigns.find_one({"code": "C2"}) is None
    # void satu voucher (Balik Lagi member B)
    vb = await db.vouchers.find_one({"type": "balik_lagi", "memberId": {"$ne": r1["member"]["id"]}})
    assert (await client.post(f"/api/admin/vouchers/{vb['_id']}/void", json={"reason": "salah terbit"}, headers=admin)).status_code == 200
    assert (await db.vouchers.find_one({"_id": vb["_id"]}))["status"] == "expired"
    assert (await client.post(f"/api/admin/vouchers/{v['_id']}/void", json={"reason": "sudah dipakai"}, headers=admin)).status_code == 409
