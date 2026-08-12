"""
Diagnostic utilities for VIGIL system.
"""
import os
import sys
import platform
import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)

def check_system_monitor(system_monitor) -> Dict[str, Any]:
    """Check if system monitor is working."""
    try:
        if not system_monitor:
            return {'status': 'fail', 'message': 'System monitor not initialized'}
        
        metrics = system_monitor.get_current_metrics()
        if metrics:
            return {'status': 'pass', 'message': f'System monitor working, CPU: {metrics.get("cpu_percent", 0):.1f}%'}
        else:
            return {'status': 'fail', 'message': 'System monitor returned no metrics'}
    except Exception as e:
        return {'status': 'fail', 'message': f'System monitor error: {str(e)}'}

def check_security_logger(security_logger) -> Dict[str, Any]:
    """Check if security logger is working."""
    try:
        if not security_logger:
            return {'status': 'fail', 'message': 'Security logger not initialized'}
        
        events = security_logger.get_recent_events(limit=5)
        return {'status': 'pass', 'message': f'Security logger working, {len(events)} recent events'}
    except Exception as e:
        return {'status': 'fail', 'message': f'Security logger error: {str(e)}'}

def check_alert_manager(alert_manager) -> Dict[str, Any]:
    """Check if alert manager is working."""
    try:
        if not alert_manager:
            return {'status': 'fail', 'message': 'Alert manager not initialized'}
        
        alerts = alert_manager.get_recent_alerts(limit=5)
        return {'status': 'pass', 'message': f'Alert manager working, {len(alerts)} recent alerts'}
    except Exception as e:
        return {'status': 'fail', 'message': f'Alert manager error: {str(e)}'}

def check_cloud_sync(cloud_sync) -> Dict[str, Any]:
    """Check if cloud sync is working."""
    try:
        if not cloud_sync:
            return {'status': 'pass', 'message': 'Cloud sync not configured (optional)'}
        
        status = cloud_sync.get_sync_status()
        if status.get('online', False):
            return {'status': 'pass', 'message': f'Cloud sync online, queue: {status.get("queue_size", 0)}'}
        else:
            return {'status': 'fail', 'message': 'Cloud sync offline'}
    except Exception as e:
        return {'status': 'fail', 'message': f'Cloud sync error: {str(e)}'}

def check_dependencies() -> Dict[str, Any]:
    """Check if all dependencies are available."""
    missing = []
    
    try:
        import PySimpleGUI
    except ImportError:
        missing.append('PySimpleGUI')
    
    try:
        import psutil
    except ImportError:
        missing.append('psutil')
    
    try:
        import matplotlib
    except ImportError:
        missing.append('matplotlib')
    
    try:
        from watchdog.observers import Observer
    except ImportError:
        missing.append('watchdog')
    
    if missing:
        return {'status': 'fail', 'message': f'Missing dependencies: {", ".join(missing)}'}
    else:
        return {'status': 'pass', 'message': 'All dependencies available'}

def check_system_info() -> Dict[str, Any]:
    """Check system information."""
    try:
        info = {
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'processor': platform.processor(),
            'cores': os.cpu_count()
        }
        return {'status': 'pass', 'message': f'System: {info["platform"]}, Python: {info["python_version"]}'}
    except Exception as e:
        return {'status': 'fail', 'message': f'System info error: {str(e)}'}

def check_database() -> Dict[str, Any]:
    """Check if databases are accessible."""
    try:
        import sqlite3
        from pathlib import Path
        
        db_path = Path('~/.vigil').expanduser()
        if not db_path.exists():
            db_path.mkdir(parents=True, exist_ok=True)
            return {'status': 'pass', 'message': 'Database directory created'}
        
        # Try to create a test connection
        test_db = db_path / 'test.db'
        conn = sqlite3.connect(test_db)
        conn.execute('CREATE TABLE IF NOT EXISTS test (id INTEGER)')
        conn.execute('INSERT INTO test VALUES (1)')
        conn.execute('DROP TABLE test')
        conn.close()
        test_db.unlink()
        
        return {'status': 'pass', 'message': 'Database access working'}
    except Exception as e:
        return {'status': 'fail', 'message': f'Database error: {str(e)}'}

def check_configuration(config_manager) -> Dict[str, Any]:
    """Check if configuration is valid."""
    try:
        if not config_manager:
            return {'status': 'fail', 'message': 'Config manager not available'}
        
        config = config_manager.config
        if not config:
            return {'status': 'fail', 'message': 'Configuration empty'}
        
        # Check required sections
        required = ['monitoring', 'security', 'ui']
        missing_sections = [section for section in required if section not in config]
        
        if missing_sections:
            return {'status': 'fail', 'message': f'Missing config sections: {", ".join(missing_sections)}'}
        else:
            return {'status': 'pass', 'message': 'Configuration valid'}
    except Exception as e:
        return {'status': 'fail', 'message': f'Configuration error: {str(e)}'}

def run_diagnostics(system_monitor=None, security_logger=None, alert_manager=None, cloud_sync=None, config_manager=None) -> Dict[str, Dict[str, Any]]:
    """
    Run comprehensive system diagnostics.
    
    Returns:
        Dictionary of diagnostic results by category.
    """
    logger.info("Running system diagnostics...")
    
    results = {
        'System': {
            'System Information': check_system_info(),
            'Dependencies': check_dependencies(),
            'Database': check_database()
        },
        'Components': {
            'System Monitor': check_system_monitor(system_monitor),
            'Security Logger': check_security_logger(security_logger),
            'Alert Manager': check_alert_manager(alert_manager),
            'Cloud Sync': check_cloud_sync(cloud_sync)
        }
    }
    
    if config_manager:
        results['Configuration'] = {
            'Config Validation': check_configuration(config_manager)
        }
    
    # Calculate overall status
    all_tests = []
    for category in results.values():
        all_tests.extend(category.values())
    
    passed = sum(1 for test in all_tests if test['status'] == 'pass')
    total = len(all_tests)
    
    results['Summary'] = {
        'Overall': {
            'status': 'pass' if passed == total else 'fail',
            'message': f'{passed}/{total} tests passed ({passed/total*100:.1f}%)'
        }
    }
    
    logger.info(f"Diagnostics complete: {passed}/{total} tests passed")
    return results

def export_diagnostics(results: Dict[str, Dict[str, Any]], output_path: str = None) -> str:
    """Export diagnostic results to file."""
    from pathlib import Path
    import json
    from datetime import datetime
    
    if not output_path:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = Path('~/.vigil/diagnostics').expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f'diagnostic_{timestamp}.json')
    
    # Convert results to serializable format
    serializable = {}
    for category, tests in results.items():
        serializable[category] = {}
        for test_name, result in tests.items():
            serializable[category][test_name] = {
                'status': result.get('status'),
                'message': result.get('message'),
                'timestamp': datetime.now().isoformat()
            }
    
    with open(output_path, 'w') as f:
        json.dump(serializable, f, indent=2)
    
    return output_path

def print_diagnostics(results: Dict[str, Dict[str, Any]]):
    """Print diagnostic results to console."""
    print("\n" + "="*60)
    print("VIGIL SYSTEM DIAGNOSTICS")
    print("="*60)
    
    for category, tests in results.items():
        print(f"\n{category}:")
        print("-"*40)
        for test_name, result in tests.items():
            status = result.get('status', 'unknown')
            message = result.get('message', '')
            icon = "✓" if status == 'pass' else "✗" if status == 'fail' else "?"
            print(f"  {icon} {test_name}: {message}")
    
    print("\n" + "="*60)
    
    # Overall status
    summary = results.get('Summary', {}).get('Overall', {})
    if summary.get('status') == 'pass':
        print("✅ SYSTEM STATUS: HEALTHY")
    else:
        print("❌ SYSTEM STATUS: ISSUES DETECTED")
    
    print("="*60)