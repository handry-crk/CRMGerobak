"""Job terjadwal: aktivasi/expiry voucher, digest harian, rekap mingguan, backup. Sekali per slot per hari."""
from __future__ import annotations

import json
import logging
import os
import smtplib
from email.mime.text import MIMEText

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..config import config
from ..db import get_db, get_settings
from ..utils import WIB, add_days, ensure_dir, format_rp, format_tanggal, iso, now_utc, today_wib
from .analytics import summary, velocity_alerts
from .voucher import activate_due_vouchers, expire_vouchers

log = logging.getLogger("jobs")


async def _once_per_day(db: AsyncIOMotorDatabase, job: str, force: bool = False) -> bool:
    day = today_wib()
    if not force and await db.job_log.find_one({"job": job, "day": day}):
        return False
    await db.job_log.insert_one({"job": job, "day": day, "at": iso(now_utc())})
    return True


def send_email(to: list[str], subject: str, html: str) -> bool:
    to = [t for t in to if t]
    if not to:
        return False
    if not config.smtp_host:
        log.info("SMTP belum diatur; email '%s' ke %s hanya dicatat.", subject, to)
        return False
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = config.smtp_from
    msg["To"] = ", ".join(to)
    with smtplib.SMTP(config.smtp_host, config.smtp_port) as s:
        s.starttls()
        if config.smtp_user:
            s.login(config.smtp_user, config.smtp_password)
        s.sendmail(config.smtp_from, to, msg.as_string())
    return True


def _wrap(title: str, body: str) -> str:
    return f"""<div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;color:#1F1A1A">
<div style="background:#D7191F;color:#fff;padding:16px 20px;border-radius:12px 12px 0 0"><h2 style="margin:0">{title}</h2></div>
<div style="padding:20px;border:1px solid #EBD9DA;border-top:0;border-radius:0 0 12px 12px">{body}
<p style="margin-top:24px"><a href="{config.public_base_url}/admin" style="background:#D7191F;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Buka dashboard</a></p></div></div>"""


async def _recipients(db: AsyncIOMotorDatabase, settings: dict) -> list[str]:
    emails = {settings.get("adminEmail") or config.admin_email}
    async for u in db.admin_users.find({"role": {"$in": ["CRM Lead", "Manager"]}, "active": True, "email": {"$exists": True}}):
        emails.add(u.get("email"))
    return [e for e in emails if e]


async def job_voucher_activate(force: bool = False) -> dict:
    db = get_db()
    if not await _once_per_day(db, "voucher_activate", force):
        return {"skipped": True}
    n = await activate_due_vouchers(db)
    return {"activated": n}


async def job_voucher_expire(force: bool = False) -> dict:
    db = get_db()
    if not await _once_per_day(db, "voucher_expire", force):
        return {"skipped": True}
    n = await expire_vouchers(db)
    return {"expired": n}


async def job_daily_digest(force: bool = False) -> dict:
    db = get_db()
    if not await _once_per_day(db, "daily_digest", force):
        return {"skipped": True}
    settings = await get_settings(db)
    today = today_wib()
    s = await summary(db, today, today, None, {})
    k = s["kpi"]
    alerts = await velocity_alerts(db)
    rows = "".join(f"<tr><td>{r['name']}</td><td align=right>{r['stamps']}</td><td align=right>{r['members']}</td></tr>" for r in s["outlets"][:15])
    flagged = "".join(f"<li>{f['phone']} ({f.get('name') or '–'}): jauh {f['jauh7d']}×, perangkat baru {f['device7d']}×</li>" for f in s["flagged"]) or "<li>Tidak ada</li>"
    vel = "".join(f"<li>{a['outlet']}: {a['last10min']} stamp / 10 menit</li>" for a in alerts) or "<li>Tidak ada</li>"
    body = f"""<p>{format_tanggal(today, True)}</p>
<ul><li>Member baru: <b>{k['newMembers']}</b></li><li>Stamp: <b>{k['stamps']}</b> dari {k['uniqueMembers']} member</li>
<li>Reward ditukar: <b>{k['rewardUsed']}</b> · Balik Lagi ditukar: <b>{k['balikLagiUsed']}</b></li>
<li>Rating rata-rata: <b>{k['avgRating'] or '–'}</b> ({k['ratings']} rating)</li></ul>
<h3>Outlet teratas</h3><table cellpadding=6 style="border-collapse:collapse"><tr style="background:#B32E26;color:#fff"><th align=left>Outlet</th><th>Stamp</th><th>Member</th></tr>{rows}</table>
<h3>Perlu dicek</h3><ul>{flagged}</ul><h3>Lonjakan stamp</h3><ul>{vel}</ul>"""
    sent = send_email(await _recipients(db, settings), f"[Stamp Bojot] Digest {today}", _wrap("Digest harian", body))
    return {"sent": sent, "kpi": k}


async def job_weekly_recap(force: bool = False) -> dict:
    db = get_db()
    if not await _once_per_day(db, "weekly_recap", force):
        return {"skipped": True}
    settings = await get_settings(db)
    today = today_wib()
    this_from, this_to = add_days(today, -7), add_days(today, -1)
    last_from, last_to = add_days(today, -14), add_days(today, -8)
    cur = await summary(db, this_from, this_to, None, {})
    prev = await summary(db, last_from, last_to, None, {})

    def row(label, a, b, suffix=""):
        if a is None and b is None:
            return ""
        a_s = f"{a}{suffix}" if a is not None else "–"
        b_s = f"{b}{suffix}" if b is not None else "–"
        delta = "" if a is None or b is None else f"{'+' if a - b >= 0 else ''}{round(a - b, 1)}"
        return f"<tr><td>{label}</td><td align=right>{a_s}</td><td align=right>{b_s}</td><td align=right>{delta}</td></tr>"

    k, p = cur["kpi"], prev["kpi"]
    table = "".join([
        row("Member baru", k["newMembers"], p["newMembers"]),
        row("Stamp", k["stamps"], p["stamps"]),
        row("Member unik", k["uniqueMembers"], p["uniqueMembers"]),
        row("Scan rate", k["scanRatePct"], p["scanRatePct"], "%"),
        row("Repeat 30D", k["repeat30d"]["pct"], p["repeat30d"]["pct"], "%"),
        row("Redemption reward", k["redemptionPct"], p["redemptionPct"], "%"),
        row("Balik Lagi dipakai", k["balikLagiPct"], p["balikLagiPct"], "%"),
        row("Rating", k["avgRating"], p["avgRating"]),
    ])
    top = "".join(f"<li>{r['name']} — {r['stamps']} stamp ({r['perOpenDay']}/hari buka)</li>" for r in cur["charts"]["topOutlets"])
    bottom = "".join(f"<li>{r['name']} — {r['stamps']} stamp</li>" for r in cur["charts"]["bottomOutlets"])
    body = f"""<p>Periode {format_tanggal(this_from)} – {format_tanggal(this_to)} vs minggu sebelumnya.</p>
<table cellpadding=6 style="border-collapse:collapse"><tr style="background:#B32E26;color:#fff"><th align=left>Metrik</th><th>Minggu ini</th><th>Minggu lalu</th><th>Δ</th></tr>{table}</table>
<h3>Top 10 outlet</h3><ol>{top}</ol><h3>Bottom 10 outlet</h3><ol>{bottom}</ol>"""
    sent = send_email(await _recipients(db, settings), f"[Stamp Bojot] Rekap mingguan {this_from}–{this_to}", _wrap("Rekap mingguan", body))
    return {"sent": sent, "kpi": k}


async def job_backup(force: bool = False) -> dict:
    db = get_db()
    if not await _once_per_day(db, "backup", force):
        return {"skipped": True}
    folder = ensure_dir(config.backup_dir)
    stamp = now_utc().astimezone(WIB).strftime("%Y%m%d-%H%M")
    path = os.path.join(folder, f"stamp-bojot-{stamp}.json")
    data = {}
    for coll in ["outlets", "members", "stamps", "vouchers", "feedback", "settings", "admin_users", "outlet_transactions", "audit_log", "campaigns"]:
        data[coll] = [d async for d in db[coll].find({})]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    files = sorted(p for p in os.listdir(folder) if p.startswith("stamp-bojot-"))
    for old in files[:-8]:
        os.remove(os.path.join(folder, old))
    return {"file": path, "collections": {k: len(v) for k, v in data.items()}}


JOBS = {
    "activate": job_voucher_activate,
    "expire": job_voucher_expire,
    "digest": job_daily_digest,
    "weekly": job_weekly_recap,
    "backup": job_backup,
}


def build_scheduler() -> AsyncIOScheduler:
    sch = AsyncIOScheduler(timezone=WIB)
    sch.add_job(job_voucher_expire, CronTrigger(hour=0, minute=5, timezone=WIB))
    sch.add_job(job_voucher_activate, CronTrigger(hour=10, minute=0, timezone=WIB))
    sch.add_job(job_daily_digest, CronTrigger(hour=21, minute=30, timezone=WIB))
    sch.add_job(job_weekly_recap, CronTrigger(day_of_week="mon", hour=8, minute=30, timezone=WIB))
    sch.add_job(job_backup, CronTrigger(day_of_week="sun", hour=2, minute=0, timezone=WIB))
    # Pengaman: cek ulang tiap 15 menit bila slot terlewat (restart dsb.) — _once_per_day menjaga tidak dobel
    sch.add_job(job_voucher_activate, "interval", minutes=15)
    sch.add_job(job_voucher_expire, "interval", minutes=15)
    return sch
