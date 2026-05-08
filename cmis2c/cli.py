"""CLI Entry Point."""

import click
import os
from .parser import extract_cmis_data
from .generator import generate_c_header

@click.group()
def cli():
    """CMIS2C - Generate C header files from CMIS PDF."""
    pass

@cli.command()
@click.argument('pdf_path')
@click.option('-o', '--output', default='cmis_registers.h', help='Output C header file path')
def generate(pdf_path, output):
    """Parse CMIS PDF and generate C header."""
    if not os.path.exists(pdf_path):
        click.echo(f"Error: File '{pdf_path}' not found.")
        return

    click.echo(f"Parsing {pdf_path}...")
    
    # 1. Parse
    try:
        registers = extract_cmis_data(pdf_path)
        click.echo(f"Found {len(registers)} register definitions.")
        
        if not registers:
            click.echo("No register tables found. Check if the PDF structure matches CMIS format.")
            return

        # 2. Generate
        output_dir = os.path.dirname(output)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        result = generate_c_header(registers, output)
        
        if result:
            click.echo(f"Success! C header generated at: {result}")
        else:
            click.echo("Failed to generate file.")
    except Exception as e:
        click.echo(f"Error during processing: {e}", err=True)

def main():
    cli()
