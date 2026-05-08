"""Enhanced parser to extract registers and their Enum definitions."""

import pdfplumber
import re
import json

def clean_cell(x):
    s = str(x).strip().replace('\n', ' ').strip() if x else ""
    # Fix PDF kerning artifacts in numeric fields: "12 8" -> "128", "3- 0" -> "3-0"
    if re.match(r'^[\d\s\-]+$', s):
        s = re.sub(r'\s+', '', s)
    return s

def parse_bits(bits_str):
    if not bits_str: return (7, 0)
    m = re.match(r'(\d+)-(\d+)', bits_str)
    if m: return (int(m.group(1)), int(m.group(2)))
    try: return (int(bits_str), int(bits_str))
    except: return (7, 0)

def _extract_register_tables(pdf, page_range, byte_lo, byte_hi):
    """Extract register entries from table pages within a byte range."""
    registers = []
    enums = {}
    current_byte = None

    for i in page_range:
        if i >= len(pdf.pages): break
        page = pdf.pages[i]
        tables = page.extract_tables()

        for t in tables:
            if not t: continue
            r0 = [clean_cell(x) for x in t[0]]

            is_detail = False
            has_byte_header = 'Byte' in r0 or 'Bytes' in r0
            is_bytes_table = 'Bytes' in r0 and 'Byte' not in r0
            # Detect overview/map tables (Address, Size, Subject Area, Description)
            is_overview = 'Address' in r0 or 'Subject Area' in r0
            if has_byte_header:
                if any(k in r0 for k in ['Bit', 'Bits', 'Field Name', 'Name', 'Register Name', 'Length', 'Subject Area']):
                    is_detail = True
            elif is_overview:
                is_detail = True
            elif len(r0) >= 3 and '' in r0[0]:
                c1 = r0[1]
                if re.match(r'^\d+-\d+$', c1) or re.match(r'^\d+$', c1):
                    is_detail = True

            if is_detail:
                start_row = 1
                if '' in r0[0] and not has_byte_header:
                    start_row = 0

                for row in t[start_row:]:
                    if not row: continue
                    cells = [clean_cell(x) for x in row]

                    entry = {}
                    if has_byte_header:
                        for j, cell in enumerate(cells):
                            if j < len(r0): entry[r0[j]] = cell
                        # Normalize: 'Bytes' header -> 'Byte' key
                        if 'Bytes' in entry and 'Byte' not in entry:
                            entry['Byte'] = entry.pop('Bytes')
                        # Normalize: 'Subject Area' -> 'Register Name' for overview tables
                        if 'Subject Area' in entry and 'Register Name' not in entry:
                            entry['Register Name'] = entry.pop('Subject Area')
                            entry['_overview'] = True
                        # For Bytes-type tables, fix Bits: 'All' or length value -> full byte range
                        if is_bytes_table:
                            bits_val = entry.get('Bits', entry.get('Bit', ''))
                            if not bits_val or bits_val.lower() == 'all' or re.match(r'^\d+$', bits_val):
                                entry['Bits'] = '7-0'
                    elif is_overview:
                        mapping = ['Byte', '_Size', 'Register Name', 'Register Description']
                        for j, cell in enumerate(cells):
                            if j < len(mapping): entry[mapping[j]] = cell
                        entry['Bits'] = '7-0'
                        entry['_overview'] = True
                        # If subject area is blank, derive name from description
                        name_val = entry.get('Register Name', '')
                        if not name_val or name_val == '-':
                            desc = entry.get('Register Description', entry.get('Description', ''))
                            if 'custom' in desc.lower():
                                if 'non-volatile' in desc.lower():
                                    entry['Register Name'] = 'CustomInfoNV'
                                else:
                                    entry['Register Name'] = 'Custom'
                            elif 'reserved' in desc.lower():
                                entry['Register Name'] = '-'
                    else:
                        mapping = ['Byte', 'Bits', 'Field Name', 'Field Description', 'Type']
                        for j, cell in enumerate(cells):
                            if j < len(mapping): entry[mapping[j]] = cell
                    # Ensure Bits is set for overview tables
                    if is_overview and 'Bits' not in entry:
                        entry['Bits'] = '7-0'

                    if 'Byte' in entry and entry['Byte'] and entry['Byte'] not in ['-', '']:
                        current_byte = entry['Byte']
                    elif current_byte:
                        entry['Byte'] = current_byte

                    name = entry.get('Field Name') or entry.get('Name') or entry.get('Register Name', '')
                    if current_byte and name and name != '-':
                        b_str = str(entry['Byte'])
                        try:
                            if '-' in b_str:
                                val = int(b_str.split('-')[0])
                                end_val = int(b_str.split('-')[1])
                            else:
                                val = int(re.sub(r'\D', '', b_str))
                                end_val = val

                            if byte_lo <= val <= byte_hi or byte_lo <= end_val <= byte_hi:
                                registers.append(entry)
                        except ValueError:
                            pass

    # Pass 2: Extract enums from same pages
    for i in page_range:
        if i >= len(pdf.pages): break
        page = pdf.pages[i]
        text = page.extract_text() or ""
        tables = page.extract_tables()

        for t in tables:
            if not t: continue
            r0 = [clean_cell(x).lower().replace('\n', ' ') for x in t[0]]

            has_code = any(c in r0 for c in ['code', 'value', 'bit pattern', 'module state'])
            has_desc = 'description' in r0 or 'name' in r0 or 'state' in r0

            if has_code and has_desc:
                table_id = None
                matches = re.findall(r'Table\s(\d+-\d+)', text)
                if matches:
                    table_id = matches[-1]

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
                        if table_id:
                            enums[f"Table {table_id}"] = {
                                'table_id': table_id,
                                'values': enum_vals
                            }
                        else:
                            enums[f"Auto_{i}_{id(t)}"] = {
                                'table_id': None,
                                'values': enum_vals
                            }

    # Link enums to registers
    for reg in registers:
        desc = reg.get('Field Description', '') or ""
        m = re.search(r'Table\s(\d+-\d+)', desc)
        if m:
            table_ref = f"Table {m.group(1)}"
            if table_ref in enums:
                reg['enum'] = enums[table_ref]

    return registers


def extract_cmis_data(pdf_path):
    """Extract Low Memory registers (bytes 0-127) from CMIS PDF."""
    with pdfplumber.open(pdf_path) as pdf:
        return _extract_register_tables(pdf, range(141, 166), 0, 127)


def extract_page00h_data(pdf_path):
    """Extract Page 00h Upper Memory registers (bytes 128-255) from CMIS PDF."""
    with pdfplumber.open(pdf_path) as pdf:
        return _extract_register_tables(pdf, range(160, 167), 128, 255)


def extract_page01h_data(pdf_path):
    """Extract Page 01h Upper Memory registers (bytes 128-255) from CMIS PDF."""
    with pdfplumber.open(pdf_path) as pdf:
        return _extract_register_tables(pdf, range(167, 184), 128, 255)
