# CMIS2C

CLI tool to extract register tables from CMIS PDF files and generate C header files.

## Setup

```bash
pip install -e .
```

## Usage

```bash
# Generate C header from CMIS PDF
cmis2c generate input.pdf -o cmis_low_memory.h
```

## Dependencies
- click
- pdfplumber
