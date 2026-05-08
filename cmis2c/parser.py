"""Enhanced parser to extract registers and their Enum definitions."""

import pdfplumber
import re
import json

def clean_cell(x):
    return str(x).strip().replace('\n', ' ').strip() if x else ""

def parse_bits(bits_str):
    if not bits_str: return (7, 0)
    m = re.match(r'(\d+)-(\d+)', bits_str)
    if m: return (int(m.group(1)), int(m.group(2)))
    try: return (int(bits_str), int(bits_str))
    except: return (7, 0)

def extract_cmis_data(pdf_path):
    registers = []
    enums = {} # Key: Table ID (e.g. "8-7") -> { 'name': str, 'values': { val: desc } }
    current_byte = None
    
    with pdfplumber.open(pdf_path) as pdf:
        # Pass 1: Extract Register Map
        for i in range(141, 166):
            if i >= len(pdf.pages): break
            page = pdf.pages[i]
            tables = page.extract_tables()
            
            for t in tables:
                if not t: continue
                r0 = [clean_cell(x) for x in t[0]]
                
                is_detail = False
                if 'Byte' in r0:
                    if any(k in r0 for k in ['Bit', 'Bits', 'Field Name', 'Name', 'Register Name']):
                        is_detail = True
                elif len(r0) >= 3 and '' in r0[0]:
                    c1 = r0[1]
                    if re.match(r'^\d+-\d+$', c1) or re.match(r'^\d+$', c1):
                        is_detail = True

                if is_detail:
                    start_row = 1
                    if '' in r0[0] and 'Byte' not in r0:
                        start_row = 0
                        # For continuation tables, assume headers map to Bytes, Bits, Name...

                    for row in t[start_row:]:
                        if not row: continue
                        cells = [clean_cell(x) for x in row]
                        
                        entry = {}
                        if 'Byte' in r0:
                            for j, cell in enumerate(cells):
                                if j < len(r0): entry[r0[j]] = cell
                        else:
                            mapping = ['Byte', 'Bits', 'Field Name', 'Field Description', 'Type']
                            for j, cell in enumerate(cells):
                                if j < len(mapping): entry[mapping[j]] = cell

                        if 'Byte' in entry and entry['Byte'] and entry['Byte'] not in ['-', '']:
                            current_byte = entry['Byte']
                        elif current_byte:
                            entry['Byte'] = current_byte
                        
                        name = entry.get('Field Name') or entry.get('Name') or entry.get('Register Name', '')
                        if current_byte and name and name != '-':
                            b_str = str(entry['Byte'])
                            try:
                                if '-' in b_str: val = int(b_str.split('-')[0])
                                else: val = int(re.sub(r'\D', '', b_str))
                                
                                if 0 <= val < 128:
                                    registers.append(entry)
                            except ValueError: pass
                            
    # Pass 2: Extract Enums
    # We look for tables with "Code", "Value", "Bit Pattern" etc.
    # Usually these follow the register table.
    
    # Heuristic: Search the whole register section (pages 141-166) for tables that look like enums
    for i in range(141, 166):
        if i >= len(pdf.pages): break
        page = pdf.pages[i]
        text = page.extract_text() or ""
        tables = page.extract_tables()
        
        for t in tables:
            if not t: continue
            r0 = [clean_cell(x).lower().replace('\n', ' ') for x in t[0]]
            
                # Is this an encoding table?
            # Look for "Code", "Value", "Bit Pattern" etc.
            has_code = any(c in r0 for c in ['code', 'value', 'bit pattern', 'module state'])
            has_desc = 'description' in r0 or 'name' in r0 or 'state' in r0
            
            if has_code and has_desc:
                # Try to find the table ID from text preceding the table or in the header
                # We look for the LAST "Table X-Y" before the table or in the header
                table_id = None
                
                # Heuristic: search the text of the page for "Table X-Y"
                # We take all matches. The table usually corresponds to the LAST match on the page 
                # or the one that is closest to the table context.
                matches = re.findall(r'Table\s(\d+-\d+)', text)
                if matches:
                    # Try to find one that makes sense.
                    # If we are on page 144, matches are ['8-6', '8-7']. Table 8-7 is the encoding table.
                    # So taking the last one might be better for encoding tables.
                    table_id = matches[-1]

                # Identify the column indices
                code_idx = -1
                desc_idx = -1
                name_idx = -1
                
                for idx, c in enumerate(r0):
                    if 'code' in c or 'value' in c or 'bit pattern' in c: code_idx = idx
                    if 'description' in c or 'field description' in c: desc_idx = idx
                    if 'name' in c or 'state' in c and 'description' not in c: name_idx = idx

                if code_idx >= 0:
                    enum_vals = {}
                    for row in t[1:]:
                        row_vals = [clean_cell(x) for x in row]
                        code_raw = row_vals[code_idx] if code_idx < len(row_vals) else ""
                        
                        # Parse code (e.g. "001b" -> 1)
                        if 'b' in code_raw.lower():
                            try:
                                code_int = int(code_raw.replace('b','').replace(' ',''), 2)
                            except: code_int = None
                        elif 'h' in code_raw.lower():
                            try:
                                code_int = int(code_raw.replace('h','').replace(' ',''), 16)
                            except: code_int = None
                        else:
                            try:
                                code_int = int(code_raw)
                            except: code_int = None
                            
                        if code_int is not None:
                            desc = row_vals[desc_idx] if desc_idx >= 0 and desc_idx < len(row_vals) else ""
                            name = row_vals[name_idx] if name_idx >= 0 and name_idx < len(row_vals) else desc
                            if not name: name = f"val_{code_int}"
                            enum_vals[code_int] = {
                                'name': name,
                                'desc': desc
                            }

                    if enum_vals:
                        # Try to link this enum to a field that mentions it
                        if table_id:
                            enums[f"Table {table_id}"] = {
                                'table_id': table_id,
                                'values': enum_vals
                            }
                        else:
                            # If no ID found, we can try to match by context or just store it for manual linking later
                            # For now, store with a generated ID
                            enums[f"Auto_{i}_{id(t)}"] = {
                                'table_id': None,
                                'values': enum_vals
                            }

    # Link enums to registers
    for reg in registers:
        desc = reg.get('Field Description', '') or ""
        # Look for "see Table X-Y"
        m = re.search(r'Table\s(\d+-\d+)', desc)
        if m:
            table_ref = f"Table {m.group(1)}"
            if table_ref in enums:
                reg['enum'] = enums[table_ref]
            else:
                # Try searching all stored enums for a match if not found by ID (sometimes IDs are messy)
                # In this case, ModuleState is the best guess if it has "Module State" as enum key?
                pass

    return registers
