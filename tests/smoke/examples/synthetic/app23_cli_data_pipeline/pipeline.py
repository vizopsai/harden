"""
CLI data pipeline tool
Reads CSV files and uses OpenAI for analysis
"""

import click
import openai
import pandas as pd
import os
from pathlib import Path

# Load OpenAI key from environment
openai.api_key = os.getenv("OPENAI_API_KEY")

@click.group()
def cli():
    """Data pipeline CLI tool for CSV analysis with AI"""
    pass

@cli.command()
@click.argument('csv_file', type=click.Path(exists=True))
@click.option('--output', '-o', help='Output file path', default='analysis.txt')
@click.option('--model', default='gpt-3.5-turbo', help='OpenAI model to use')
def analyze(csv_file, output, model):
    """Analyze a CSV file using OpenAI"""
    click.echo(f"Reading {csv_file}...")

    # Read CSV - this works for now but might need chunking for large files
    try:
        df = pd.read_csv(csv_file)
    except Exception as e:
        click.echo(f"Error reading CSV: {e}", err=True)
        return

    click.echo(f"Loaded {len(df)} rows, {len(df.columns)} columns")

    # Generate summary stats
    summary = df.describe().to_string()
    columns_info = f"Columns: {', '.join(df.columns)}"

    # Build prompt for OpenAI
    prompt = f"""Analyze this dataset and provide insights:

{columns_info}

Summary statistics:
{summary}

Sample data (first 5 rows):
{df.head().to_string()}

Please provide:
1. Key insights about the data
2. Potential data quality issues
3. Recommendations for further analysis
"""

    click.echo(f"Sending to OpenAI ({model})...")

    # Call OpenAI - TODO: add retry logic
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a data analyst expert."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000
        )

        analysis = response.choices[0].message.content

        # Write output
        with open(output, 'w') as f:
            f.write("=== Data Analysis Report ===\n\n")
            f.write(f"File: {csv_file}\n")
            f.write(f"Rows: {len(df)}, Columns: {len(df.columns)}\n\n")
            f.write(analysis)

        click.echo(f"Analysis saved to {output}")

    except Exception as e:
        click.echo(f"Error calling OpenAI: {e}", err=True)

@cli.command()
@click.argument('csv_file', type=click.Path(exists=True))
def validate(csv_file):
    """Quick validation of CSV file"""
    click.echo(f"Validating {csv_file}...")

    df = pd.read_csv(csv_file)

    # Basic checks - this works for now
    issues = []

    # Check for missing values
    missing = df.isnull().sum()
    if missing.any():
        issues.append(f"Missing values detected: {missing[missing > 0].to_dict()}")

    # Check for duplicate rows
    duplicates = df.duplicated().sum()
    if duplicates > 0:
        issues.append(f"Found {duplicates} duplicate rows")

    if issues:
        click.echo("Issues found:")
        for issue in issues:
            click.echo(f"  - {issue}")
    else:
        click.echo("No issues found!")

if __name__ == '__main__':
    cli()
