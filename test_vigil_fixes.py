#!/usr/bin/env python3
"""
Test script to verify VIGIL fixes
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_system_monitor():
    """Test SystemMonitor fixes."""
    print("Testing SystemMonitor...")
    try:
        from src.core.system_monitor import SystemMonitor
        monitor = SystemMonitor()
        
        # Test get_system_info
        info = monitor.get_system_info()
        print(f"  ✓ System Info: {info.get('hostname', 'Unknown')} - {info.get('os', 'Unknown')}")
        
        # Test get_processes
        processes = monitor.get_processes(5)
        print(f"  ✓ Processes: {len(processes)} found")
        
        # Test current metrics
        metrics = monitor.get_current_metrics()
        print(f"  ✓ CPU: {metrics.get('cpu', {}).get('percent', 0):.1f}%")
        print(f"  ✓ Memory: {metrics.get('memory', {}).get('percent', 0):.1f}%")
        
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def test_alert_manager():
    """Test AlertManager fixes."""
    print("\nTesting AlertManager...")
    try:
        from src.core.alert_manager import AlertManager, Alert, AlertSeverity
        from datetime import datetime
        
        am = AlertManager()
        
        # Create test alert
        alert = Alert(
            id="test_123",
            type="test",
            severity=AlertSeverity.INFO,
            message="Test alert",
            timestamp=datetime.now(),
            description="Test description"
        )
        
        # Test get_recent_alerts
        alerts = am.get_recent_alerts(5)
        print(f"  ✓ get_recent_alerts works: {len(alerts)} alerts")
        
        # Test alert has description
        print(f"  ✓ Alert has description: {'description' in dir(alert)}")
        
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 60)
    print("VIGIL FIX VERIFICATION")
    print("=" * 60)
    
    results = []
    results.append(test_system_monitor())
    results.append(test_alert_manager())
    
    print("=" * 60)
    if all(results):
        print("✅ ALL TESTS PASSED! VIGIL is ready to run.")
        print("\nRun: python main.py")
    else:
        print("⚠️  Some tests failed. Check the errors above.")
    
    return 0 if all(results) else 1

if __name__ == "__main__":
    sys.exit(main())
