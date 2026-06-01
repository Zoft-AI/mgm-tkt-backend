"""
Seed auth_users table with existing MGM users.
Run this ONCE to populate auth_users with matching profile IDs.

Usage: python scripts/seed_auth_users.py
"""

import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import asyncpg
import bcrypt

# All MGM users: (email, password, display_name)
USERS = [
    ("payouts@mgmhealthcare.in", "OYqUPCoirIVQ1mQj", "Charanya"),
    ("ganesh.v@mgmhealthcare.in", "DWr3JnWSQnWgwWQT", "Ganesh V"),
    ("ilaiah.d@mgmhealthcare.in", "wDOz5xffgrJnMvjo", "Ilaiah D"),
    ("sajitha.k@mgmhealthcare.in", "2APKYEjPeib6DYtn", "Sajitha K"),
    ("moorthy.s@mgmhealthcare.in", "4ZOogrB11PN8xN48", "Moorthy S"),
    ("prashanth.r@mgmhealthcare.in", "WcfdWL5k8JUaVmhR", "Dr. Prashanth"),
    ("purchase@mgmhealthcare.in", "DTFGbJ0cSxfA5WL9", "Ramesh"),
    ("rohit.m@mgmhealthcare.in", "CNh6MCbRCKz8CSpy", "Rohit M"),
    ("banu.m@mgmhealthcare.in", "K4PZkl9WWr6XdpOo", "Bhanu"),
    ("marketing.mis@mgmhealthcare.in", "LbdT34yZk2G5DmqE", "Revathi"),
    ("senthilkumar.a@mgmhealthcare.in", "GxhRv6ywClIQXd6Z", "Senthilkumar"),
    ("nilesh.m@mgmhealthcare.in", "s3Mk4EjLEELwzP6L", "Nilesh M"),
    ("accountspayable@mgmhealthcare.in", "J2IWIcbmLZFIGkwk", "Chirag/Bh"),
    ("bharanikrishnan.r@mgmhcmalar.in", "NJbBeVvTO0abZQFs", "Bharani Krishnan"),
    ("manikandan.k@mgmhealthcare.in", "MVFM36TMi5AL9ruv", "Manikandan K"),
    ("manikandan.r@mgmhealthcare.in", "WMxECkPgUB7n3Q4Z", "Manikandan R"),
    ("krishan.bhardwaj@mgmhealthcare.in", "LzXH15V6u0BMGhc5", "Krishan"),
    ("kesavan.k@mgmhealthcare.in", "sogahZa7GJfCdzf5", "Kesavan"),
    ("salamath.m@mgmhealthcare.in", "XwKwfqQA4GAoxMJK", "Salamath"),
    ("marketing.mgmci@mgmcancerinstitute.in", "AYyt2VIDzKnoKbrM", "Lekha"),
    ("hemakumar.p@mgmcancerinstitute.in", "ohQPkxygAn0w2Jrg", "Hemakumar"),
    ("saravanakumar.r@mgmhealthcare.in", "fJqCSnKwsCdKbV7M", "Saravanakumar"),
    ("pathmanaban@mgmhealthcare.in", "NdFHmiPymKsEi9lh", "Pathmanaban"),
    ("itsupport.mgmci@mgmcancerinstitute.in", "8FrWncHG", "Venkat Ra"),
    ("sam.y@mgmcancerinstitute.in", "iqifcwzCFo5EQj6B", "Sam"),
    ("sujith.s@mgmhealthcare.in", "8FrWncHGPPRR1VAg", "Dr. Sujith"),
    ("mis.marketing@mgmhcmalar.in", "xYxwDuPuvOcKCfXy", "Divya"),
    ("jayaprakash.n@mgmhcmalar.in", "2pRWxSe3nBikEefQ", "Jayaprakash"),
    ("venugopal.b@mgmhealthcare.in", "DoEGfi2Y2pz3Xti7", "Venugopal"),
    ("umamaheswari.g@mgmhcmalar.in", "rVUoxbiALm5SybjS", "Umamaheswari"),
    ("internal.audit@mgmhcmalar.in", "HEpY2k89ejBCEY3v", "Sharada"),
    ("manodesilva.t@mgmhcmalar.in", "Fn64DGeb3lC3aAKA", "Manodesilva"),
    ("accounts.payable@mgmhcmalar.in", "ya95aBQ8FRhpV5VV", "Sudharsan"),
    ("ilamurugu.p@mgmhcmalar.in", "viBdm9AxaxiWw7lZ", "Ilamurugu"),
    ("sekar.v@mgmhcmalar.in", "mV01QbiqZvzNyCE5", "Sekar V"),
    ("mis@mgmsevenhills.in", "am2s5CVpZu8bZcO0", "Kumari"),
    ("audit@mgmsevenhills.in", "22r7tq20dz6jnNjD", "Krishna M"),
    ("hodmarketing@mgmsevenhills.in", "TJJ0FwYdlkgC1SKf", "Sanjay"),
    ("hodfinance@mgmsevenhills.in", "uGNF4Dzwj7UmnhGj", "Brahmaji"),
    ("coo@mgmsevenhills.in", "Kum7uNTwTdzAYm0Z", "Dr. Giri"),
    ("payments@mgmsevenhills.in", "HQ8rFa1Yb6hfhbd3", "Sekhar M"),
    ("hodit@mgmsevenhills.in", "Efggvgd1L7qDH1ig", "Ramesh D"),
    ("purchase@mgmsevenhills.in", "Bckefj4eq49TPngi", "Bhuva Lakshmi"),
    ("hodhr@mgmsevenhills.in", "vnK3ZsvJDrggcfoU", "BHANU Ch"),
]


async def seed():
    pool = await asyncpg.create_pool(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        database=os.environ.get("DB_NAME", "postgres"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ["DB_PASSWORD"],
        ssl="require",
    )

    async with pool.acquire() as conn:
        inserted = 0
        skipped = 0

        # Disable the trigger so it doesn't call create_new_user() for existing users
        await conn.execute(
            "ALTER TABLE public.auth_users DISABLE TRIGGER trigger_auth_user_created"
        )
        print("  Trigger disabled for seeding.")

        try:
            for email, password, name in USERS:
                email_lower = email.lower()

                profile = await conn.fetchrow(
                    "SELECT id FROM profiles WHERE email = $1", email_lower
                )

                if not profile:
                    print(f"  SKIP (no profile): {email_lower}")
                    skipped += 1
                    continue

                profile_id = profile["id"]

                existing = await conn.fetchrow(
                    "SELECT id FROM auth_users WHERE email = $1", email_lower
                )
                if existing:
                    print(f"  SKIP (already exists): {email_lower}")
                    skipped += 1
                    continue

                password_hash = bcrypt.hashpw(
                    password.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8")

                await conn.execute(
                    """INSERT INTO auth_users (id, email, password_hash, name, email_verified, provider, created_at)
                       VALUES ($1, $2, $3, $4, true, 'email', NOW())""",
                    profile_id, email_lower, password_hash, name
                )
                print(f"  OK: {email_lower} -> {profile_id}")
                inserted += 1
        finally:
            await conn.execute(
                "ALTER TABLE public.auth_users ENABLE TRIGGER trigger_auth_user_created"
            )
            print("  Trigger re-enabled.")

        print(f"\nDone! Inserted: {inserted}, Skipped: {skipped}")

    await pool.close()


if __name__ == "__main__":
    print("Seeding auth_users table...")
    asyncio.run(seed())
