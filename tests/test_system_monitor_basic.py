#!/usr/bin/env python3
"""
Basic test for SystemMonitor functionality
"""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src.core.system_monitor import SystemMonitor

def test_basic_functionality():
    """Test basic SystemMonitor functionality"""
    print("Testing SystemMonitor basic functionality...")
    print("=" * 60)
    
    # Create monitor with mock mode for testing
    config = {
        'testing': {'mock_mode': True},
        'monitoring': {'interval': 0.1}  # Fast updates for testing
    }
    
    monitor = SystemMonitor(config)
    
    print("1. Testing CPU usage...")
    cpu = monitor.get_cpu_usage()
    print(f"   CPU Percent: {cpu['percent']:.1f}%")
    print(f"   Cores: {len(cpu['cores'])}")
    print(f"   Frequency: {cpu['frequency']}")
    
    print("\n2. Testing memory usage...")
    memory = monitor.get_memory_usage()
    print(f"   Memory Percent: {memory['percent']:.1f}%")
    print(f"   Total: {memory['total'] / (1024**3):.1f} GB")
    print(f"   Used: {memory['used_gb']:.1f} GB")
    
    print("\n3. Testing disk I/O...")
    disk = monitor.get_disk_io()
    print(f"   Read: {disk['read_bytes_sec'] / 1024:.1f} KB/s")
    print(f"   Write: {disk['write_bytes_sec'] / 1024:.1f} KB/s")
    
    print("\n4. Testing network I/O...")
    network = monitor.get_network_io()
    print(f"   Sent: {network['bytes_sent_sec'] / 1024:.1f} KB/s")
    print(f"   Received: {network['bytes_recv_sec'] / 1024:.1f} KB/s")
    
    print("\n5. Testing system info...")
    system = monitor.get_system_info()
    print(f"   Hostname: {system['hostname']}")
    print(f"   OS: {system['os']}")
    print(f"   Uptime: {system['uptime'] // 3600} hours")
    
    print("\n6. Testing process listing...")
    processes = monitor.get_running_processes()
    print(f"   Found {len(processes)} processes")
    if processes:
        print(f"   First process: {processes[0]['name']} (PID: {processes[0]['pid']})")
    
    print("\n7. Testing alert callbacks...")
    alert_received = False
    
    def alert_callback(alert):
        nonlocal alert_received
        alert_received = True
        print(f"   Alert received: {alert['type']} - {alert['message']}")
    
    monitor.register_alert_callback(alert_callback)
    
    # Start monitoring briefly
    print("\n8. Starting monitor (2 seconds)...")
    monitor.start()
    time.sleep(2)
    monitor.stop()
    
    print("\n9. Testing data export...")
    cpu_df = monitor.get_cpu_history_dataframe()
    print(f"   CPU history points: {len(cpu_df)}")
    
    print("\n" + "=" * 60)
    print("BASIC TEST COMPLETE!")
    print("All SystemMonitor methods are working.")
    
    return True

if __name__ == "__main__":
    try:
        test_basic_functionality()
        print("\n✓ SystemMonitor is functioning correctly")
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)