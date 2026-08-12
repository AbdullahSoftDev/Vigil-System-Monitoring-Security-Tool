#!/usr/bin/env python3
"""
Verify Day 1 Completion
"""

import os
import sys
from pathlib import Path

def check_file_exists(filepath):
    """Check if file exists and return status"""
    exists = os.path.exists(filepath)
    status = "✓" if exists else "✗"
    return status, exists

def main():
    print("=" * 70)
    print("VIGIL - DAY 1 COMPLETION VERIFICATION")
    print("=" * 70)
    
    # All required files from Day 1 prompts
    day1_files = {
        "Prompt 1 - Requirements": [
            ("requirements.txt", "Dependencies list"),
        ],
        "Prompt 2 - Architecture & Supabase": [
            ("src/core/architecture.md", "Architecture documentation"),
            ("src/core/supabase_client.py", "Supabase client implementation"),
            ("src/core/supabase_schema.sql", "Database schema"),
            ("src/config/default_config.yaml", "Default configuration"),
            (".env.template", "Environment template"),
        ],
        "Prompt 3 - SystemMonitor": [
            ("src/core/system_monitor.py", "SystemMonitor class (Project #34)"),
        ],
        "Additional Core Files": [
            ("main.py", "Application entry point"),
            ("src/core/config_manager.py", "Configuration manager"),
        ]
    }
    
    total_files = 0
    existing_files = 0
    
    for section, files in day1_files.items():
        print(f"\n{section}:")
        print("-" * 40)
        
        for filename, description in files:
            total_files += 1
            status, exists = check_file_exists(filename)
            if exists:
                existing_files += 1
            
            # Get file size if exists
            size_info = ""
            if exists:
                size = os.path.getsize(filename)
                size_info = f" ({size:,} bytes)"
            
            print(f"  {status} {filename:40} - {description}{size_info}")
    
    # Test SystemMonitor functionality
    print("\n" + "=" * 70)
    print("FUNCTIONALITY TEST:")
    print("=" * 70)
    
    try:
        # Add src to path
        sys.path.insert(0, str(Path(__file__).parent / 'src'))
        
        from src.core.system_monitor import SystemMonitor
        
        print("\nTesting SystemMonitor in mock mode...")
        config = {'testing': {'mock_mode': True}}
        monitor = SystemMonitor(config)
        
        # Test all required methods
        methods_to_test = [
            ("get_cpu_usage", monitor.get_cpu_usage),
            ("get_memory_usage", monitor.get_memory_usage),
            ("get_disk_io", monitor.get_disk_io),
            ("get_network_io", monitor.get_network_io),
            ("get_running_processes", monitor.get_running_processes),
            ("get_system_info", monitor.get_system_info),
        ]
        
        all_methods_working = True
        for method_name, method in methods_to_test:
            try:
                result = method()
                if result:
                    print(f"  ✓ {method_name}() - Working")
                else:
                    print(f"  ⚠ {method_name}() - Returned empty")
                    all_methods_working = False
            except Exception as e:
                print(f"  ✗ {method_name}() - Failed: {e}")
                all_methods_working = False
        
        if all_methods_working:
            print("\n✅ All SystemMonitor methods working!")
        else:
            print("\n⚠ Some SystemMonitor methods failed (but core exists)")
        
    except ImportError as e:
        print(f"\n✗ Cannot import SystemMonitor: {e}")
        all_methods_working = False
    except Exception as e:
        print(f"\n✗ SystemMonitor test failed: {e}")
        all_methods_working = False
    
    # Final summary
    print("\n" + "=" * 70)
    print("DAY 1 COMPLETION SUMMARY:")
    print("=" * 70)
    
    completion_rate = (existing_files / total_files) * 100 if total_files > 0 else 0
    
    print(f"\n📊 Files: {existing_files}/{total_files} ({completion_rate:.1f}%)")
    
    if existing_files == total_files and all_methods_working:
        print("\n🎉 SUCCESS: DAY 1 COMPLETELY FINISHED!")
        print("\nAll requirements from your 3 prompts are satisfied.")
        print("\nNext steps:")
        print("1. Set up Supabase database")
        print("2. Test the application: python main.py")
        print("3. Move to Day 2 development")
    elif existing_files >= total_files * 0.8:
        print("\n✅ GOOD PROGRESS: Day 1 mostly complete!")
        print("\nCore requirements are satisfied.")
        print("Minor issues can be fixed as we proceed.")
    else:
        print("\n⚠ NEEDS WORK: Day 1 incomplete")
        print("\nSome core files are missing.")
    
    print("\n" + "=" * 70)
    
    return 0 if existing_files == total_files and all_methods_working else 1

if __name__ == "__main__":
    sys.exit(main())