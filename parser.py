import fitz
import re
import os

def parse_osde_pdf(pdf_path: str):
    doc = fitz.open(pdf_path)
    items = []
    
    # Extract metadata from header
    tramite = ""
    efector = ""
    fecha_emision = ""
    
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        words = page.get_text("words")
        text_page = page.get_text("text")
        
        if page_idx == 0:
            m_tram = re.search(r'Tr[áa]mite:\s*(\d+)', text_page)
            if m_tram: tramite = m_tram.group(1)
            m_efec = re.search(r'Efector:[^\n]*\n(?:Cuit:[^\n]*\n)?([0-9]+\s*\(DIRECTO\)\s*-\s*[^\n]+)', text_page)
            if m_efec:
                efector = m_efec.group(1).strip()
            else:
                m_efec_alt = re.search(r'([0-9]+\s*-\s*VALENTE[^\n]+)', text_page)
                if m_efec_alt: efector = m_efec_alt.group(1).strip()
            m_fec = re.search(r'Fecha de Emisi[óo]n:\s*(\d{2}/\d{2}/\d{4})', text_page)
            if m_fec: fecha_emision = m_fec.group(1)

        # OSDE item anchors: 10-digit ID starting with 15 in column x < 50
        anchors = [w for w in words if w[0] < 50 and re.match(r'^15\d{8}$', w[4])]
        anchors = sorted(anchors, key=lambda w: w[1])
        
        for idx, anc in enumerate(anchors):
            y_start = anc[1] - 4
            y_end = anchors[idx+1][1] - 4 if idx + 1 < len(anchors) else 550.0
            
            row_words = [w for w in words if y_start <= w[1] < y_end]
            id_osde = anc[4]
            
            afi_w = [w for w in row_words if 90 <= w[0] <= 140 and re.match(r'^\d{11}$', w[4])]
            afiliado = afi_w[0][4] if afi_w else ''
            
            fecha_w = [w for w in row_words if 190 <= w[0] <= 230 and re.match(r'^\d{2}/\d{2}/\d{2}$', w[4])]
            fecha = fecha_w[0][4] if fecha_w else ''
            
            cod_w = [w for w in row_words if 235 <= w[0] <= 280 and re.match(r'^\d{7}$', w[4])]
            codigo = cod_w[0][4] if cod_w else ''
            
            dte_w = [w for w in row_words if 275 <= w[0] <= 320 and w[1] <= y_start + 8 and re.match(r'^\d{1,2}$', w[4])]
            dte = dte_w[0][4] if dte_w else ''
            
            estado_w = [w for w in row_words if 390 <= w[0] <= 460 and w[4] in ('APROBADO', 'RECHAZADO')]
            estado = estado_w[0][4] if estado_w else 'APROBADO'
            
            amt_words = sorted([w for w in row_words if w[1] <= y_start + 12 and re.match(r'^\d{1,3}(?:,\d{3})*\.\d{2}$', w[4])], key=lambda w: w[0])
            imp_facturado = float(amt_words[0][4].replace(',', '')) if len(amt_words) > 0 else 0.0
            imp_liquidado = float(amt_words[1][4].replace(',', '')) if len(amt_words) > 1 else 0.0
            diferencia = float(amt_words[2][4].replace(',', '')) if len(amt_words) > 2 else 0.0
            
            pac_words = sorted([w for w in row_words if y_start + 7 <= w[1] <= y_start + 22 and 90 <= w[0] < 235], key=lambda w: w[0])
            paciente = ' '.join([w[4] for w in pac_words])
            
            desc_words = sorted([w for w in row_words if y_start + 7 <= w[1] <= y_start + 22 and w[0] >= 235], key=lambda w: w[0])
            descripcion = ' '.join([w[4] for w in desc_words])
            
            motivo_words = sorted([w for w in row_words if w[1] > y_start + 22 and w[0] >= 90], key=lambda w: (round(w[1]/4), w[0]))
            motivo = ' '.join([w[4] for w in motivo_words])
            
            items.append({
                'page': page_idx + 1,
                'id_osde': id_osde,
                'afiliado': afiliado,
                'paciente': paciente,
                'fecha': fecha,
                'codigo': codigo,
                'dte': dte,
                'descripcion': descripcion,
                'estado': estado,
                'imp_facturado': imp_facturado,
                'imp_liquidado': imp_liquidado,
                'diferencia': diferencia,
                'motivo_rechazo': motivo
            })
            
    metadata = {
        'tramite': tramite,
        'efector': efector,
        'fecha_emision': fecha_emision,
        'total_items': len(items),
        'total_liquidado': sum(it['imp_liquidado'] for it in items),
        'total_facturado': sum(it['imp_facturado'] for it in items),
        'total_rechazados': sum(1 for it in items if it['estado'] == 'RECHAZADO')
    }
    return metadata, items

def parse_professional_pdf(pdf_path: str):
    doc = fitz.open(pdf_path)
    full_text = '\n'.join([p.get_text('text') for p in doc])
    
    m_prof = re.search(r'Profesional:\s*([^\n]+)', full_text)
    profesional = m_prof.group(1).strip() if m_prof else os.path.splitext(os.path.basename(pdf_path))[0]
    
    m_desde = re.search(r'Fecha desde:\s*([^\n]+)', full_text)
    m_hasta = re.search(r'Fecha hasta:\s*([^\n]+)', full_text)
    fecha_desde = m_desde.group(1).strip() if m_desde else ''
    fecha_hasta = m_hasta.group(1).strip() if m_hasta else ''
    
    t0 = doc[0].get_text('text')
    m_tot = re.search(r'Total:\s*\$\s*([\d\.,]+)', t0)
    header_total = float(m_tot.group(1).replace('.', '').replace(',', '.')) if m_tot else 0.0
    
    lines = [l.strip() for p in doc for l in p.get_text('text').split('\n') if l.strip()]
    date_indices = [i for i, l in enumerate(lines) if re.match(r'^\d{2}/\d{2}/\d{4}$', l)]
    
    records = []
    for idx, d_i in enumerate(date_indices):
        next_d_i = date_indices[idx + 1] if idx + 1 < len(date_indices) else len(lines)
        chunk = lines[d_i:next_d_i]
        fecha = chunk[0]
        
        afi_match = ''
        afi_idx = -1
        for k, cl in enumerate(chunk):
            if re.match(r'^\d{11}$', cl):
                afi_match = cl
                afi_idx = k
                break
                
        if afi_match:
            plan = chunk[afi_idx - 1] if afi_idx > 1 else ''
            paciente = ' '.join(chunk[1:afi_idx - 1]) if afi_idx > 2 else chunk[1]
            cod_prest = chunk[afi_idx + 1] if afi_idx + 1 < len(chunk) else ''
        else:
            # Row without affiliate number: e.g. ['06/08/2026', 'Lorena Saddemi', '210', '01.01', ...]
            plan = chunk[2] if len(chunk) > 2 else ''
            paciente = chunk[1] if len(chunk) > 1 else ''
            cod_prest = chunk[3] if len(chunk) > 3 else ''
            afi_match = ''
            
        # Dollar amounts
        dlrs = [float(x.replace('$ ', '').replace('.', '').replace(',', '.')) for x in chunk if x.startswith('$ ')]
        imp_final = dlrs[1] if len(dlrs) >= 2 else (dlrs[0] if dlrs else 0.0)
        imp_neto = dlrs[0] if dlrs else imp_final
            
        # Description
        desc_parts = []
        start_desc = afi_idx + 2 if afi_idx != -1 else 4
        for cl in chunk[start_desc:]:
            if cl.startswith('$ ') or cl in ('-', 'NG') or re.match(r'^\d+$', cl):
                continue
            desc_parts.append(cl)
        desc = ' '.join(desc_parts)
        
        records.append({
            'profesional': profesional,
            'archivo': os.path.basename(pdf_path),
            'fecha': fecha,
            'paciente': paciente,
            'plan': plan,
            'afiliado': afi_match,
            'cod_prest': cod_prest,
            'descripcion': desc,
            'imp_neto': imp_neto,
            'imp_final': imp_final
        })
            
    metadata = {
        'profesional': profesional,
        'archivo': os.path.basename(pdf_path),
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'header_total': header_total,
        'total_items': len(records),
        'calculated_total': sum(r['imp_final'] for r in records)
    }
    return metadata, records

def parse_particulares_pdf(pdf_path: str):
    """
    Parsea archivos PDF de 'Liquidación a profesional - Pagos de pacientes'
    Nombrados comúnmente como 'Particulares(Nombre del profesional).pdf' o 'Particulares Ariel.pdf'.
    """
    doc = fitz.open(pdf_path)
    full_text = '\n'.join([p.get_text('text') for p in doc])
    
    # 1. Metadatos del encabezado
    m_prof = re.search(r'Profesional:\s*([^\n]+)', full_text)
    profesional = m_prof.group(1).strip() if m_prof else ''
    
    m_os = re.search(r'Obra social:\s*([^\n]+)', full_text)
    obra_social = m_os.group(1).strip() if m_os else 'Todas las obras sociales'
    
    m_desde = re.search(r'Fecha desde:\s*([^\n\-]+)', full_text)
    m_hasta = re.search(r'Fecha hasta:\s*([^\n]+)', full_text)
    fecha_desde = m_desde.group(1).strip() if m_desde else ''
    fecha_hasta = m_hasta.group(1).strip() if m_hasta else ''
    
    m_tot = re.search(r'Total a pagar:\s*\$\s*([\d\.,]+)', full_text)
    header_total = float(m_tot.group(1).replace('.', '').replace(',', '.')) if m_tot else 0.0
    
    m_pagos = re.search(r'Pagos a liquidar:\s*(\d+)', full_text)
    header_pagos_cant = int(m_pagos.group(1)) if m_pagos else 0
    
    records = []
    
    # 2. Extracción de filas por página
    for page_idx, page in enumerate(doc):
        words = page.get_text("words")
        if not words:
            continue
            
        # Agrupar palabras en filas visuales según su coordenada vertical Y
        words_sorted = sorted(words, key=lambda w: (w[1], w[0]))
        rows = []
        curr_row = []
        curr_y = None
        
        for w in words_sorted:
            if curr_y is None or abs(w[1] - curr_y) <= 4:
                curr_row.append(w)
                curr_y = w[1] if curr_y is None else (curr_y + w[1]) / 2
            else:
                rows.append(sorted(curr_row, key=lambda x: x[0]))
                curr_row = [w]
                curr_y = w[1]
        if curr_row:
            rows.append(sorted(curr_row, key=lambda x: x[0]))
            
        for row in rows:
            line_str = ' '.join(w[4] for w in row).strip()
            
            # Cada fila de atención particular debe iniciar con una fecha válida DD/MM/YYYY
            m_date = re.match(r'^(\d{2}/\d{2}/\d{4})\b', line_str)
            if not m_date:
                continue
                
            fecha = m_date.group(1)
            
            # Montos en pesos ($)
            amounts = [m.group(1) for m in re.finditer(r'\$\s*([\d\.,]+)', line_str)]
            imp_a_pagar = float(amounts[0].replace('.', '').replace(',', '.')) if amounts else 0.0
            iva = float(amounts[1].replace('.', '').replace(',', '.')) if len(amounts) > 1 else 0.0
            
            # Estado de Anulación (No / Si)
            anul_match = re.search(r'\b(No|Si|S[íi])\s+\$', line_str, re.IGNORECASE)
            anulado = anul_match.group(1).lower() in ('si', 'sí') if anul_match else False
            
            # Descartar registros anulados
            if anulado:
                continue
                
            # Comprobante
            comp_match = re.search(r'\b(Factura|Recibo|Otro|Nota de Cr[ée]dito|Ticket)\b', line_str, re.IGNORECASE)
            comp_str = comp_match.group(1) if comp_match else ''
            
            # Forma de pago
            forma_match = re.search(r'\b(Transferencia|Efectivo|Tarjeta|D[ée]bito|Cr[ée]dito|Mercado\s*Pago|MP|Cheque)\b', line_str, re.IGNORECASE)
            forma_str = forma_match.group(1) if forma_match else ''
            
            # Paciente: texto entre Fecha y Comprobante
            paciente = ''
            if comp_match:
                comp_start = line_str.find(comp_match.group(0))
                paciente = line_str[len(fecha):comp_start].strip()
            else:
                parts = line_str[len(fecha):].strip().split()
                paciente = ' '.join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else '')
                
            # Concepto / Tratamiento: texto entre Forma de pago y Anulación/Monto
            concepto = ''
            if forma_match:
                forma_end = line_str.find(forma_match.group(0)) + len(forma_match.group(0))
                if anul_match:
                    concepto = line_str[forma_end:anul_match.start(0)].strip()
                elif amounts:
                    first_dlr = line_str.find('$')
                    concepto = line_str[forma_end:first_dlr].strip()
                    
            concepto = re.sub(r'^(?:[A-Z]\s+|-\s+)+', '', concepto).strip()
            if not concepto:
                concepto = 'PARTICULAR'
                
            # Comprobante completo (ej. Factura B, Recibo A, Otro B)
            comprobante_full = comp_str
            if comp_match and forma_match:
                c_start = line_str.find(comp_match.group(0))
                f_start = line_str.find(forma_match.group(0))
                comp_slice = line_str[c_start:f_start].strip()
                if comp_slice:
                    comprobante_full = comp_slice
                    
            records.append({
                'fecha': fecha,
                'paciente': paciente,
                'comprobante': comprobante_full,
                'forma_pago': forma_str,
                'prestacion': concepto,
                'importe': imp_a_pagar,
                'iva': iva,
                'anulado': anulado,
                'archivo': os.path.basename(pdf_path)
            })

    metadata = {
        'profesional': profesional,
        'obra_social': obra_social,
        'archivo': os.path.basename(pdf_path),
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'header_total': header_total,
        'header_pagos_cant': header_pagos_cant,
        'total_items': len(records),
        'calculated_total': sum(r['importe'] for r in records)
    }
    return metadata, records

