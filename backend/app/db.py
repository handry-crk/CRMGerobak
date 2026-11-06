"""Koneksi MongoDB (Motor), index, dan pengaturan default."""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .config import config
from .utils import hash_pin, iso, now_utc

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None

DEFAULT_SETTINGS: dict = {
    "_id": "main",
    "appName": "Stamp Bojot",
    "stampsPerReward": 5,
    "rewardTitle": "Cimol Bojot kecil gratis",
    "rewardValueRp": 6000,
    "maxStampsPerOutletPerDay": 1,
    "maxStampsPerDay": 2,
    "minMinutesBetweenStamps": 20,
    "geofenceM": 300,
    "welcomeVoucher": {
        "enabled": True,
        "title": "Potongan 3.000",
        "valueRp": 3000,
        "minSpendRp": 15000,
        "startAfterDays": 3,
        "validDays": 7,
    },
    "rewardVoucherValidDays": 30,
    "rewardRedeemAfterDays": 1,          # Lapis 1: reward baru bisa ditukar H+1 (crew harus "kembali besok")
    "maxRedemptionsPerOutletPerDay": 10,  # Lapis 1: kuota penukaran per gerobak per hari; lebih → ditolak + alert
    "redeemCountdownSec": 180,
    "feedbackPrompt": True,
    "activePromoCode": "",
    "activePromoQuestion": "",
    "adminEmail": "",
    "outletSessionMinutes": 60,
    "flagJauhThreshold": 3,
    "flagDeviceThreshold": 3,
}

ADMIN_ROLES = ("CRM Lead", "Manager", "Area", "Viewer")
AREAS = ("Jakarta", "Bandung", "Bekasi", "Depok", "Bogor", "Tangsel", "Tangerang")
SOURCES = ("Lewat gerobak", "Instagram", "TikTok", "Teman", "GoFood/GrabFood", "Lainnya")
FEEDBACK_TAGS = ("Enak banget", "Bumbu pas", "Antre lama", "Kurang panas", "Kurang bumbu", "Crew ramah")


def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        if config.use_mock_db:
            use_mock_client()
        else:
            _client = AsyncIOMotorClient(config.mongo_url, tz_aware=True, serverSelectionTimeoutMS=5000)
            _db = _client[config.mongo_db]
    return _db


def use_mock_client() -> None:
    """Database in-memory (mongomock). Data hilang saat proses berhenti."""
    global _client, _db
    from mongomock_motor import AsyncMongoMockClient
    _client = AsyncMongoMockClient(tz_aware=True)
    _db = _client[config.mongo_db]


async def connect_or_fallback() -> AsyncIOMotorDatabase:
    """Coba MongoDB; bila tidak terjangkau, jatuh ke mock agar aplikasi tetap bisa dicoba."""
    import logging
    log = logging.getLogger("db")
    db = get_db()
    if config.use_mock_db:
        log.warning("USE_MOCK_DB=true — database in-memory, DATA TIDAK TERSIMPAN setelah restart.")
        return db
    try:
        await db.command("ping")
        log.info("MongoDB terhubung: %s", config.mongo_url.split("@")[-1])
        return db
    except Exception as e:  # noqa: BLE001
        log.error("MongoDB tidak terjangkau (%s). Beralih ke database in-memory — DATA TIDAK TERSIMPAN. "
                  "Isi MONGO_URL yang benar untuk produksi.", e)
        use_mock_client()
        return get_db()


def set_db(db: AsyncIOMotorDatabase) -> None:
    """Dipakai test untuk menyuntikkan database mock."""
    global _db
    _db = db


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.outlets.create_index("qrToken", unique=True)
    await db.outlets.create_index("code", unique=True)
    await db.members.create_index("phone", unique=True)
    await db.members.create_index("deviceTokens")
    await db.stamps.create_index([("memberId", 1), ("day", 1)])
    await db.stamps.create_index([("outletId", 1), ("at", -1)])
    await db.stamps.create_index("requestId")
    await db.vouchers.create_index([("memberId", 1), ("status", 1)])
    await db.feedback.create_index([("outletId", 1), ("at", -1)])
    await db.admin_sessions.create_index("token", unique=True)
    await db.job_log.create_index([("job", 1), ("day", 1)])
    await db.staff_numbers.create_index("phone", unique=True)
    await db.outlet_transactions.create_index([("outletId", 1), ("day", 1)], unique=True)


async def get_settings(db: AsyncIOMotorDatabase) -> dict:
    doc = await db.settings.find_one({"_id": "main"})
    merged = {**DEFAULT_SETTINGS, **(doc or {})}
    merged["welcomeVoucher"] = {**DEFAULT_SETTINGS["welcomeVoucher"], **(merged.get("welcomeVoucher") or {})}
    return merged


async def bootstrap(db: AsyncIOMotorDatabase) -> None:
    """Index, settings default, dan admin pertama bila belum ada."""
    await ensure_indexes(db)
    if not await db.settings.find_one({"_id": "main"}):
        await db.settings.insert_one({**DEFAULT_SETTINGS, "adminEmail": config.admin_email})
    if await db.admin_users.count_documents({}) == 0:
        await db.admin_users.insert_one(
            {
                "_id": "adm_default",
                "name": config.default_admin_name,
                "role": "CRM Lead",
                "areas": [],
                "pinHash": hash_pin(config.default_admin_pin),
                "active": True,
                "failedAttempts": 0,
                "lockedUntil": None,
                "createdAt": iso(now_utc()),
            }
        )
