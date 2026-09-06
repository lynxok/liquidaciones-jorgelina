"""
Mapeo de Nomencladores Odontológicos:
Traduce entre la codificación de las planillas de los profesionales (formato estándar con puntos)
y la codificación interna de OSDE (código numérico de 7 dígitos con prefijo 18/19).
"""

PROF_TO_OSDE = {
    '01.01': '1810100',      # Examen / Diagnóstico / Consulta
    '01.04': '1810400',      # Consulta de urgencia
    '01.06': '1810600',      # Interconsulta con especialista
    '02.22': '1822200',      # Restauraciones
    '03.01': '1830100',      # Endodoncia unirradicular
    '03.02': '1830200',      # Endodoncia multirradicular
    '05.04': '1850400',      # Módulo de prevención / Enseñanza higiene
    '05.05': '1850500',      # Sellante de puntos y fisuras
    '06.02.08': '1860208',    # Cuota tratamiento ortopedia mensual
    '06.03.03': '1860303',    # Tratamiento de ortodoncia
    '06.03.07': '1860307',    # Inicio ortodoncia
    '06.03.08': '1860308',    # Cuota tratamiento ortodoncia x 17
    '06.303.08': '1860308',   # Variante de ortodoncia x 17
    '07.01': '1870100',      # Consulta odontopediatrica / Fichado y motivación
    '07.02': '1870200',      # Odontopediatría
    '07.04': '1870400',      # Odontopediatría
    '07.05': '1870500',      # Odontopediatría
    '08.02': '1880200',      # Tratamiento de gingivitis
    '09.01.01': '1890101',    # Radiografía periapical
    '09.01.13': '1890113',    # Radiografía oclusal / ortopanto
    '09.01.14': '1890114',    # Radiografía seriada
    '10.01': '1900100',      # Extracción dentaria / Cirugía
}

OSDE_TO_PROF = {v: k for k, v in PROF_TO_OSDE.items()}
OSDE_TO_PROF['1860303'] = '06.03.03'
OSDE_TO_PROF['1840210'] = '04.02.10'

def normalize_prof_code(code: str) -> str:
    return str(code).strip().replace(' ', '')

def prof_to_osde_code(prof_code: str) -> str:
    clean = normalize_prof_code(prof_code)
    if clean in PROF_TO_OSDE:
        return PROF_TO_OSDE[clean]
    parts = clean.split('.')
    if len(parts) == 2:
        try:
            cap = int(parts[0])
            sub = int(parts[1])
            if cap == 10:
                return f"190{sub:02d}00" if sub < 10 else f"19{sub:03d}0"
            return f"18{cap}{sub:02d}00"
        except ValueError:
            pass
    elif len(parts) == 3:
        try:
            cap = int(parts[0])
            sub1 = int(parts[1]) % 100
            sub2 = int(parts[2])
            return f"18{cap}{sub1:02d}{sub2:02d}"
        except ValueError:
            pass
    return clean

def osde_to_prof_code(osde_code: str) -> str:
    c = str(osde_code).strip()
    return OSDE_TO_PROF.get(c, c)
