from datetime import datetime
from typing import List, Dict, Any, Tuple
import nomenclator
import database

def reconcile_period(period_name: str, osde_path: str, prof_paths: List[str], parser_mod=None, overwrite_existing: bool = False) -> Dict[str, Any]:
    if parser_mod is None:
        import parser as parser_mod
        
    osde_meta, osde_items = parser_mod.parse_osde_pdf(osde_path)
    
    # 1. Validar que el archivo de OSDE corresponda al periodo indicado
    osde_fec = osde_meta.get('fecha_emision', '') # e.g. '24/08/2026'
    meses_map = {
        '01': ['enero', 'jan'], '02': ['febrero', 'feb'], '03': ['marzo', 'mar'],
        '04': ['abril', 'apr'], '05': ['mayo', 'may'], '06': ['junio', 'jun'],
        '07': ['julio', 'jul'], '08': ['agosto', 'ago', 'aug'], '09': ['septiembre', 'setiembre', 'sep'],
        '10': ['octubre', 'oct'], '11': ['noviembre', 'nov'], '12': ['diciembre', 'dic']
    }
    
    if osde_fec and len(osde_fec.split('/')) == 3:
        _, m_num, y_num = osde_fec.split('/')
        p_lower = period_name.lower()
        valid_keywords = meses_map.get(m_num, [])
        match_month = any(kw in p_lower for kw in valid_keywords) or (f"-{m_num}" in p_lower or f"/{m_num}" in p_lower)
        match_year = y_num in p_lower or y_num[-2:] in p_lower
        
        if not match_month:
            mes_nombre_detectado = valid_keywords[0].capitalize() if valid_keywords else m_num
            raise ValueError(
                f"El archivo de OSDE corresponde a {mes_nombre_detectado} {y_num} (Emisión: {osde_fec}), "
                f"pero indicaste el período '{period_name}'. Por favor verifica los archivos antes de procesar."
            )
            
    # 2. Verificar duplicados por número de trámite en Supabase
    tramite_osde = osde_meta.get('tramite')
    if tramite_osde:
        chk_conn = database.get_db_connection()
        chk_cur = chk_conn.cursor()
        chk_cur.execute("SELECT id, nombre FROM periodos WHERE osde_tramite = ?", (tramite_osde,))
        existing_p = chk_cur.fetchone()
        if existing_p:
            if overwrite_existing:
                # Eliminar periodo anterior para reemplazarlo limpiamente
                chk_cur.execute("DELETE FROM periodos WHERE id = ?", (existing_p['id'],))
                chk_conn.commit()
            else:
                chk_conn.close()
                raise ValueError(
                    f"Este trámite de OSDE ({tramite_osde}) ya fue liquidado anteriormente en el período '{existing_p['nombre']}'. Activa la opción 'Sobrescribir si ya existe' o elimina el período anterior para volver a cargarlo."
                )
        chk_conn.close()

    all_prof_meta = []
    all_prof_items = []
    for p_path in prof_paths:
        p_meta, p_items = parser_mod.parse_professional_pdf(p_path)
        all_prof_meta.append(p_meta)
        all_prof_items.extend(p_items)
        
    # Map professional code equivalent to each prof item
    for item in all_prof_items:
        item['cod_osde_equivalente'] = nomenclator.prof_to_osde_code(item['cod_prest'])
        item['imp_liquidado_osde'] = 0.0
        item['diferencia_osde'] = 0.0
        item['estado_conciliacion'] = 'NO_EN_OSDE'
        item['motivo_conciliacion'] = ''

    # Build mapping for lookup
    # Primary lookup key: (afiliado, cod_osde_equivalente)
    # Secondary lookup key: (afiliado)
    prof_items_by_key = {}
    for idx, item in enumerate(all_prof_items):
        key = (item['afiliado'], item['cod_osde_equivalente'])
        prof_items_by_key.setdefault(key, []).append(idx)
        
    # Also track affiliates by professional
    afi_to_prof_name = {}
    for item in all_prof_items:
        afi_to_prof_name[item['afiliado']] = item['profesional']
        
    matched_prof_indices = set()
    logs_ajustes = []
    
    # Process each OSDE item
    for o_item in osde_items:
        o_afi = o_item['afiliado']
        o_cod = o_item['codigo']
        o_est = o_item['estado']
        o_liq = o_item['imp_liquidado']
        o_fac = o_item['imp_facturado']
        o_mot = o_item['motivo_rechazo']
        
        # Determine professional owner
        assigned_prof = afi_to_prof_name.get(o_afi, 'NO ASIGNADO')
        o_item['profesional_asignado'] = assigned_prof
        
        # Try exact match (afiliado + codigo)
        match_idx = None
        if o_afi:
            key = (o_afi, o_cod)
            candidates = prof_items_by_key.get(key, [])
            for c_idx in candidates:
                if c_idx not in matched_prof_indices:
                    match_idx = c_idx
                    break
                    
            # Fallback 1: same affiliate, any unconsumed item
            if match_idx is None:
                for idx, p_it in enumerate(all_prof_items):
                    if idx not in matched_prof_indices and p_it['afiliado'] == o_afi:
                        match_idx = idx
                        break
                        
        # Fallback 2: match by patient surname/name (useful for rows where affiliate was missing in PDF)
        if match_idx is None and o_item['paciente']:
            o_pac_words = set(o_item['paciente'].upper().split())
            for idx, p_it in enumerate(all_prof_items):
                if idx not in matched_prof_indices and p_it['paciente']:
                    p_pac_words = set(p_it['paciente'].upper().split())
                    # Check significant intersection
                    common_w = o_pac_words.intersection(p_pac_words)
                    # Exclude common short words
                    sig_common = [w for w in common_w if len(w) > 2]
                    if len(sig_common) >= 2 or (len(sig_common) == 1 and any(len(w) >= 6 for w in sig_common)):
                        if p_it['cod_osde_equivalente'] == o_cod or not o_afi or not p_it['afiliado']:
                            match_idx = idx
                            if not p_it['afiliado']:
                                p_it['afiliado'] = o_afi
                            break
                    
        if match_idx is not None:
            matched_prof_indices.add(match_idx)
            p_item = all_prof_items[match_idx]
            p_item['imp_liquidado_osde'] = o_liq
            p_item['diferencia_osde'] = round(o_liq - p_item['imp_final'], 2)
            
            if o_est == 'RECHAZADO':
                p_item['estado_conciliacion'] = 'RECHAZADO'
                p_item['motivo_conciliacion'] = o_mot or 'Rechazado por OSDE'
                logs_ajustes.append({
                    'profesional': p_item['profesional'],
                    'afiliado': o_afi,
                    'paciente': p_item['paciente'] or o_item['paciente'],
                    'prestacion': f"{p_item['cod_prest']} ({p_item['descripcion']})",
                    'tipo_ajuste': 'RECHAZO OSDE',
                    'monto_declarado': p_item['imp_final'],
                    'monto_osde': o_liq,
                    'diferencia_ajuste': -p_item['imp_final'],
                    'motivo': o_mot or 'Rechazado por OSDE (se descuenta total liquidado por prof)'
                })
            else:
                dif = round(o_liq - p_item['imp_final'], 2)
                if abs(dif) > 0.01:
                    p_item['estado_conciliacion'] = 'DIFERENCIA'
                    tipo = 'DIFERENCIA MENOR' if dif < 0 else 'DIFERENCIA MAYOR'
                    logs_ajustes.append({
                        'profesional': p_item['profesional'],
                        'afiliado': o_afi,
                        'paciente': p_item['paciente'] or o_item['paciente'],
                        'prestacion': f"{p_item['cod_prest']} ({p_item['descripcion']})",
                        'tipo_ajuste': tipo,
                        'monto_declarado': p_item['imp_final'],
                        'monto_osde': o_liq,
                        'diferencia_ajuste': dif,
                        'motivo': f"OSDE liquidó {'menor' if dif < 0 else 'mayor'} importe que lo presentado"
                    })
                else:
                    p_item['estado_conciliacion'] = 'CONCILIADO_OK'
        else:
            # OSDE item had no match in professional files
            if o_est == 'RECHAZADO':
                logs_ajustes.append({
                    'profesional': assigned_prof,
                    'afiliado': o_afi,
                    'paciente': o_item['paciente'],
                    'prestacion': f"OSDE {o_cod} ({o_item['descripcion']})",
                    'tipo_ajuste': 'RECHAZO NO PRESENTADO',
                    'monto_declarado': 0.0,
                    'monto_osde': 0.0,
                    'diferencia_ajuste': 0.0,
                    'motivo': f"Rechazado en OSDE ({o_mot}) pero no figura en planillas profesionales de este mes"
                })

    # Any professional item not matched in OSDE
    for idx, p_item in enumerate(all_prof_items):
        if idx not in matched_prof_indices:
            p_item['estado_conciliacion'] = 'NO_PROCESADO_OSDE'
            logs_ajustes.append({
                'profesional': p_item['profesional'],
                'afiliado': p_item['afiliado'],
                'paciente': p_item['paciente'],
                'prestacion': f"{p_item['cod_prest']} ({p_item['descripcion']})",
                'tipo_ajuste': 'NO PROCESADO OSDE',
                'monto_declarado': p_item['imp_final'],
                'monto_osde': 0.0,
                'diferencia_ajuste': -p_item['imp_final'],
                'motivo': 'Presentado por profesional pero ausente en liquidación recibida de OSDE'
            })

    # Summarize per professional
    prof_summaries = {}
    for p_meta in all_prof_meta:
        p_name = p_meta['profesional']
        prof_summaries[p_name] = {
            'profesional': p_name,
            'archivo': p_meta['archivo'],
            'total_declarado': p_meta['calculated_total'],
            'total_liquidado_osde': 0.0,
            'total_descuentos_rechazos': 0.0,
            'total_diferencias': 0.0,
            'total_neto_liquidable': 0.0,
            'total_prestaciones': 0,
            'prestaciones_rechazadas': 0
        }
        
    for p_item in all_prof_items:
        p_name = p_item['profesional']
        s = prof_summaries.get(p_name)
        if not s: continue
        s['total_prestaciones'] += 1
        s['total_liquidado_osde'] += p_item['imp_liquidado_osde']
        
        if p_item['estado_conciliacion'] == 'RECHAZADO':
            s['prestaciones_rechazadas'] += 1
            s['total_descuentos_rechazos'] += p_item['imp_final']
        elif p_item['estado_conciliacion'] in ('DIFERENCIA', 'CONCILIADO_OK'):
            dif = p_item['imp_liquidado_osde'] - p_item['imp_final']
            s['total_diferencias'] += dif
        elif p_item['estado_conciliacion'] == 'NO_PROCESADO_OSDE':
            s['prestaciones_rechazadas'] += 1
            s['total_descuentos_rechazos'] += p_item['imp_final']
            
    for p_name, s in prof_summaries.items():
        s['total_descuentos_rechazos'] = round(s['total_descuentos_rechazos'], 2)
        s['total_diferencias'] = round(s['total_diferencias'], 2)
        s['total_liquidado_osde'] = round(s['total_liquidado_osde'], 2)
        # Neto liquidable = Declarado - Rechazos + Diferencias
        s['total_neto_liquidable'] = round(s['total_declarado'] - s['total_descuentos_rechazos'] + s['total_diferencias'], 2)

    # General totals
    tot_prof_declarado = sum(s['total_declarado'] for s in prof_summaries.values())
    tot_osde_liquidado = osde_meta['total_liquidado']
    tot_rechazos_cant = sum(1 for o in osde_items if o['estado'] == 'RECHAZADO')
    tot_rechazos_monto = sum(o['imp_facturado'] for o in osde_items if o['estado'] == 'RECHAZADO')
    dif_neta = round(tot_osde_liquidado - tot_prof_declarado, 2)
    
    # Save into SQLite Database
    conn = database.get_db_connection()
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO periodos (
            nombre, fecha_proceso, osde_tramite, osde_efector, osde_fecha_emision,
            total_osde_liquidado, total_prof_declarado, total_rechazados_cant,
            total_rechazados_monto, diferencia_neta
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        period_name, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        osde_meta.get('tramite', ''), osde_meta.get('efector', ''), osde_meta.get('fecha_emision', ''),
        tot_osde_liquidado, tot_prof_declarado, tot_rechazos_cant,
        tot_rechazos_monto, dif_neta
    ))
    periodo_id = c.lastrowid
    
    # Insert OSDE items
    for o in osde_items:
        c.execute('''
            INSERT INTO osde_items (
                periodo_id, page, id_osde, afiliado, paciente, fecha, codigo, dte,
                descripcion, estado, imp_facturado, imp_liquidado, diferencia,
                motivo_rechazo, profesional_asignado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            periodo_id, o['page'], o['id_osde'], o['afiliado'], o['paciente'], o['fecha'],
            o['codigo'], o['dte'], o['descripcion'], o['estado'], o['imp_facturado'],
            o['imp_liquidado'], o['diferencia'], o['motivo_rechazo'], o['profesional_asignado']
        ))
        
    # Insert Prof items
    for p in all_prof_items:
        c.execute('''
            INSERT INTO prof_items (
                periodo_id, profesional, archivo, fecha, paciente, plan, afiliado,
                cod_prest, cod_osde_equivalente, descripcion, imp_neto, imp_final,
                imp_liquidado_osde, diferencia_osde, estado_conciliacion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            periodo_id, p['profesional'], p['archivo'], p['fecha'], p['paciente'], p['plan'],
            p['afiliado'], p['cod_prest'], p['cod_osde_equivalente'], p['descripcion'],
            p['imp_neto'], p['imp_final'], p['imp_liquidado_osde'], p['diferencia_osde'],
            p['estado_conciliacion']
        ))
        
    # Insert summaries
    for s in prof_summaries.values():
        c.execute('''
            INSERT INTO liquidacion_resumen_profesional (
                periodo_id, profesional, archivo, total_declarado, total_liquidado_osde,
                total_descuentos_rechazos, total_diferencias, total_neto_liquidable,
                total_prestaciones, prestaciones_rechazadas
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            periodo_id, s['profesional'], s['archivo'], s['total_declarado'],
            s['total_liquidado_osde'], s['total_descuentos_rechazos'], s['total_diferencias'],
            s['total_neto_liquidable'], s['total_prestaciones'], s['prestaciones_rechazadas']
        ))
        
    # Insert logs
    for log in logs_ajustes:
        c.execute('''
            INSERT INTO logs_ajustes (
                periodo_id, profesional, afiliado, paciente, prestacion,
                tipo_ajuste, monto_declarado, monto_osde, diferencia_ajuste, motivo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            periodo_id, log['profesional'], log['afiliado'], log['paciente'], log['prestacion'],
            log['tipo_ajuste'], log['monto_declarado'], log['monto_osde'],
            log['diferencia_ajuste'], log['motivo']
        ))
        
    conn.commit()
    conn.close()
    
    # Store original PDF files in Supabase for 90 days
    try:
        if os.path.exists(osde_path):
            with open(osde_path, 'rb') as f:
                database.store_periodo_file(periodo_id, 'OSDE', os.path.basename(osde_path), f.read())
        for p_path in prof_paths:
            if os.path.exists(p_path):
                with open(p_path, 'rb') as f:
                    database.store_periodo_file(periodo_id, 'PROFESIONAL', os.path.basename(p_path), f.read())
    except Exception as e_store:
        print("Aviso: no se pudo persistir el binario en Supabase:", e_store)
        
    return {
        'periodo_id': periodo_id,
        'period_name': period_name,
        'osde_meta': osde_meta,
        'prof_summaries': list(prof_summaries.values()),
        'rechazos_osde': [o for o in osde_items if o['estado'] == 'RECHAZADO'],
        'logs_ajustes': logs_ajustes,
        'totales': {
            'osde_liquidado': tot_osde_liquidado,
            'prof_declarado': tot_prof_declarado,
            'diferencia_neta': dif_neta,
            'rechazos_cant': tot_rechazos_cant,
            'rechazos_monto': tot_rechazos_monto
        }
    }
