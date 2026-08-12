#!/usr/bin/env python3
"""
VIGIL - Live System Monitoring Dashboard
Main entry point for the VIGIL monitoring system
"""

import os
import sys
import signal
import time
import logging
from pathlib import Path

# Add the src directory to the Python path
current_dir = Path(__file__).parent
src_dir = current_dir / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from src.core.config_manager import ConfigManager
from src.core.system_monitor import SystemMonitor
from src.core.alert_manager import AlertManager
from src.core.security_logger import SecurityLogger
from src.core.cloud_sync import CloudSync
from src.ui.dashboard import VigilDashboard

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('vigil.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

class Vigil:
    """Main VIGIL application class"""
    
    def __init__(self):
        self.running = False
        self.config_manager = None
        self.alert_manager = None
        self.system_monitor = None
        self.security_logger = None
        self.cloud_sync = None
        self.dashboard = None
        
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.info("Shutdown signal received")
            self.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def initialize_components(self):
        """Initialize all components"""
        logger.info("=" * 60)
        logger.info("STARTING VIGIL - LIVE MONITORING SYSTEM")
        logger.info("=" * 60)
        
        # 1. Load configuration
        logger.info("📋 Loading configuration...")
        self.config_manager = ConfigManager()
        logger.info("✅ Configuration loaded")
        
        # 2. Initialize AlertManager
        logger.info("🚨 Initializing AlertManager...")
        self.alert_manager = AlertManager(config=self.config_manager.config)
        logger.info("✅ AlertManager initialized")
        
        # 3. Initialize SystemMonitor
        logger.info("💻 Initializing SystemMonitor...")
        self.system_monitor = SystemMonitor(
            config=self.config_manager.config,
            alert_manager=self.alert_manager
        )
        logger.info("✅ SystemMonitor initialized")
        
        # 4. Initialize SecurityLogger (with error handling for threading)
        logger.info("🛡️ Initializing SecurityLogger...")
        try:
            self.security_logger = SecurityLogger(
                config_manager=self.config_manager,
                alert_manager=self.alert_manager
            )
            logger.info("✅ SecurityLogger initialized")
        except Exception as e:
            logger.error(f"⚠️ SecurityLogger initialization failed: {e}")
            logger.info("⚠️ Security monitoring will be limited")
            self.security_logger = None
        
        # 5. Initialize CloudSync
        logger.info("☁️ Initializing CloudSync...")
        try:
            self.cloud_sync = CloudSync(
                config_manager=self.config_manager,
                alert_manager=self.alert_manager
            )
            # Set cloud sync references
            if self.cloud_sync:
                self.system_monitor.set_cloud_sync(self.cloud_sync)
                self.alert_manager.set_cloud_sync(self.cloud_sync)
            logger.info("✅ CloudSync initialized")
        except Exception as e:
            logger.error(f"⚠️ CloudSync initialization failed: {e}")
            logger.info("⚠️ Cloud sync will be disabled")
            self.cloud_sync = None
        
        # 6. Initialize Dashboard
        logger.info("📊 Initializing Dashboard...")
        self.dashboard = VigilDashboard(self.config_manager)
        self.dashboard.set_components(
            system_monitor=self.system_monitor,
            security_logger=self.security_logger,
            alert_manager=self.alert_manager,
            cloud_sync=self.cloud_sync
        )
        logger.info("✅ Dashboard initialized")
        
        # 7. Test components
        self.test_components()
        
        logger.info("✅ All core components initialized successfully")
        return True
    
    def test_components(self):
        """Test that all components are working"""
        try:
            # Test system monitor
            system_info = self.system_monitor.get_system_info()
            logger.info(f"System: {system_info.get('os', 'Unknown')} on {system_info.get('hostname', 'Unknown')}")
            
            # Test alert manager with correct parameters
            test_alert = {
                'type': 'system_test',
                'severity': 'info',
                'message': 'VIGIL initialization test',
                'timestamp': time.time()
            }
            self.alert_manager.handle_system_alert(test_alert)
            logger.info("✅ Alert system test passed")
            
        except Exception as e:
            logger.error(f"⚠️ Component test failed: {e}")
    
    def start_components(self):
        """Start all monitoring components"""
        logger.info("▶️ Starting monitoring components...")
        
        # Start SystemMonitor
        self.system_monitor.start()
        logger.info("✅ SystemMonitor started - CPU/Memory/Disk/Network monitoring active")
        
        # Start SecurityLogger
        if self.security_logger:
            try:
                self.security_logger.start_monitoring()
                logger.info("✅ SecurityLogger started - File/Process/Auth monitoring active")
            except Exception as e:
                logger.error(f"⚠️ Failed to start SecurityLogger: {e}")
        
        # Start CloudSync
        if self.cloud_sync:
            try:
                self.cloud_sync.start()
                logger.info("✅ CloudSync started - Remote monitoring enabled")
            except Exception as e:
                logger.error(f"⚠️ Failed to start CloudSync: {e}")
        
        # Show initial metrics
        self.show_initial_metrics()
    
    def show_initial_metrics(self):
        """Show initial system metrics"""
        logger.info("📊 Initial System Metrics:")
        try:
            # Get current metrics
            cpu = self.system_monitor.get_cpu_usage()
            memory = self.system_monitor.get_memory_usage()
            disk_io = self.system_monitor.get_disk_io()
            network = self.system_monitor.get_network_io()
            system_info = self.system_monitor.get_system_info()
            
            # Get disk usage for root
            import psutil
            root_disk = psutil.disk_usage('/')
            
            logger.info(f"  CPU Usage: {cpu['percent']:.1f}%")
            logger.info(f"  Memory Usage: {memory['percent']:.1f}% ({memory['used_gb']:.1f} GB used)")
            logger.info(f"  Disk Usage: {root_disk.percent:.1f}% ({root_disk.used/(1024**3):.1f} GB used)")
            logger.info(f"  Processes: {len(psutil.pids())}")
            logger.info(f"  Uptime: {self.format_uptime(system_info.get('uptime', 0))}")
            
            # Get security event count if available
            if self.security_logger:
                try:
                    event_count = self.security_logger.get_recent_events_count(hours=1)
                    logger.info(f"  Security Events (last hour): {event_count}")
                except:
                    logger.info(f"  Security Events: N/A")
            
        except Exception as e:
            logger.error(f"Error getting initial metrics: {e}")
    
    def format_uptime(self, seconds):
        """Format uptime into human readable string"""
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m {seconds}s"
    
    def run(self):
        """Main run loop"""
        try:
            # Setup
            self.setup_signal_handlers()
            
            # Initialize components
            if not self.initialize_components():
                logger.error("Failed to initialize components")
                return 1
            
            # Start monitoring
            self.start_components()
            
            # Show startup message
            self.show_startup_message()
            
            # Run dashboard
            logger.info("📊 Starting dashboard...")
            self.dashboard.run()
            
            # Keep running
            self.running = True
            while self.running:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Shutdown requested by user")
            self.stop()
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            self.stop()
            return 1
        
        return 0
    
    def show_startup_message(self):
        """Show startup message"""
        logger.info("=" * 60)
        logger.info("🎉 VIGIL IS NOW RUNNING!")
        logger.info("=" * 60)
        logger.info("📊 Dashboard will open in a new window")
        logger.info("🔄 Live updates: Every 1-2 seconds")
        logger.info("📈 Graphs: CPU, Memory, Network (live)")
        logger.info("🛡️ Security: File monitoring, Process tracking")
        logger.info("🚨 Alerts: Real-time notifications")
        logger.info("=" * 60)
        logger.info("Press Ctrl+C in terminal or close dashboard window to stop")
        logger.info("=" * 60)
    
    def stop(self):
        """Stop all components"""
        logger.info("🛑 Stopping VIGIL...")
        self.running = False
        
        if self.system_monitor:
            self.system_monitor.stop()
            logger.info("✅ SystemMonitor stopped")
        
        if self.security_logger:
            try:
                self.security_logger.stop_monitoring()
                logger.info("✅ SecurityLogger stopped")
            except Exception as e:
                logger.error(f"Error stopping SecurityLogger: {e}")
        
        if self.cloud_sync:
            try:
                self.cloud_sync.stop()
                logger.info("✅ CloudSync stopped")
            except Exception as e:
                logger.error(f"Error stopping CloudSync: {e}")
        
        logger.info("👋 VIGIL shutdown complete")

def main():
    """Main entry point"""
    vigil = Vigil()
    return vigil.run()

if __name__ == "__main__":
    sys.exit(main())