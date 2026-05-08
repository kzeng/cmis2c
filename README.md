# CMIS2C

CLI tool to extract register tables from CMIS PDF files and generate C header files.

## Setup

```bash
pip install -e .
```

## Usage

```bash
# Generate all headers from CMIS PDF
cmis2c generate input.pdf -o output/

# Produces:
#   output/cmis_low_memory.h   - Low memory map (bytes 0-127)
#   output/cmis_page_00h.h     - Page 00h upper memory (bytes 128-255)
#   output/cmis.h              - Umbrella header including both
```

## Dependencies
- click
- pdfplumber
