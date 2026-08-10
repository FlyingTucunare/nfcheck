import os, psycopg2, psycopg2.extras
from cryptography.fernet import Fernet

def _env(k):
    v = os.environ.get(k)
    if not v:
        raise RuntimeError(f"Variavel {k} ausente no .env")
    return v

FERNET = Fernet(_env("NFCHECK_FERNET_KEY").encode())
JWT_SECRET = _env("NFCHECK_JWT_SECRET")
DIR_CERTS = os.environ.get("DIR_CERTS", "/var/lib/nfcheck/certs")
DIR_XML   = os.environ.get("DIR_XML",   "/var/lib/nfcheck/xml")

def get_conn():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        dbname=_env("DB_NAME"), user=_env("DB_USER"), password=_env("DB_PASS"),
    )

def q(sql, params=None, one=False):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params or ())
        if cur.description:
            rows = cur.fetchall()
            conn.commit()
            return (dict(rows[0]) if rows else None) if one else [dict(r) for r in rows]
        conn.commit()
        return None
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
