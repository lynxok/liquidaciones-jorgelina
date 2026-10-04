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

@app.get("/static/lynx_logo_color.png")
def get_lynx_logo():
    logo_path = os.path.join(STATIC_DIR, "lynx_logo_color.png")
    if os.path.exists(logo_path):
        return FileResponse(logo_path, media_type="image/png")
    return JSONResponse(status_code=404, content={"error": "Logo no encontrado"})

@app.get("/static/icon-192.png")
@app.get("/icon-192.png")
def get_icon_192():
    icon_path = os.path.join(STATIC_DIR, "icon-192.png")
    if os.path.exists(icon_path):
        return FileResponse(icon_path, media_type="image/png")
    return JSONResponse(status_code=404, content={"error": "Icono no encontrado"})

@app.get("/static/icon-512.png")
@app.get("/icon-512.png")
def get_icon_512():
    icon_path = os.path.join(STATIC_DIR, "icon-512.png")
    if os.path.exists(icon_path):
        return FileResponse(icon_path, media_type="image/png")
    return JSONResponse(status_code=404, content={"error": "Icono no encontrado"})

@app.get("/manifest.json")
def get_manifest():
    manifest_path = os.path.join(STATIC_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        return FileResponse(manifest_path, media_type="application/manifest+json")
    return JSONResponse(status_code=404, content={"error": "Manifest no encontrado"})

@app.get("/sw.js")
def get_sw():
    sw_path = os.path.join(STATIC_DIR, "sw.js")
    if os.path.exists(sw_path):
        return FileResponse(sw_path, media_type="application/javascript")
    return JSONResponse(status_code=404, content={"error": "Service Worker no encontrado"})

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

class PorcentajeUpdateRequest(BaseModel):
    nombre: str
    porcentaje: float

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

@app.post("/api/profesionales/porcentaje")
def update_porcentaje(req: PorcentajeUpdateRequest):
    """Guarda o actualiza el porcentaje correspondiente que se le da del total facturado neto a cada medico."""
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO profesionales_perfiles (nombre, porcentaje_honorarios, actualizado_en)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (nombre) DO UPDATE SET porcentaje_honorarios = EXCLUDED.porcentaje_honorarios, actualizado_en = CURRENT_TIMESTAMP
    ''', (req.nombre, req.porcentaje))
    conn.commit()
    conn.close()
    return {"success": True}

class ProfesionalCreateRequest(BaseModel):
    nombre: str

@app.post("/api/profesionales/nuevo")
def create_profesional(req: ProfesionalCreateRequest):
    """Permite dar de alta un nuevo profesional al equipo médico."""
    clean_nombre = req.nombre.strip()
    if not clean_nombre:
        return JSONResponse(status_code=400, content={"success": False, "error": "El nombre no puede estar vacío."})
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO profesionales_perfiles (nombre, porcentaje_honorarios, actualizado_en)
        VALUES (?, 100, CURRENT_TIMESTAMP)
        ON CONFLICT (nombre) DO NOTHING
    ''', (clean_nombre,))
    conn.commit()
    conn.close()
    return {"success": True, "nombre": clean_nombre}

class PorcentajeParticularUpdateRequest(BaseModel):
    nombre: str
    porcentaje: float

@app.post("/api/profesionales/porcentaje_particular")
def update_porcentaje_particular(req: PorcentajeParticularUpdateRequest):
    """Guarda o actualiza el porcentaje de honorarios para atenciones particulares de un médico."""
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO profesionales_perfiles (nombre, porcentaje_particular, actualizado_en)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (nombre) DO UPDATE SET porcentaje_particular = EXCLUDED.porcentaje_particular, actualizado_en = CURRENT_TIMESTAMP
    ''', (req.nombre, req.porcentaje))
    conn.commit()
    conn.close()
    return {"success": True}

class PacienteCreateRequest(BaseModel):
    nombre: str
    apellido: str

@app.get("/api/pacientes")
def get_pacientes(q: str = ""):
    """Busca pacientes por coincidencia en nombre o apellido."""
    conn = database.get_db_connection()
    c = conn.cursor()
    q_clean = q.strip()
    if q_clean:
        param = f"%{q_clean}%"
        c.execute("""
            SELECT id, nombre, apellido, TRIM(apellido || ' ' || nombre) AS nombre_completo
            FROM pacientes
            WHERE apellido ILIKE ? OR nombre ILIKE ? OR (apellido || ' ' || nombre) ILIKE ? OR (nombre || ' ' || apellido) ILIKE ?
            ORDER BY apellido ASC, nombre ASC
            LIMIT 30
        """, (param, param, param, param))
    else:
        c.execute("""
            SELECT id, nombre, apellido, TRIM(apellido || ' ' || nombre) AS nombre_completo
            FROM pacientes
            ORDER BY apellido ASC, nombre ASC
            LIMIT 50
        """)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/pacientes")
def create_paciente(req: PacienteCreateRequest):
    nom = req.nombre.strip()
    ape = req.apellido.strip()
    if not ape and not nom:
        return JSONResponse(status_code=400, content={"success": False, "error": "Debe especificar al menos un apellido o nombre."})
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, nombre, apellido FROM pacientes WHERE LOWER(apellido) = LOWER(?) AND LOWER(nombre) = LOWER(?)", (ape, nom))
    existing = c.fetchone()
    if existing:
        conn.close()
        return {"success": True, "id": existing["id"], "nombre": existing["nombre"], "apellido": existing["apellido"]}
    c.execute("INSERT INTO pacientes (nombre, apellido) VALUES (?, ?)", (nom, ape))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"success": True, "id": new_id, "nombre": nom, "apellido": ape}

class ParticularCreateRequest(BaseModel):
    periodo_id: int
    fecha: str = ""
    paciente: str
    profesional: str
    prestacion: str
    importe: float
    porcentaje_aplicado: float = 100.0

@app.post("/api/particulares")
def create_particular(req: ParticularCreateRequest):
    conn = database.get_db_connection()
    c = conn.cursor()
    monto_prof = round(float(req.importe) * (float(req.porcentaje_aplicado) / 100.0), 2)
    c.execute("""
        INSERT INTO atenciones_particulares (periodo_id, fecha, paciente, profesional, prestacion, importe, porcentaje_aplicado, monto_profesional)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (req.periodo_id, req.fecha, req.paciente.strip(), req.profesional.strip(), req.prestacion.strip(), req.importe, req.porcentaje_aplicado, monto_prof))
    
    # Auto registrar en pacientes si no existe
    pac_parts = req.paciente.strip().split()
    if pac_parts:
        ape = pac_parts[0]
        nom = " ".join(pac_parts[1:]) if len(pac_parts) > 1 else ""
        c.execute("SELECT id FROM pacientes WHERE LOWER(apellido) = LOWER(?) AND LOWER(nombre) = LOWER(?)", (ape, nom))
        if not c.fetchone():
            c.execute("INSERT INTO pacientes (nombre, apellido) VALUES (?, ?)", (nom, ape))
            
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/particulares/{item_id}")
def delete_particular(item_id: int):
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM atenciones_particulares WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return {"success": True}

class LaboratorioCreateRequest(BaseModel):
    periodo_id: int
    profesional: str
    fecha: str = ""
    concepto: str
    monto_total: float
    porcentaje_profesional: float = 0.0

@app.post("/api/laboratorios")
def create_laboratorio(req: LaboratorioCreateRequest):
    conn = database.get_db_connection()
    c = conn.cursor()
    monto_prof = round(float(req.monto_total) * (float(req.porcentaje_profesional) / 100.0), 2)
    c.execute("""
        INSERT INTO gastos_laboratorio (periodo_id, profesional, fecha, concepto, monto_total, porcentaje_profesional, monto_profesional)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (req.periodo_id, req.profesional.strip(), req.fecha, req.concepto.strip(), req.monto_total, req.porcentaje_profesional, monto_prof))
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/laboratorios/{item_id}")
def delete_laboratorio(item_id: int):
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM gastos_laboratorio WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return {"success": True}

class ProtesisCreateRequest(BaseModel):
    periodo_id: int
    profesional: str
    paciente_nombre: str
    paciente_apellido: str
    trabajo: str
    importe: float
    porcentaje_profesional: float = 0.0
    fecha: str = ""

@app.post("/api/protesis")
def create_protesis(req: ProtesisCreateRequest):
    conn = database.get_db_connection()
    c = conn.cursor()
    monto_prof = round(float(req.importe) * (float(req.porcentaje_profesional) / 100.0), 2)
    nom = req.paciente_nombre.strip()
    ape = req.paciente_apellido.strip()
    c.execute("""
        INSERT INTO ingresos_protesis (periodo_id, profesional, paciente_nombre, paciente_apellido, trabajo, importe, porcentaje_profesional, monto_profesional, fecha)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (req.periodo_id, req.profesional.strip(), nom, ape, req.trabajo.strip(), req.importe, req.porcentaje_profesional, monto_prof, req.fecha))
    
    # Auto guardar o verificar en directorio de pacientes
    if ape or nom:
        c.execute("SELECT id FROM pacientes WHERE LOWER(apellido) = LOWER(?) AND LOWER(nombre) = LOWER(?)", (ape, nom))
        if not c.fetchone():
            c.execute("INSERT INTO pacientes (nombre, apellido) VALUES (?, ?)", (nom, ape))

    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/protesis/{item_id}")
def delete_protesis(item_id: int):
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM ingresos_protesis WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return {"success": True}

class LoginRequest(BaseModel):
    email: str
    password: str

class PasswordChangeRequest(BaseModel):
    email: str
    current_password: str
    new_password: str

@app.post("/api/auth/login")
def login(req: LoginRequest):
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, email, password_hash, salt, nombre FROM usuarios WHERE LOWER(email) = LOWER(?)", (req.email.strip(),))
    user = c.fetchone()
    conn.close()
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "Usuario o contraseña incorrectos."})
    
    if not database.verify_password(req.password, user["salt"], user["password_hash"]):
        return JSONResponse(status_code=401, content={"success": False, "error": "Usuario o contraseña incorrectos."})
    
    # Retornar datos de usuario autenticado
    return {
        "success": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "nombre": user["nombre"]
        }
    }

@app.post("/api/auth/change-password")
def change_password(req: PasswordChangeRequest):
    if len(req.new_password) < 6:
        return JSONResponse(status_code=400, content={"success": False, "error": "La nueva contraseña debe tener al menos 6 caracteres."})
    
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, email, password_hash, salt FROM usuarios WHERE LOWER(email) = LOWER(?)", (req.email.strip(),))
    user = c.fetchone()
    if not user:
        conn.close()
        return JSONResponse(status_code=404, content={"success": False, "error": "Usuario no encontrado."})
    
    if not database.verify_password(req.current_password, user["salt"], user["password_hash"]):
        conn.close()
        return JSONResponse(status_code=400, content={"success": False, "error": "La contraseña actual no es correcta."})
    
    new_salt, new_hash = database.hash_password(req.new_password)
    c.execute('''
        UPDATE usuarios
        SET password_hash = ?, salt = ?, actualizado_en = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (new_hash, new_salt, user["id"]))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Contraseña actualizada con éxito."}

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

    # Atenciones Particulares
    c.execute("SELECT * FROM atenciones_particulares WHERE periodo_id = ? ORDER BY id DESC", (periodo_id,))
    particulares = c.fetchall()

    # Gastos de Laboratorio
    c.execute("SELECT * FROM gastos_laboratorio WHERE periodo_id = ? ORDER BY id DESC", (periodo_id,))
    laboratorios = c.fetchall()

    # Ingresos por Prótesis
    c.execute("SELECT * FROM ingresos_protesis WHERE periodo_id = ? ORDER BY id DESC", (periodo_id,))
    protesis = c.fetchall()
    
    conn.close()
    return {
        "periodo": dict(periodo),
        "profesionales": [dict(p) for p in profs],
        "rechazos": [dict(r) for r in rechazos],
        "prof_items": [dict(pi) for pi in prof_items],
        "logs": [dict(l) for l in logs],
        "particulares": [dict(pa) for pa in particulares],
        "laboratorios": [dict(la) for la in laboratorios],
        "protesis": [dict(pr) for pr in protesis]
    }

@app.delete("/api/periodo/{periodo_id}")
def delete_periodo(periodo_id: int):
    """Elimina por completo un período y todos sus registros en cascada."""
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, nombre FROM periodos WHERE id = ?", (periodo_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return JSONResponse(status_code=404, content={"success": False, "error": "Período no encontrado."})
    
    c.execute("DELETE FROM periodos WHERE id = ?", (periodo_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Período '{row['nombre']}' eliminado con éxito."}

@app.post("/api/process")
async def process_month(
    request: Request,
    period_name: str = Form(...),
    use_existing: bool = Form(False),
    overwrite_existing: bool = Form(False),
    osde_file: UploadFile = File(default=None),
    files: List[UploadFile] = File(default=[])
):
    try:
        # Normalizar flags booleanos si vienen como string
        if isinstance(use_existing, str):
            use_existing = use_existing.lower() in ("true", "1", "t")
        if isinstance(overwrite_existing, str):
            overwrite_existing = overwrite_existing.lower() in ("true", "1", "t")

        if use_existing:
            # Use current project directory PDFs
            target_osde = os.path.join(BASE_DIR, "LiquidacionOSDE.pdf")
            if not os.path.exists(target_osde):
                return {"success": False, "error": "No se encontró LiquidacionOSDE.pdf en la carpeta del proyecto."}
                
            prof_files_paths = [f for f in sorted(glob.glob(os.path.join(BASE_DIR, "liquidacion*.pdf"))) if os.path.basename(f) != "LiquidacionOSDE.pdf"]
            if not prof_files_paths:
                return {"success": False, "error": "No se encontraron archivos de liquidación de profesionales en la carpeta."}
        else:
            import tempfile
            upload_dir = os.path.join(tempfile.gettempdir(), "uploads", period_name.replace(" ", "_"))
            os.makedirs(upload_dir, exist_ok=True)
            
            target_osde = None
            prof_files_paths = []

            # 1. Si vino archivo específico de OSDE
            if osde_file and osde_file.filename:
                osde_path = os.path.join(upload_dir, f"OSDE_{osde_file.filename}")
                with open(osde_path, "wb") as buffer:
                    shutil.copyfileobj(osde_file.file, buffer)
                target_osde = osde_path

            # 2. Revisar archivos en `files` (tanto subida múltiple clásica como subida por profesional)
            # También soportar campos dinámicos prof_file_<nombre>
            form_data = await request.form()
            for key, val in form_data.items():
                if key.startswith("prof_file_") and hasattr(val, "filename") and val.filename:
                    p_path = os.path.join(upload_dir, val.filename)
                    with open(p_path, "wb") as buffer:
                        shutil.copyfileobj(val.file, buffer)
                    prof_files_paths.append(p_path)

            for f in files:
                if not f.filename:
                    continue
                target_path = os.path.join(upload_dir, f.filename)
                with open(target_path, "wb") as buffer:
                    shutil.copyfileobj(f.file, buffer)
                if not target_osde and "OSDE" in f.filename.upper():
                    target_osde = target_path
                else:
                    prof_files_paths.append(target_path)
                    
            if not target_osde:
                return {"success": False, "error": "Es obligatorio incluir el archivo de Liquidación OSDE (.pdf)."}
            if not prof_files_paths:
                return {"success": False, "error": "Debe incluir al menos una liquidación de profesional (.pdf)."}
                
        # Run reconciliation
        res = matcher.reconcile_period(period_name, target_osde, prof_files_paths, overwrite_existing=overwrite_existing)
        return {"success": True, "periodo_id": res["periodo_id"]}
        
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    print("Iniciando servidor web de Liquidaciones en http://localhost:8080 ...")
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)
