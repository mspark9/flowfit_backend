import pg8000.dbapi as pg8000
from config import settings


def get_connection():
    """pg8000 DB 커넥션 반환 — 사용 후 반드시 close() 호출"""
    conn = pg8000.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_database,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT set_config('TimeZone', %s, false)", (settings.app_timezone,))
    cur.fetchone()
    cur.close()
    return conn
