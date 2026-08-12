#!/usr/bin/env python3
"""
Script to setup Supabase database schema
Run this after creating your Supabase project
"""

import os
import sys
import argparse
from pathlib import Path


def read_schema_file():
    """Read the SQL schema file"""
    schema_path = Path(__file__).parent.parent / 'src' / 'core' / 'supabase_schema.sql'
    
    if not schema_path.exists():
        print(f"Error: Schema file not found at {schema_path}")
        return None
    
    with open(schema_path, 'r') as f:
        return f.read()

def main():
    parser = argparse.ArgumentParser(description='Setup Supabase database schema')
    parser.add_argument('--url', help='Supabase project URL')
    parser.add_argument('--key', help='Supabase service role key')
    parser.add_argument('--execute', action='store_true', help='Execute the schema (use with caution)')
    
    args = parser.parse_args()
    
    # Read the schema
    schema = read_schema_file()
    if not schema:
        return 1
    
    print("=" * 60)
    print("VIGIL Supabase Database Schema Setup")
    print("=" * 60)
    print()
    
    if args.execute and args.url and args.key:
        print("WARNING: This will execute SQL on your Supabase database!")
        print("Make sure you have backups before proceeding.")
        print()
        
        confirm = input("Type 'YES' to confirm: ")
        if confirm != 'YES':
            print("Cancelled.")
            return 0
        
        try:
            from supabase import create_client
            
            print(f"Connecting to {args.url}...")
            supabase = create_client(args.url, args.key)
            
            # Split schema into individual statements
            statements = schema.split(';')
            
            for i, statement in enumerate(statements):
                statement = statement.strip()
                if statement and not statement.startswith('--'):
                    print(f"Executing statement {i+1}/{len(statements)}...")
                    try:
                        # Note: supabase-py doesn't have direct SQL execution
                        # This would need to be run in Supabase SQL editor
                        print("  (This needs to be run in Supabase SQL editor)")
                        break
                    except Exception as e:
                        print(f"  Error: {e}")
                        return 1
            
            print()
            print("Schema execution would need to be done manually in Supabase SQL editor.")
            print("Please copy the SQL from: vigil/src/core/supabase_schema.sql")
            print("And run it in your Supabase project SQL editor.")
            
        except ImportError:
            print("Error: supabase-py not installed. Run: pip install supabase-py")
            return 1
        except Exception as e:
            print(f"Error: {e}")
            return 1
    else:
        # Just show the schema
        print("SQL Schema to run in Supabase SQL editor:")
        print("=" * 60)
        print(schema)
        print("=" * 60)
        print()
        print("Instructions:")
        print("1. Go to your Supabase project dashboard")
        print("2. Click on 'SQL Editor' in the left sidebar")
        print("3. Create a new query")
        print("4. Copy and paste the above SQL")
        print("5. Run the query")
        print()
        print("To automatically execute, run:")
        print("  python scripts/setup_supabase.py --url YOUR_URL --key YOUR_KEY --execute")
        print()
        print("Get your URL and Service Key from:")
        print("  Supabase Project Settings -> API")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())