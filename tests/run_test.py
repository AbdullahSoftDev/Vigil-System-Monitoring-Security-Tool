#!/usr/bin/env python3
"""
Quick test to verify VIGIL components are working
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

def test_imports():
    """Test that all modules can be imported"""
    print("Testing module imports...")
    print("=" * 60)
    
    modules_to_test = [
        ('src.core.system_monitor', 'SystemMonitor'),
        ('src.core.supabase_client', 'SupabaseClient'),
        ('src.core.config_manager', 'ConfigManager'),
        ('src.core.alert_manager', 'AlertManager'),
        ('src.utils.encryption', 'EncryptionManager'),
    ]
    
    all_ok = True
    for module_path, class_name in modules_to_test:
        try:
            module = __import__(module_path, fromlist=[class_name])
            cls = getattr(module, class_name)
            print(f"✓ {module_path}.{class_name}")
        except ImportError as e:
            print(f"✗ {module_path}.{class_name} - ImportError: {e}")
            all_ok = False
        except AttributeError as e:
            print(f"✗ {module_path}.{class_name} - AttributeError: {e}")
            all_ok = False
        except Exception as e:
            print(f"✗ {module_path}.{class_name} - Error: {e}")
            all_ok = False
    
    print("=" * 60)
    return all_ok

def test_config():
    """Test configuration loading"""
    print("\nTesting configuration...")
    print("=" * 60)
    
    try:
        from src.core.config_manager import ConfigManager
        
        # Try to load config
        config = ConfigManager()
        
        print("✓ ConfigManager loaded successfully")
        print(f"  Monitoring interval: {config.get('monitoring.interval')}s")
        print(f"  Privacy level: {config.get('privacy.level')}")
        print(f"  Encryption enabled: {config.get('privacy.encryption_enabled')}")
        
        return True
    except Exception as e:
        print(f"✗ Config test failed: {e}")
        return False

def test_system_monitor():
    """Test system monitor in mock mode"""
    print("\nTesting SystemMonitor (mock mode)...")
    print("=" * 60)
    
    try:
        from src.core.system_monitor import SystemMonitor
        
        # Create config for testing
        test_config = {
            'testing': {'mock_mode': True},
            'monitoring': {'interval': 0.1, 'history_size': 10}
        }
        
        monitor = SystemMonitor(test_config)
        
        # Test basic methods
        cpu = monitor.get_cpu_usage()
        memory = monitor.get_memory_usage()
        system = monitor.get_system_info()
        
        print(f"✓ CPU: {cpu['percent']:.1f}%")
        print(f"✓ Memory: {memory['percent']:.1f}%")
        print(f"✓ System: {system['hostname']}")
        print(f"✓ All SystemMonitor methods working")
        
        return True
    except Exception as e:
        print(f"✗ SystemMonitor test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("VIGIL Component Test")
    print("=" * 60)
    
    tests = [
        ("Module Imports", test_imports),
        ("Configuration", test_config),
        ("System Monitor", test_system_monitor),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"✗ {test_name} crashed: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for test_name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status} - {test_name}")
        if not success:
            all_passed = False
    
    print("=" * 60)
    
    if all_passed:
        print("ALL TESTS PASSED! VIGIL components are working.")
        print("\nNext steps:")
        print("1. Edit .env file with your Supabase credentials")
        print("2. Run: python main.py")
    else:
        print("SOME TESTS FAILED. Check the errors above.")
        print("\nTroubleshooting:")
        print("1. Make sure all dependencies are installed: pip install -r requirements.txt")
        print("2. Check Python version (requires 3.10+): python3 --version")
        print("3. Run diagnostic: ./scripts/diagnose.sh")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())