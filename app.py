import os
import glob
import shutil
from typing import List
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import database
import matcher

app = FastAPI(title="Liquidaciones Odontológicas OSDE")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.on_event("startup")
def startup():
    database.init_db()

from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

@app.get("/", response_class=HTMLResponse)
def index():
    index_path = os.path.join(TEMPLATES_DIR, "index.html")
    return FileResponse(index_path)

@app.get("/static/logo_ls.jpeg")
@app.get("/favicon.ico")
def get_logo():
    logo_path = os.path.join(STATIC_DIR, "logo_ls.jpeg")
    if os.path.exists(logo_path):
        return FileResponse(logo_path, media_type="image/jpeg")
    return JSONResponse(status_code=404, content={"error": "Logo no encontrado"})

@app.get("/api/heartbeat")
def heartbeat():
    """Heartbeat keep-alive para mantener despierta la base de datos de Supabase y purgar archivos expirados."""
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT 1 AS alive")
    res = c.fetchone()
    conn.close()
    
    # Intentar purgar archivos expirados (+90 dias)
    try:
        database.purge_expired_files()
    except Exception as e:
        print("Error en purga automatica:", e)
        
    return {"status": "ok", "db": "connected", "alive": res.get("alive") if res else 1}

@app.get("/api/profesionales")
def get_profesionales():
    """Obtiene el historial consolidado de todos los medicos sincronizados y sus fotos de perfil."""
    conn = database.get_db_connection()
    c = conn.cursor()
    # Asegurar que todos los que estan en liquidaciones existan en perfiles
    c.execute('''
        INSERT INTO profesionales_perfiles (nombre)
        SELECT DISTINCT profesional FROM liquidacion_resumen_profesional
        ON CONFLICT (nombre) DO NOTHING
    ''')
    conn.commit()
    
    c.execute("SELECT * FROM profesionales_perfiles ORDER BY nombre ASC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

from pydantic import BaseModel

class AvatarUpdateRequest(BaseModel):
    nombre: str
    avatar_url: str

@app.post("/api/profesionales/avatar")
def update_avatar(req: AvatarUpdateRequest):
    """Guarda o actualiza la foto de avatar (URL o base64) de un medico en Supabase."""
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO profesionales_perfiles (nombre, avatar_url, actualizado_en)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (nombre) DO UPDATE SET avatar_url = EXCLUDED.avatar_url, actualizado_en = CURRENT_TIMESTAMP
    ''', (req.nombre, req.avatar_url))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/periodos")
def get_periodos():
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM periodos ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/periodo/{periodo_id}")
def get_periodo_detail(periodo_id: int):
    conn = database.get_db_connection()
    c = conn.cursor()
    
    # Periodo
    c.execute("SELECT * FROM periodos WHERE id = ?", (periodo_id,))
    periodo = c.fetchone()
    if not periodo:
        conn.close()
        return JSONResponse(status_code=404, content={"error": "Período no encontrado"})
        
    # Profesionales resumen
    c.execute("SELECT * FROM liquidacion_resumen_profesional WHERE periodo_id = ? ORDER BY total_neto_liquidable DESC", (periodo_id,))
    profs = c.fetchall()
    
    # Rechazos
    c.execute("SELECT * FROM osde_items WHERE periodo_id = ? AND estado = 'RECHAZADO' ORDER BY page ASC", (periodo_id,))
    rechazos = c.fetchall()
    
    # Prof items (prestaciones)
    c.execute("SELECT * FROM prof_items WHERE periodo_id = ? ORDER BY profesional ASC, fecha ASC", (periodo_id,))
    prof_items = c.fetchall()
    
    # Logs ajustes
    c.execute("SELECT * FROM logs_ajustes WHERE periodo_id = ? ORDER BY id ASC", (periodo_id,))
    logs = c.fetchall()
    
    conn.close()
    return {
        "periodo": dict(periodo),
        "profesionales": [dict(p) for p in profs],
        "rechazos": [dict(r) for r in rechazos],
        "prof_items": [dict(pi) for pi in prof_items],
        "logs": [dict(l) for l in logs]
    }

@app.post("/api/process")
async def process_month(
    period_name: str = Form(...),
    use_existing: bool = Form(False),
    files: List[UploadFile] = File(default=[])
):
    try:
        # Normalizar use_existing si viene como string
        if isinstance(use_existing, str):
            use_existing = use_existing.lower() in ("true", "1", "t")

        if use_existing:
            # Use current project directory PDFs
            osde_file = os.path.join(BASE_DIR, "LiquidacionOSDE.pdf")
            if not os.path.exists(osde_file):
                return {"success": False, "error": "No se encontró LiquidacionOSDE.pdf en la carpeta del proyecto."}
                
            prof_files = [f for f in sorted(glob.glob(os.path.join(BASE_DIR, "liquidacion*.pdf"))) if os.path.basename(f) != "LiquidacionOSDE.pdf"]
            if not prof_files:
                return {"success": False, "error": "No se encontraron archivos de liquidación de profesionales en la carpeta."}
        else:
            if not files or len(files) == 0:
                return {"success": False, "error": "Por favor selecciona los archivos PDF a procesar (Liquidación OSDE y planillas)."}

            # Save uploaded files into a temporary directory (compatible with /tmp on Vercel)
            import tempfile
            upload_dir = os.path.join(tempfile.gettempdir(), "uploads", period_name.replace(" ", "_"))
            os.makedirs(upload_dir, exist_ok=True)
            
            osde_file = None
            prof_files = []
            
            for f in files:
                if not f.filename:
                    continue
                target_path = os.path.join(upload_dir, f.filename)
                with open(target_path, "wb") as buffer:
                    shutil.copyfileobj(f.file, buffer)
                if "OSDE" in f.filename.upper():
                    osde_file = target_path
                else:
                    prof_files.append(target_path)
                    
            if not osde_file:
                return {"success": False, "error": "Es obligatorio incluir el archivo Liquidacion OSDE (.pdf) con 'OSDE' en su nombre."}
            if not prof_files:
                return {"success": False, "error": "Debe incluir al menos una liquidación de profesional (.pdf)."}
                
        # Run reconciliation
        res = matcher.reconcile_period(period_name, osde_file, prof_files)
        return {"success": True, "periodo_id": res["periodo_id"]}
        
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    print("Iniciando servidor web de Liquidaciones en http://localhost:8080 ...")
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)
