"""Generate C header for CMIS Low Memory with Bit-Fields, Unions, and Enums."""

import re

def sanitize_name(name):
    """Sanitize a field name for C."""
    # Fix PDF extraction artifacts: single letter + space + word -> joined
    name = re.sub(r'\b([A-Z])\s+([a-z])', r'\1\2', name)
    # Remove footnote/note markers: trailing digits/bracketed refs with optional commas
    name = re.sub(r'\s+\[\d+(?:,\s*\d+)*\]$', '', name)
    name = re.sub(r'\s+\d+(?:,\s*\d+)*$', '', name)
    clean = ""
    for c in name:
        if c.isalnum() or c == '_':
            clean += c
        elif c == ' ':
            clean += '_'
        else:
            clean += '_'
    clean = clean.strip('_')
    if not clean:
        return "unnamed"
    if clean.lower() in ['register', 'volatile', 'typedef', 'struct', 'enum']:
        clean += "_reg"
    return clean

def clean_c_string(text):
    """Clean up PDF text for C comments."""
    if not text:
        return ""
    text = " ".join(text.split())
    return text

def format_doxygen(brief, details, access, indent_level=4, width=120):
    """Generate Doxygen-style comment block."""
    lines = []
    has_content = brief or details or access
    
    if not has_content:
        return lines

    indent_str = " " * indent_level
    lines.append(f"{indent_str}/**")
    
    if brief:
        lines.append(f"{indent_str} * @brief {brief}")
    
    if details:
        words = details.split()
        current_line = f"{indent_str} * @details "
        for word in words:
            if len(current_line) + len(word) + 1 > width:
                lines.append(current_line)
                current_line = f"{indent_str} * " + word
            else:
                current_line += word + " "
        if current_line.strip() != f"{indent_str} *":
            lines.append(current_line.rstrip())
            
    if access:
        lines.append(f"{indent_str} * @access {access}")
        
    lines.append(f"{indent_str} */")
    return lines

def parse_bits(bits_str):
    """Parse bits string like '7-4', '3', '5-0' into (msb, lsb)."""
    if not bits_str:
        return (7, 0)
    if bits_str.lower() == 'all':
        return (7, 0)
    if '-' in bits_str:
        try:
            msb, lsb = bits_str.split('-')
            return (int(msb), int(lsb))
        except:
            pass
    try:
        val = int(bits_str)
        return (val, val)
    except:
        pass
    return (7, 0)


def _build_byte_map(registers, byte_start, byte_end):
    """Build byte-to-registers map within the given byte range."""
    byte_map = {}
    for reg in registers:
        byte_str = reg.get('Byte', '')
        name = reg.get('Field Name') or reg.get('Name') or reg.get('Register Name', '')
        if not byte_str or not name or name == '-':
            continue
        try:
            if '-' in str(byte_str):
                parts = str(byte_str).split('-')
                start = int(parts[0])
                width = int(parts[1]) - start + 1
                if byte_start <= start < byte_end:
                    reg['width_bytes'] = width
                    if start not in byte_map:
                        byte_map[start] = []
                    # Dedup: skip if same name already at this start byte
                    existing_names = {r.get('Field Name', '') or r.get('Name', '') or r.get('Register Name', '')
                                      for r in byte_map[start]}
                    if name in existing_names:
                        continue
                    byte_map[start].append(reg)
                    # Sort by width ascending: detail entries (narrower) come first
                    byte_map[start].sort(key=lambda r: r.get('width_bytes', 1))
                    # If both overview and detail entries exist, drop overview entries
                    has_detail = any(not r.get('_overview') for r in byte_map[start])
                    if has_detail:
                        byte_map[start] = [r for r in byte_map[start] if not r.get('_overview')]
            else:
                b = int(byte_str)
                if byte_start <= b < byte_end:
                    if b not in byte_map:
                        byte_map[b] = []
                    reg['width_bytes'] = 1
                    existing_names = {r.get('Field Name', '') or r.get('Name', '') or r.get('Register Name', '')
                                      for r in byte_map[b]}
                    if name in existing_names:
                        continue
                    byte_map[b].append(reg)
                    byte_map[b].sort(key=lambda r: r.get('width_bytes', 1))
                    # If both overview and detail entries exist, drop overview entries
                    has_detail = any(not r.get('_overview') for r in byte_map[b])
                    if has_detail:
                        byte_map[b] = [r for r in byte_map[b] if not r.get('_overview')]
        except (ValueError, TypeError):
            continue
    return byte_map


def _build_struct_lines(registers, byte_start, byte_end, struct_name, header_comment, guard_name):
    """Build the C struct definition lines.

    Returns list of code lines (not joined, not written to file).
    """
    num_bytes = byte_end - byte_start

    lines = [
        f"/* Auto-generated by CMIS2C - {header_comment} */",
        f"#ifndef {guard_name}",
        f"#define {guard_name}",
        "",
        "#include <stdint.h>",
        ""
    ]

    # Collect and emit enums
    field_enums = {}
    for reg in registers:
        if 'enum' in reg:
            name = reg.get('Field Name') or reg.get('Name') or reg.get('Register Name', '')
            clean_name = sanitize_name(name)
            if clean_name not in field_enums:
                field_enums[clean_name] = reg['enum']

    for field_name, enum_data in field_enums.items():
        enum_name = f"Enums_{field_name}"
        lines.append("typedef enum {")
        for code, enum_info in sorted(enum_data['values'].items()):
            enum_name_raw = enum_info['name']
            if not enum_name_raw or enum_name_raw == '-':
                enum_val_name = f"Reserved_{code}"
            else:
                enum_val_name = sanitize_name(enum_name_raw)
            comment = enum_info['name'] if enum_info['name'] != enum_info['desc'] else enum_info['desc']
            lines.append(f"    {enum_name}_{enum_val_name} = {code},  /**< {clean_c_string(comment)} **/")
        lines.append(f"}} {enum_name};")
        lines.append("")

    byte_map = _build_byte_map(registers, byte_start, byte_end)

    lines.append(f"/** @brief {header_comment} (Bytes {byte_start}-{byte_end-1}) */")
    lines.append("typedef struct __attribute__((packed)) {")
    lines.append("")

    reserved_start = -1
    reserved_len = 0
    consumed_bytes = set()

    def flush_reserved():
        nonlocal reserved_start, reserved_len
        if reserved_len > 0:
            if reserved_len == 1:
                lines.append(f"    uint8_t reserved_{reserved_start};  /**< r{reserved_start} Reserved */")
            else:
                lines.append(f"    uint8_t reserved_{reserved_start}[{reserved_len}];  /**< r{reserved_start}.. */")
        reserved_len = 0
        reserved_start = -1

    # Detect array starts
    app_array_start = None
    app9_array_start = None
    cdb_array_start = None
    mlao_array_start = None

    for b in range(byte_start, byte_end):
        if b not in byte_map:
            continue

        regs_at_byte = byte_map[b]

        def _name_has(entries, substr):
            for r in entries:
                n = r.get('Field Name', '') or r.get('Name', '') or r.get('Register Name', '')
                if substr in n:
                    return True
            return False

        first_reg = regs_at_byte[0]
        name0 = first_reg.get('Field Name', '') or first_reg.get('Name', '') or first_reg.get('Register Name', '')

        if app_array_start is None and _name_has(regs_at_byte, 'App1'):
            if (b + 4) in byte_map:
                if _name_has(byte_map[b + 4], 'App2'):
                    app_array_start = b
                    for k in range(32):
                        consumed_bytes.add(b + k)

        if app9_array_start is None and _name_has(regs_at_byte, 'App9'):
            if (b + 4) in byte_map:
                if _name_has(byte_map[b + 4], 'App10'):
                    app9_array_start = b
                    for k in range(28):
                        consumed_bytes.add(b + k)

        if mlao_array_start is None and _name_has(regs_at_byte, 'MediaLaneAssignmentOptionsApp1'):
            if (b + 1) in byte_map:
                if _name_has(byte_map[b + 1], 'MediaLaneAssignmentOptionsApp2'):
                    mlao_array_start = b
                    for k in range(15):
                        consumed_bytes.add(b + k)

        width_bytes = first_reg.get('width_bytes', 1)
        if width_bytes > 1:
            for k in range(1, width_bytes):
                consumed_bytes.add(b + k)

    for b in range(byte_start, byte_end):
        if b in consumed_bytes:
            flush_reserved()
            if b == app_array_start:
                lines.append("    /** @brief Application Descriptors (AppSel 1-8) */")
                lines.append("    struct {")
                for offset in range(4):
                    byte_idx = b + offset
                    if byte_idx in byte_map:
                        regs = byte_map[byte_idx]
                        fields = []
                        for r in regs:
                            name = r.get('Field Name', '') or r.get('Name', '') or r.get('Register Name', '')
                            if name and name != '-':
                                clean = re.sub(r'App\d+', '', name).strip('_')
                                bits = r.get('Bits') or r.get('Bit', '')
                                desc = clean_c_string(r.get('Field Description', r.get('Register Description', r.get('Description', ''))))
                                rtype = clean_c_string(r.get('Type', ''))
                                msb, lsb = parse_bits(bits)
                                fields.append({'name': clean, 'width': msb - lsb + 1, 'lsb': lsb, 'desc': desc, 'type': rtype})

                        fields.sort(key=lambda x: x['lsb'])
                        current_bit = 0
                        for f in fields:
                            gap = f['lsb'] - current_bit
                            if gap > 0:
                                lines.append(f"        uint8_t _pad_{offset}_{current_bit} : {gap};")
                            lines.extend(format_doxygen(f['name'], f['desc'], f['type'], indent_level=8))
                            msb_bit = f['lsb'] + f['width'] - 1
                            if f['width'] == 1:
                                bit_note = f"r{byte_idx}.{f['lsb']}"
                            else:
                                bit_note = f"r{byte_idx}.{msb_bit}-{f['lsb']}"
                            lines.append(f"        uint8_t {f['name']} : {f['width']};  /* {bit_note} */")
                            current_bit = f['lsb'] + f['width']
                        if current_bit < 8:
                            lines.append(f"        uint8_t _pad_{offset}_{current_bit} : {8 - current_bit};")
                    else:
                        lines.append(f"        uint8_t reserved_{offset};")
                lines.append("    } AppDescriptors[8];")

            elif b == app9_array_start:
                lines.append("    /** @brief Application Descriptors (AppSel 9-15) */")
                lines.append("    struct {")
                for offset in range(4):
                    byte_idx = b + offset
                    if byte_idx in byte_map:
                        regs = byte_map[byte_idx]
                        fields = []
                        for r in regs:
                            name = r.get('Field Name', '') or r.get('Name', '') or r.get('Register Name', '')
                            if name and name != '-':
                                clean = re.sub(r'App\d+', '', name).strip('_')
                                bits = r.get('Bits') or r.get('Bit', '')
                                desc = clean_c_string(r.get('Field Description', r.get('Register Description', r.get('Description', ''))))
                                rtype = clean_c_string(r.get('Type', ''))
                                msb, lsb = parse_bits(bits)
                                fields.append({'name': clean, 'width': msb - lsb + 1, 'lsb': lsb, 'desc': desc, 'type': rtype})

                        fields.sort(key=lambda x: x['lsb'])
                        current_bit = 0
                        for f in fields:
                            gap = f['lsb'] - current_bit
                            if gap > 0:
                                lines.append(f"        uint8_t _pad_{offset}_{current_bit} : {gap};")
                            lines.extend(format_doxygen(f['name'], f['desc'], f['type'], indent_level=8))
                            msb_bit = f['lsb'] + f['width'] - 1
                            if f['width'] == 1:
                                bit_note = f"r{byte_idx}.{f['lsb']}"
                            else:
                                bit_note = f"r{byte_idx}.{msb_bit}-{f['lsb']}"
                            lines.append(f"        uint8_t {f['name']} : {f['width']};  /* {bit_note} */")
                            current_bit = f['lsb'] + f['width']
                        if current_bit < 8:
                            lines.append(f"        uint8_t _pad_{offset}_{current_bit} : {8 - current_bit};")
                    else:
                        lines.append(f"        uint8_t reserved_{offset};")
                lines.append("    } AppDescriptors[7];")

            elif b == mlao_array_start:
                lines.append("    /** @brief Media Lane Assignment Options (App 1-15) */")
                lines.append("    uint8_t MediaLaneAssignmentOptions[15];")

            elif b == cdb_array_start:
                lines.append("    /** @brief CDB Status (Instance 1 & 2) */")
                lines.append("    struct {")
                struct_lines = []
                fields = [
                    {'name': 'CdbCommandResult', 'width': 6, 'lsb': 0,
                     'desc': 'The CdbCommandResult field provides more detailed classification for each of the three coarse query results encoded by Bit 7 (CdbIsBusy) and Bit 6 (CdbHasFailed).',
                     'type': 'RO'},
                    {'name': 'CdbHasFailed', 'width': 1, 'lsb': 6,
                     'desc': 'Bool: CdbHasFailed bit indicates if there was a failure, after the module has completed execution of the last CDB command.',
                     'type': 'RO'},
                    {'name': 'CdbIsBusy', 'width': 1, 'lsb': 7,
                     'desc': 'Bool: CdbIsBusy status bit indicates whether the module is still busy, or idle and ready to accept a new CDB command.',
                     'type': 'RO'}
                ]
                fields.sort(key=lambda x: x['lsb'])
                current_bit = 0
                for f in fields:
                    gap = f['lsb'] - current_bit
                    if gap > 0:
                        pad_name = f"_pad_{b}_{current_bit}"
                        struct_lines.append(f"            uint8_t {pad_name} : {gap};")
                    lines.extend(format_doxygen(f['name'], f['desc'], f['type'], indent_level=12))
                    msb_bit = f['lsb'] + f['width'] - 1
                    if f['width'] == 1:
                        bit_note = f"r{b}.{f['lsb']}"
                    else:
                        bit_note = f"r{b}.{msb_bit}-{f['lsb']}"
                    struct_lines.append(f"            uint8_t {f['name']} : {f['width']};  /* {bit_note} */")
                    current_bit = f['lsb'] + f['width']
                if current_bit < 8:
                    pad_name = f"_pad_{b}_{current_bit}"
                    struct_lines.append(f"            uint8_t {pad_name} : {8 - current_bit};")

                lines.append(f"    union {{")
                lines.append(f"        struct {{")
                for line in struct_lines:
                    lines.append(line)
                lines.append(f"        }};")
                lines.append(f"        uint8_t r{b};")
                lines.append(f"    }};")
            else:
                pass
        elif b in byte_map:
            flush_reserved()
            regs = byte_map[b]
            # Filter: keep only entries with the minimum width (drop broader overview entries)
            min_width = min(r.get('width_bytes', 1) for r in regs)
            regs = [r for r in regs if r.get('width_bytes', 1) == min_width]
            # Dedup within same width: prefer non-"Copy" names, then de-duplicate by sanitized name
            if len(regs) > 1:
                non_copy = [r for r in regs if 'Copy' not in (r.get('Field Name', '') or r.get('Name', '') or r.get('Register Name', ''))]
                if non_copy:
                    regs = non_copy
                seen = set()
                unique = []
                for r in regs:
                    n = sanitize_name(r.get('Field Name', '') or r.get('Name', '') or r.get('Register Name', ''))
                    if n not in seen:
                        seen.add(n)
                        unique.append(r)
                regs = unique
            fields = []
            for r in regs:
                name = r.get('Field Name', '') or r.get('Name', '') or r.get('Register Name', '')
                if name and name != '-':
                    clean = sanitize_name(name)
                    bits = r.get('Bits') or r.get('Bit', '')
                    desc = clean_c_string(r.get('Field Description', r.get('Register Description', r.get('Description', ''))))
                    rtype = clean_c_string(r.get('Type', ''))
                    msb, lsb = parse_bits(bits)
                    fields.append({'name': clean, 'width': msb - lsb + 1, 'lsb': lsb, 'desc': desc, 'type': rtype})

            if not fields:
                if reserved_len == 0:
                    reserved_start = b
                reserved_len += 1
            elif len(fields) == 1 and fields[0]['width'] == 8:
                f = fields[0]
                width_bytes = regs[0].get('width_bytes', 1)
                lines.extend(format_doxygen(f['name'], f['desc'], f['type'], indent_level=4))
                if width_bytes == 2:
                    lines.append(f"    uint16_t {f['name']};  /* r{b} */")
                elif width_bytes == 4:
                    lines.append(f"    uint32_t {f['name']};  /* r{b} */")
                elif width_bytes > 1:
                    lines.append(f"    uint8_t {f['name']}[{width_bytes}];  /* r{b} */")
                else:
                    lines.append(f"    uint8_t {f['name']};  /* r{b} */")
            else:
                fields.sort(key=lambda x: x['lsb'])
                struct_lines = []
                current_bit = 0
                for f in fields:
                    gap = f['lsb'] - current_bit
                    if gap > 0:
                        struct_lines.append(f"            uint8_t _pad_{b}_{current_bit} : {gap};")
                    lines.extend(format_doxygen(f['name'], f['desc'], f['type'], indent_level=8))
                    msb_bit = f['lsb'] + f['width'] - 1
                    if f['width'] == 1:
                        bit_note = f"r{b}.{f['lsb']}"
                    else:
                        bit_note = f"r{b}.{msb_bit}-{f['lsb']}"
                    struct_lines.append(f"            uint8_t {f['name']} : {f['width']};  /* {bit_note} */")
                    current_bit = f['lsb'] + f['width']
                if current_bit < 8:
                    struct_lines.append(f"            uint8_t _pad_{b}_{current_bit} : {8 - current_bit};")

                lines.append(f"    union {{")
                lines.append(f"        struct {{")
                for line in struct_lines:
                    lines.append(line)
                lines.append(f"        }};")
                lines.append(f"        uint8_t r{b};")
                lines.append(f"    }};")
        else:
            if reserved_len == 0:
                reserved_start = b
            reserved_len += 1

    flush_reserved()

    lines.append("")
    lines.append(f"}} {struct_name};")
    lines.append("")
    lines.append("#if __STDC_VERSION__ >= 202311L")
    lines.append(f"static_assert(sizeof({struct_name}) == {num_bytes}, \"{struct_name} must be exactly {num_bytes} bytes\");")
    lines.append("#elif __STDC_VERSION__ >= 201112L")
    lines.append(f"_Static_assert(sizeof({struct_name}) == {num_bytes}, \"{struct_name} must be exactly {num_bytes} bytes\");")
    lines.append("#elif defined(__GNUC__) || defined(__clang__)")
    lines.append(f"_Static_assert(sizeof({struct_name}) == {num_bytes}, \"{struct_name} must be exactly {num_bytes} bytes\");")
    lines.append("#else")
    lines.append(f"/* verify manually: sizeof({struct_name}) must be {num_bytes} */")
    lines.append("#endif")
    lines.append("")
    lines.append(f"#endif  // {guard_name}")

    return lines


def _write_header(lines, output_path):
    """Write lines to a header file."""
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return output_path
    except Exception as e:
        print(f"Error writing file: {e}")
        return None


def generate_c_header(registers, output_path):
    """Generate the low-memory (bytes 0-127) C header."""
    lines = _build_struct_lines(
        registers,
        byte_start=0, byte_end=128,
        struct_name="cmis_low_memory_t",
        header_comment="CMIS Low Memory Register Map",
        guard_name="__CMIS_LOW_MEMORY_H"
    )
    return _write_header(lines, output_path)


def generate_page00h_header(registers, output_path):
    """Generate the Page 00h upper-memory (bytes 128-255) C header."""
    lines = _build_struct_lines(
        registers,
        byte_start=128, byte_end=256,
        struct_name="cmis_page_00h_t",
        header_comment="CMIS Page 00h Register Map",
        guard_name="__CMIS_PAGE_00H_H"
    )
    return _write_header(lines, output_path)


def generate_page01h_header(registers, output_path):
    """Generate the Page 01h upper-memory (bytes 128-255) C header."""
    lines = _build_struct_lines(
        registers,
        byte_start=128, byte_end=256,
        struct_name="cmis_page_01h_t",
        header_comment="CMIS Page 01h Register Map",
        guard_name="__CMIS_PAGE_01H_H"
    )
    return _write_header(lines, output_path)
