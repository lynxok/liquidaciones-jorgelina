import os
import psycopg2
from psycopg2.extras import RealDictCursor

# Default PostgreSQL / Supabase connection URL
DEFAULT_DB_URL = "postgresql://postgres.mvcobbbsdzgwfpzyowrh:FFWhL2Z7QNXpjfeg@aws-0-us-east-2.pooler.supabase.com:6543/postgres"

def get_db_url():
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or DEFAULT_DB_URL

class PostgresConnectionWrapper:
    """Wrapper that adapts psycopg2 connection to behave conveniently like sqlite3 connection."""
    def __init__(self, pg_conn):
        self._conn = pg_conn

    def cursor(self):
        return PostgresCursorWrapper(self._conn.cursor(cursor_factory=RealDictCursor))

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

class PostgresCursorWrapper:
    """Adapts ? parameter style to %s parameter style and supports .lastrowid via RETURNING id."""
    def __init__(self, pg_cur):
        self._cur = pg_cur
        self.lastrowid = None

    def execute(self, query, params=None):
        # Translate ? to %s for PostgreSQL
        converted_query = query.replace("?", "%s")
        
        # If it is an INSERT into a table that has an auto-increment id, automatically append RETURNING id
        trimmed = converted_query.strip().rstrip(";")
        is_insert = trimmed.upper().startswith("INSERT INTO")
        has_returning = "RETURNING" in trimmed.upper()
        
        if is_insert and not has_returning:
            converted_query = trimmed + " RETURNING id;"

        if params:
            self._cur.execute(converted_query, params)
        else:
            self._cur.execute(converted_query)

        if is_insert and not has_returning:
            try:
                row = self._cur.fetchone()
                if row:
                    self.lastrowid = row.get("id") if isinstance(row, dict) else row[0]
            except Exception:
                self.lastrowid = None

        return self

    def executemany(self, query, params_seq):
        converted_query = query.replace("?", "%s")
        return self._cur.executemany(converted_query, params_seq)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def close(self):
        self._cur.close()

def get_db_connection():
    db_url = get_db_url()
    conn = psycopg2.connect(db_url)
    return PostgresConnectionWrapper(conn)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Table: periodos
    c.execute('''
        CREATE TABLE IF NOT EXISTS periodos (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            fecha_proceso TEXT NOT NULL,
            osde_tramite TEXT,
            osde_efector TEXT,
            osde_fecha_emision TEXT,
            total_osde_liquidado NUMERIC DEFAULT 0,
            total_prof_declarado NUMERIC DEFAULT 0,
            total_rechazados_cant INTEGER DEFAULT 0,
            total_rechazados_monto NUMERIC DEFAULT 0,
            diferencia_neta NUMERIC DEFAULT 0
        )
    ''')
    
    # Table: osde_items
    c.execute('''
        CREATE TABLE IF NOT EXISTS osde_items (
            id SERIAL PRIMARY KEY,
            periodo_id INTEGER NOT NULL REFERENCES periodos(id) ON DELETE CASCADE,
            page INTEGER,
            id_osde TEXT,
            afiliado TEXT,
            paciente TEXT,
            fecha TEXT,
            codigo TEXT,
            dte TEXT,
            descripcion TEXT,
            estado TEXT,
            imp_facturado NUMERIC,
            imp_liquidado NUMERIC,
            diferencia NUMERIC,
            motivo_rechazo TEXT,
            profesional_asignado TEXT
        )
    ''')
    
    # Table: prof_items
    c.execute('''
        CREATE TABLE IF NOT EXISTS prof_items (
            id SERIAL PRIMARY KEY,
            periodo_id INTEGER NOT NULL REFERENCES periodos(id) ON DELETE CASCADE,
            profesional TEXT,
            archivo TEXT,
            fecha TEXT,
            paciente TEXT,
            plan TEXT,
            afiliado TEXT,
            cod_prest TEXT,
            cod_osde_equivalente TEXT,
            descripcion TEXT,
            imp_neto NUMERIC,
            imp_final NUMERIC,
            imp_liquidado_osde NUMERIC DEFAULT 0,
            diferencia_osde NUMERIC DEFAULT 0,
            estado_conciliacion TEXT DEFAULT 'PENDIENTE'
        )
    ''')
    
    # Table: liquidacion_resumen_profesional
    c.execute('''
        CREATE TABLE IF NOT EXISTS liquidacion_resumen_profesional (
            id SERIAL PRIMARY KEY,
            periodo_id INTEGER NOT NULL REFERENCES periodos(id) ON DELETE CASCADE,
            profesional TEXT NOT NULL,
            archivo TEXT,
            total_declarado NUMERIC DEFAULT 0,
            total_liquidado_osde NUMERIC DEFAULT 0,
            total_descuentos_rechazos NUMERIC DEFAULT 0,
            total_diferencias NUMERIC DEFAULT 0,
            total_neto_liquidable NUMERIC DEFAULT 0,
            total_prestaciones INTEGER DEFAULT 0,
            prestaciones_rechazadas INTEGER DEFAULT 0
        )
    ''')
    
    # Table: logs_ajustes
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs_ajustes (
            id SERIAL PRIMARY KEY,
            periodo_id INTEGER NOT NULL REFERENCES periodos(id) ON DELETE CASCADE,
            profesional TEXT,
            afiliado TEXT,
            paciente TEXT,
            prestacion TEXT,
            tipo_ajuste TEXT,
            monto_declarado NUMERIC,
            monto_osde NUMERIC,
            diferencia_ajuste NUMERIC,
            motivo TEXT
        )
    ''')

    # Table: periodos_archivos (Archivos respaldatorios con caducidad de 90 dias)
    c.execute('''
        CREATE TABLE IF NOT EXISTS periodos_archivos (
            id SERIAL PRIMARY KEY,
            periodo_id INTEGER NOT NULL REFERENCES periodos(id) ON DELETE CASCADE,
            tipo TEXT NOT NULL,
            nombre_archivo TEXT NOT NULL,
            profesional TEXT,
            tamano_bytes INTEGER,
            contenido_bytes BYTEA,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expira_en TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '90 days')
        )
    ''')
    
    conn.commit()
    conn.close()

def store_periodo_file(periodo_id: int, tipo: str, nombre_archivo: str, file_bytes: bytes, profesional: str = None):
    """Guarda el archivo original en Supabase PostgreSQL con fecha de expiracion de 90 dias."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO periodos_archivos (
            periodo_id, tipo, nombre_archivo, profesional, tamano_bytes, contenido_bytes
        ) VALUES (?, ?, ?, ?, ?, ?)
    ''', (periodo_id, tipo, nombre_archivo, profesional, len(file_bytes), psycopg2.Binary(file_bytes)))
    conn.commit()
    conn.close()

def purge_expired_files():
    """Libera almacenamiento purgando el binario de archivos con mas de 90 dias, conservando el registro y todas las tablas."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE periodos_archivos SET contenido_bytes = NULL WHERE expira_en < CURRENT_TIMESTAMP AND contenido_bytes IS NOT NULL")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully on Supabase!")
