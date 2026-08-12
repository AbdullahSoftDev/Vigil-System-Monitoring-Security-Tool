"""
System Monitor for VIGIL
Project #34 Implementation
"""

import threading
import time
import collections
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Callable, Deque, Tuple, Any
import queue
import logging
import json
import os

import psutil
import pandas as pd

# Setup logging
logger = logging.getLogger(__name__)

@dataclass
class CPUUsage:
    """CPU usage data structure"""
    timestamp: datetime
    percent: float
    cores: List[float]
    frequency: Dict[str, float]

@dataclass
class MemoryUsage:
    """Memory usage data structure"""
    timestamp: datetime
    total: int
    available: int
    percent: float
    used_gb: float

@dataclass
class DiskIO:
    """Disk I/O data structure"""
    timestamp: datetime
    read_bytes_sec: float
    write_bytes_sec: float
    read_count: int
    write_count: int

@dataclass
class NetworkIO:
    """Network I/O data structure"""
    timestamp: datetime
    bytes_sent_sec: float
    bytes_recv_sec: float
    packets_sent: int
    packets_recv: int

@dataclass
class ProcessInfo:
    """Process information data structure"""
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
    memory_rss: int  # in bytes
    username: str
    cmdline: str
    timestamp: datetime

@dataclass
class SystemInfo:
    """System information data structure"""
    hostname: str
    os: str
    kernel: str
    uptime: int  # in seconds

class SystemMonitor:
    """Main system monitoring class implementing Project #34 requirements"""
    
    def __init__(self, config=None, alert_manager=None):
        self.config = config or {}
        self.alert_manager = alert_manager
        self.running = False
        self.monitor_thread = None
        self.alert_thread = None
        self.lock = threading.Lock()
        
        # Configuration
        monitoring_config = self.config.get('monitoring', {})
        self.update_interval = monitoring_config.get('interval', 2.0)
        self.history_size = monitoring_config.get('history_size', 300)
        self.process_update_interval = monitoring_config.get('process_update_interval', 5.0)
        
        # Alert thresholds
        alerts_config = self.config.get('alerts', {})
        self.cpu_threshold = alerts_config.get('cpu_threshold', 80.0)
        self.memory_threshold = alerts_config.get('memory_threshold', 90.0)
        self.disk_threshold = alerts_config.get('disk_threshold', 95.0)
        self.network_multiplier = alerts_config.get('network_baseline_multiplier', 2.0)
        self.consecutive_readings = alerts_config.get('consecutive_readings', 3)
        
        # Data storage
        self.cpu_history: Deque[CPUUsage] = collections.deque(maxlen=self.history_size)
        self.memory_history: Deque[MemoryUsage] = collections.deque(maxlen=self.history_size)
        self.disk_history: Deque[DiskIO] = collections.deque(maxlen=self.history_size)
        self.network_history: Deque[NetworkIO] = collections.deque(maxlen=self.history_size)
        self.process_history: Deque[List[ProcessInfo]] = collections.deque(maxlen=self.history_size // 10)
        
        # Alert tracking
        self.cpu_alert_count = 0
        self.memory_alert_count = 0
        self.disk_alerts = set()
        self.network_baseline = None
        self.network_baseline_samples = collections.deque(maxlen=60)  # 2 minutes of baseline
        
        # Event system
        self.on_alert = []  # List of callback functions for alerts
        self.on_metrics_update = []  # List of callback functions for metrics updates
        
        # Last readings for delta calculations
        self.last_disk_io = None
        self.last_network_io = None
        self.last_disk_time = time.time()
        self.last_network_time = time.time()
        self.last_process_update = 0
        
        # Cloud sync reference
        self.cloud_sync = None
        
        # Mock mode for testing
        self.mock_mode = self.config.get('testing', {}).get('mock_mode', False)
        
        # Initialize last readings
        try:
            self.last_disk_io = psutil.disk_io_counters()
            self.last_network_io = psutil.net_io_counters()
        except Exception as e:
            logger.warning(f"Could not initialize I/O counters: {e}")
        
        logger.info(f"SystemMonitor initialized with interval={self.update_interval}s, history={self.history_size}")
    
    def set_cloud_sync(self, cloud_sync):
        """Set cloud sync reference for automatic metric queuing."""
        self.cloud_sync = cloud_sync
        logger.info("Cloud sync reference set in SystemMonitor")
    
    def collect_metrics(self):
        """Collect all system metrics."""
        metrics = {}
        
        try:
            # CPU Usage
            cpu_percent = psutil.cpu_percent(interval=0.5)
            metrics['cpu_percent'] = cpu_percent
            
            # Memory Usage
            memory = psutil.virtual_memory()
            metrics['memory_percent'] = memory.percent
            metrics['memory_used_gb'] = memory.used / (1024**3)
            metrics['memory_total_gb'] = memory.total / (1024**3)
            
            # Disk Usage
            disk = psutil.disk_usage('/')
            metrics['disk_percent'] = disk.percent
            metrics['disk_used_gb'] = disk.used / (1024**3)
            metrics['disk_total_gb'] = disk.total / (1024**3)
            
            # Network
            net_io = psutil.net_io_counters()
            metrics['network_sent_mb'] = net_io.bytes_sent / (1024**2)
            metrics['network_recv_mb'] = net_io.bytes_recv / (1024**2)
            metrics['network_sent_kbps'] = (net_io.bytes_sent / 1024) / self.update_interval
            metrics['network_recv_kbps'] = (net_io.bytes_recv / 1024) / self.update_interval
            
            # Processes
            metrics['process_count'] = len(psutil.pids())
            
            # Load Average
            load_avg = psutil.getloadavg()
            metrics['load_avg_1m'] = load_avg[0]
            metrics['load_avg_5m'] = load_avg[1]
            metrics['load_avg_15m'] = load_avg[2]
            metrics['load_avg'] = f"{load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}"
            
            # Timestamp
            metrics['timestamp'] = datetime.now().isoformat()
            
            # Queue to cloud sync if available
            if self.cloud_sync and hasattr(self.cloud_sync, 'queue_system_metrics'):
                try:
                    self.cloud_sync.queue_system_metrics(metrics)
                except Exception as e:
                    logger.warning(f"Failed to queue metrics to cloud sync: {e}")
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error collecting metrics: {e}")
            return {}
    
    def start(self):
        """Start the monitoring threads"""
        if self.running:
            return
        
        self.running = True
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        
        # Start alert checking thread
        self.alert_thread = threading.Thread(target=self._alert_check_loop, daemon=True)
        self.alert_thread.start()
        
        logger.info("SystemMonitor started")
    
    def stop(self):
        """Stop the monitoring threads"""
        self.running = False
        
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5.0)
        if self.alert_thread:
            self.alert_thread.join(timeout=5.0)
        
        logger.info("SystemMonitor stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop - collects metrics"""
        process_counter = 0
        
        while self.running:
            try:
                timestamp = datetime.now()
                
                # Collect system metrics
                cpu_data = self.get_cpu_usage()
                memory_data = self.get_memory_usage()
                disk_data = self.get_disk_io()
                network_data = self.get_network_io()
                
                # Store in history
                with self.lock:
                    self.cpu_history.append(CPUUsage(
                        timestamp=timestamp,
                        percent=cpu_data['percent'],
                        cores=cpu_data['cores'],
                        frequency=cpu_data['frequency']
                    ))
                    
                    self.memory_history.append(MemoryUsage(
                        timestamp=timestamp,
                        total=memory_data['total'],
                        available=memory_data['available'],
                        percent=memory_data['percent'],
                        used_gb=memory_data['used_gb']
                    ))
                    
                    self.disk_history.append(DiskIO(
                        timestamp=timestamp,
                        read_bytes_sec=disk_data['read_bytes_sec'],
                        write_bytes_sec=disk_data['write_bytes_sec'],
                        read_count=disk_data['read_count'],
                        write_count=disk_data['write_count']
                    ))
                    
                    self.network_history.append(NetworkIO(
                        timestamp=timestamp,
                        bytes_sent_sec=network_data['bytes_sent_sec'],
                        bytes_recv_sec=network_data['bytes_recv_sec'],
                        packets_sent=network_data['packets_sent'],
                        packets_recv=network_data['packets_recv']
                    ))
                
                # Update processes periodically (less frequent due to cost)
                process_counter += 1
                if process_counter >= (self.process_update_interval / self.update_interval):
                    processes = self.get_running_processes()
                    with self.lock:
                        self.process_history.append(processes)
                    process_counter = 0
                    self.last_process_update = time.time()
                
                # Add network data to baseline samples
                total_traffic = network_data['bytes_sent_sec'] + network_data['bytes_recv_sec']
                self.network_baseline_samples.append(total_traffic)
                
                # Calculate network baseline (average of last 60 samples)
                if len(self.network_baseline_samples) >= 10:  # Need at least 10 samples
                    self.network_baseline = sum(self.network_baseline_samples) / len(self.network_baseline_samples)
                
                # Check for CPU and memory alerts
                self._check_cpu_memory_alerts(cpu_data, memory_data, network_data)
                
                # Notify listeners of metrics update
                self._notify_metrics_update({
                    'cpu': cpu_data,
                    'memory': memory_data,
                    'disk': disk_data,
                    'network': network_data,
                    'timestamp': timestamp
                })
                
                # Sleep until next interval
                time.sleep(self.update_interval)
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}", exc_info=True)
                time.sleep(1)  # Prevent tight loop on error
    
    def _check_cpu_memory_alerts(self, cpu_data, memory_data, network_data):
        """Check for CPU and memory threshold alerts"""
        # Check CPU
        if cpu_data['percent'] > self.cpu_threshold:
            self.cpu_alert_count += 1
            if self.cpu_alert_count >= self.consecutive_readings:
                self._trigger_alert(
                    alert_type='CPU',
                    message=f"High CPU usage: {cpu_data['percent']:.1f}% > {self.cpu_threshold}% threshold",
                    severity='WARNING' if cpu_data['percent'] < 95.0 else 'CRITICAL',
                    data=cpu_data
                )
                self.cpu_alert_count = 0  # Reset after alert
        else:
            self.cpu_alert_count = 0
        
        # Check memory
        if memory_data['percent'] > self.memory_threshold:
            self.memory_alert_count += 1
            if self.memory_alert_count >= self.consecutive_readings:
                self._trigger_alert(
                    alert_type='Memory',
                    message=f"High memory usage: {memory_data['percent']:.1f}% > {self.memory_threshold}% threshold",
                    severity='WARNING' if memory_data['percent'] < 98.0 else 'CRITICAL',
                    data=memory_data
                )
                self.memory_alert_count = 0  # Reset after alert
        else:
            self.memory_alert_count = 0
        
        # Check network (if baseline established)
        if self.network_baseline:
            total_traffic = network_data['bytes_sent_sec'] + network_data['bytes_recv_sec']
            if total_traffic > self.network_baseline * self.network_multiplier:
                self._trigger_alert(
                    alert_type='Network',
                    message=f"Unusual network traffic: {total_traffic/1024:.1f} KB/s > {self.network_baseline/1024:.1f} KB/s baseline",
                    severity='INFO',
                    data=network_data
                )
    
    def _alert_check_loop(self):
        """Separate thread for checking alerts"""
        disk_check_counter = 0
        disk_check_interval = self.config.get('monitoring', {}).get('disk_check_interval', 60)
        
        while self.running:
            try:
                # Check disk usage periodically (less frequent)
                disk_check_counter += 1
                if disk_check_counter >= (disk_check_interval / self.update_interval):
                    self._check_disk_usage()
                    disk_check_counter = 0
                
                time.sleep(self.update_interval)
                
            except Exception as e:
                logger.error(f"Error in alert check loop: {e}")
                time.sleep(1)
    
    def _check_disk_usage(self):
        """Check disk usage for all partitions"""
        for partition in psutil.disk_partitions():
            try:
                if partition.fstype and 'loop' not in partition.device:  # Skip loop devices
                    usage = psutil.disk_usage(partition.mountpoint)
                    
                    if usage.percent > self.disk_threshold:
                        if partition.mountpoint not in self.disk_alerts:
                            self._trigger_alert(
                                alert_type='Disk',
                                message=f"Disk {partition.mountpoint} usage {usage.percent:.1f}% > {self.disk_threshold}% threshold",
                                severity='WARNING',
                                data={
                                    'mountpoint': partition.mountpoint,
                                    'usage_percent': usage.percent,
                                    'total_gb': usage.total / (1024**3),
                                    'used_gb': usage.used / (1024**3),
                                    'free_gb': usage.free / (1024**3)
                                }
                            )
                            self.disk_alerts.add(partition.mountpoint)
                    elif partition.mountpoint in self.disk_alerts:
                        # Usage dropped below threshold, clear alert
                        self.disk_alerts.remove(partition.mountpoint)
                        
            except (PermissionError, OSError) as e:
                logger.debug(f"Cannot check disk {partition.mountpoint}: {e}")
            except Exception as e:
                logger.error(f"Error checking disk usage for {partition.mountpoint}: {e}")
    
    def _notify_metrics_update(self, metrics):
        """Notify all registered callbacks of metrics update"""
        for callback in self.on_metrics_update:
            try:
                callback(metrics)
            except Exception as e:
                logger.error(f"Error in metrics callback: {e}")
    
    def _trigger_alert(self, alert_type: str, message: str, severity: str = 'WARNING', data: Dict = None):
        """Trigger an alert and notify listeners"""
        alert = {
            'type': alert_type,
            'message': message,
            'timestamp': datetime.now(),
            'severity': severity,
            'data': data or {}
        }
        
        logger.warning(f"Alert: {message}")
        
        # Send to alert manager if available
        if self.alert_manager and hasattr(self.alert_manager, 'handle_system_alert'):
            try:
                self.alert_manager.handle_system_alert(alert)
            except Exception as e:
                logger.error(f"Failed to send alert to alert manager: {e}")
        
        # Notify registered callbacks
        for callback in self.on_alert:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"Error in alert callback: {e}")
    
    # =========================================================================
    # REQUIRED METHODS - Project #34
    # =========================================================================
    
    def get_cpu_usage(self) -> Dict:
        """
        Get CPU usage statistics
        
        Returns:
            dict: {percent: float, cores: list, frequency: dict}
        """
        if self.mock_mode:
            return {
                'percent': 25.5,
                'cores': [20.0, 25.0, 30.0, 35.0] * 2,  # Simulate 8 cores
                'frequency': {'current': 2400.0, 'min': 800.0, 'max': 3500.0}
            }
        
        try:
            # Get overall CPU percentage
            percent = psutil.cpu_percent(interval=0.1)
            
            # Get per-core percentages
            per_cpu = psutil.cpu_percent(interval=0.1, percpu=True)
            
            # Get CPU frequency if available
            freq = psutil.cpu_freq()
            frequency = {}
            if freq:
                frequency = {
                    'current': float(freq.current) if freq.current else 0.0,
                    'min': float(freq.min) if freq.min else 0.0,
                    'max': float(freq.max) if freq.max else 0.0
                }
            else:
                frequency = {'current': 0.0, 'min': 0.0, 'max': 0.0}
            
            return {
                'percent': float(percent),
                'cores': [float(core) for core in per_cpu],
                'frequency': frequency
            }
        except Exception as e:
            logger.error(f"Error getting CPU usage: {e}")
            return {'percent': 0.0, 'cores': [], 'frequency': {}}
    
    def get_memory_usage(self) -> Dict:
        """
        Get memory usage statistics
        
        Returns:
            dict: {total: int, available: int, percent: float, used_gb: float}
        """
        if self.mock_mode:
            return {
                'total': 17179869184,  # 16GB
                'available': 8589934592,  # 8GB
                'percent': 50.0,
                'used_gb': 8.0
            }
        
        try:
            mem = psutil.virtual_memory()
            return {
                'total': int(mem.total),
                'available': int(mem.available),
                'percent': float(mem.percent),
                'used_gb': float(mem.used / (1024**3))  # Convert to GB
            }
        except Exception as e:
            logger.error(f"Error getting memory usage: {e}")
            return {'total': 0, 'available': 0, 'percent': 0.0, 'used_gb': 0.0}
    
    def get_disk_io(self) -> Dict:
        """
        Get disk I/O statistics
        
        Returns:
            dict: {read_bytes_sec: float, write_bytes_sec: float, read_count: int, write_count: int}
        """
        if self.mock_mode:
            return {
                'read_bytes_sec': 102400.0,  # 100 KB/s
                'write_bytes_sec': 51200.0,   # 50 KB/s
                'read_count': 10,
                'write_count': 5
            }
        
        try:
            current_time = time.time()
            current_io = psutil.disk_io_counters()
            
            # Calculate deltas if we have previous readings
            if self.last_disk_io and current_io:
                time_diff = current_time - self.last_disk_time
                if time_diff > 0:
                    read_bytes_sec = (current_io.read_bytes - self.last_disk_io.read_bytes) / time_diff
                    write_bytes_sec = (current_io.write_bytes - self.last_disk_io.write_bytes) / time_diff
                    read_count = current_io.read_count - self.last_disk_io.read_count
                    write_count = current_io.write_count - self.last_disk_io.write_count
                else:
                    read_bytes_sec = 0.0
                    write_bytes_sec = 0.0
                    read_count = 0
                    write_count = 0
            else:
                # First reading or no counters available
                read_bytes_sec = 0.0
                write_bytes_sec = 0.0
                read_count = 0
                write_count = 0
            
            # Update last readings
            self.last_disk_io = current_io
            self.last_disk_time = current_time
            
            return {
                'read_bytes_sec': float(read_bytes_sec),
                'write_bytes_sec': float(write_bytes_sec),
                'read_count': int(read_count),
                'write_count': int(write_count)
            }
        except Exception as e:
            logger.error(f"Error getting disk I/O: {e}")
            return {'read_bytes_sec': 0.0, 'write_bytes_sec': 0.0, 'read_count': 0, 'write_count': 0}
    
    def get_network_io(self) -> Dict:
        """
        Get network I/O statistics
        
        Returns:
            dict: {bytes_sent_sec: float, bytes_recv_sec: float, packets_sent: int, packets_recv: int}
        """
        if self.mock_mode:
            return {
                'bytes_sent_sec': 51200.0,   # 50 KB/s
                'bytes_recv_sec': 102400.0,  # 100 KB/s
                'packets_sent': 100,
                'packets_recv': 150
            }
        
        try:
            current_time = time.time()
            current_io = psutil.net_io_counters()
            
            # Calculate deltas if we have previous readings
            if self.last_network_io and current_io:
                time_diff = current_time - self.last_network_time
                if time_diff > 0:
                    bytes_sent_sec = (current_io.bytes_sent - self.last_network_io.bytes_sent) / time_diff
                    bytes_recv_sec = (current_io.bytes_recv - self.last_network_io.bytes_recv) / time_diff
                    packets_sent = current_io.packets_sent - self.last_network_io.packets_sent
                    packets_recv = current_io.packets_recv - self.last_network_io.packets_recv
                else:
                    bytes_sent_sec = 0.0
                    bytes_recv_sec = 0.0
                    packets_sent = 0
                    packets_recv = 0
            else:
                # First reading or no counters available
                bytes_sent_sec = 0.0
                bytes_recv_sec = 0.0
                packets_sent = 0
                packets_recv = 0
            
            # Update last readings
            self.last_network_io = current_io
            self.last_network_time = current_time
            
            return {
                'bytes_sent_sec': float(bytes_sent_sec),
                'bytes_recv_sec': float(bytes_recv_sec),
                'packets_sent': int(packets_sent),
                'packets_recv': int(packets_recv)
            }
        except Exception as e:
            logger.error(f"Error getting network I/O: {e}")
            return {'bytes_sent_sec': 0.0, 'bytes_recv_sec': 0.0, 'packets_sent': 0, 'packets_recv': 0}
    
    def get_running_processes(self) -> List[Dict]:
        """
        Get list of running processes
        
        Returns:
            list: List of dicts with process information
        """
        if self.mock_mode:
            timestamp = datetime.now()
            return [
                {
                    'pid': 1,
                    'name': 'systemd',
                    'cpu_percent': 0.5,
                    'memory_percent': 1.2,
                    'memory_rss': 10485760,
                    'username': 'root',
                    'cmdline': '/sbin/init',
                    'timestamp': timestamp
                },
                {
                    'pid': 1234,
                    'name': 'python3',
                    'cpu_percent': 2.5,
                    'memory_percent': 3.8,
                    'memory_rss': 15728640,
                    'username': 'user',
                    'cmdline': 'python3 main.py',
                    'timestamp': timestamp
                }
            ]
        
        processes = []
        timestamp = datetime.now()
        
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info', 'username', 'cmdline']):
            try:
                info = proc.info
                
                # Handle missing or None values
                pid = info['pid']
                name = info['name'] or 'Unknown'
                cpu_percent = float(info['cpu_percent'] or 0.0)
                memory_percent = float(info['memory_percent'] or 0.0)
                memory_rss = int(info['memory_info'].rss if info['memory_info'] else 0)
                username = info['username'] or 'Unknown'
                
                # Handle cmdline
                cmdline = info['cmdline']
                if cmdline:
                    cmdline_str = ' '.join(cmdline)
                else:
                    cmdline_str = ''
                
                processes.append({
                    'pid': pid,
                    'name': name,
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory_percent,
                    'memory_rss': memory_rss,
                    'username': username,
                    'cmdline': cmdline_str,
                    'timestamp': timestamp
                })
                
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                # Process disappeared or we don't have permission
                continue
            except Exception as e:
                logger.debug(f"Error getting process info: {e}")
                continue
        
        return processes
    
    def get_system_info(self) -> Dict:
        """
        Get system information - FIXED VERSION
        
        Returns:
            dict: {hostname: str, os: str, kernel: str, uptime: int}
        """
        if self.mock_mode:
            return {
                'hostname': 'mock-host',
                'os': 'Mock OS 1.0',
                'kernel': '5.15.0-mock',
                'uptime': 86400  # 24 hours
            }
        
        try:
            import platform
            uname = platform.uname()
            boot_time = psutil.boot_time()
            uptime = int(time.time() - boot_time)
            
            # FIX: Use 'node' instead of 'nodename'
            return {
                'hostname': uname.node,  # <-- THIS IS THE FIX
                'os': f"{uname.system} {uname.release}",
                'kernel': uname.version,
                'uptime': uptime
            }
        except Exception as e:
            logger.error(f"Error getting system info: {e}")
            return {'hostname': 'Unknown', 'os': 'Unknown', 'kernel': 'Unknown', 'uptime': 0}
    
    # =========================================================================
    # ADDITIONAL METHODS
    # =========================================================================
    
    def get_processes_sorted_by_cpu(self, limit: int = 10) -> List[Dict]:
        """Get processes sorted by CPU usage (descending)"""
        processes = self.get_running_processes()
        return sorted(processes, key=lambda x: x['cpu_percent'], reverse=True)[:limit]
    
    def get_processes_sorted_by_memory(self, limit: int = 10) -> List[Dict]:
        """Get processes sorted by memory usage (descending)"""
        processes = self.get_running_processes()
        return sorted(processes, key=lambda x: x['memory_percent'], reverse=True)[:limit]
    
    def get_processes(self, limit: int = 100) -> List[Dict]:
        """
        Get processes for dashboard compatibility.
        
        Args:
            limit: Maximum number of processes to return
            
        Returns:
            List of process dictionaries
        """
        processes = self.get_running_processes()
        return processes[:limit]
    
    def get_current_metrics(self) -> Dict:
        """Get current metrics snapshot - DASHBOARD COMPATIBLE VERSION"""
        try:
            # Get all individual metrics
            cpu_data = self.get_cpu_usage()
            memory_data = self.get_memory_usage()
            disk_data = self.get_disk_io()
            network_data = self.get_network_io()
            system_info = self.get_system_info()
            
            # Get disk usage for dashboard
            try:
                disk_percent = psutil.disk_usage('/').percent
            except:
                disk_percent = 0
            
            # Format for dashboard compatibility
            return {
                # Dashboard expects these flat keys
                'cpu_percent': cpu_data.get('percent', 0),
                'memory_percent': memory_data.get('percent', 0),
                'disk_percent': disk_percent,
                
                # Network in KB/s for dashboard
                'network_sent_kbps': (network_data.get('bytes_sent_sec', 0) / 1024),
                'network_recv_kbps': (network_data.get('bytes_recv_sec', 0) / 1024),
                
                # System info
                'uptime': self._format_uptime(system_info.get('uptime', 0)),
                'process_count': len(psutil.pids()),
                'load_avg': self._get_load_avg_string(),
                
                # For compatibility - also include the original structure
                'cpu': cpu_data,
                'memory': memory_data,
                'disk': disk_data,
                'network': network_data,
                'system': system_info,
                'timestamp': datetime.now()
            }
        except Exception as e:
            logger.error(f"Error in get_current_metrics: {e}")
            return {
                'cpu_percent': 0,
                'memory_percent': 0,
                'disk_percent': 0,
                'network_sent_kbps': 0,
                'network_recv_kbps': 0,
                'uptime': '0:00:00',
                'process_count': 0,
                'load_avg': '0.00, 0.00, 0.00',
                'timestamp': datetime.now()
            }
    
    def _format_uptime(self, seconds: int) -> str:
        """Format uptime seconds to HH:MM:SS"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours}:{minutes:02d}:{secs:02d}"
    
    def _get_load_avg_string(self) -> str:
        """Get load average as string"""
        try:
            load = psutil.getloadavg()
            return f"{load[0]:.2f}, {load[1]:.2f}, {load[2]:.2f}"
        except:
            return "0.00, 0.00, 0.00"
    
    def get_cpu_history_dataframe(self) -> pd.DataFrame:
        """Export CPU history to pandas DataFrame"""
        with self.lock:
            data = list(self.cpu_history)
        
        if not data:
            return pd.DataFrame()
        
        records = []
        for item in data:
            record = {
                'timestamp': item.timestamp,
                'cpu_percent': item.percent,
            }
            # Add individual core percentages
            for i, core in enumerate(item.cores):
                record[f'core_{i}'] = core
            
            # Add frequency info
            for key, value in item.frequency.items():
                record[f'freq_{key}'] = value
            
            records.append(record)
        
        return pd.DataFrame(records)
    
    def get_memory_history_dataframe(self) -> pd.DataFrame:
        """Export memory history to pandas DataFrame"""
        with self.lock:
            data = list(self.memory_history)
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame([{
            'timestamp': item.timestamp,
            'memory_percent': item.percent,
            'memory_total_gb': item.total / (1024**3),
            'memory_available_gb': item.available / (1024**3),
            'memory_used_gb': item.used_gb
        } for item in data])
        
        return df
    
    def get_disk_history_dataframe(self) -> pd.DataFrame:
        """Export disk I/O history to pandas DataFrame"""
        with self.lock:
            data = list(self.disk_history)
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame([{
            'timestamp': item.timestamp,
            'disk_read_mb_sec': item.read_bytes_sec / (1024**2),
            'disk_write_mb_sec': item.write_bytes_sec / (1024**2),
            'disk_read_count': item.read_count,
            'disk_write_count': item.write_count
        } for item in data])
        
        return df
    
    def get_network_history_dataframe(self) -> pd.DataFrame:
        """Export network I/O history to pandas DataFrame"""
        with self.lock:
            data = list(self.network_history)
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame([{
            'timestamp': item.timestamp,
            'network_sent_mb_sec': item.bytes_sent_sec / (1024**2),
            'network_recv_mb_sec': item.bytes_recv_sec / (1024**2),
            'network_packets_sent': item.packets_sent,
            'network_packets_recv': item.packets_recv
        } for item in data])
        
        return df
    
    def get_all_history_dataframe(self) -> Dict[str, pd.DataFrame]:
        """Get all history data as DataFrames"""
        return {
            'cpu': self.get_cpu_history_dataframe(),
            'memory': self.get_memory_history_dataframe(),
            'disk': self.get_disk_history_dataframe(),
            'network': self.get_network_history_dataframe()
        }
    
    def register_alert_callback(self, callback: Callable):
        """Register a callback function for alerts"""
        if callback not in self.on_alert:
            self.on_alert.append(callback)
            logger.debug(f"Registered alert callback: {callback.__name__}")
    
    def register_metrics_callback(self, callback: Callable):
        """Register a callback function for metrics updates"""
        if callback not in self.on_metrics_update:
            self.on_metrics_update.append(callback)
            logger.debug(f"Registered metrics callback: {callback.__name__}")
    
    def clear_histories(self):
        """Clear all history data"""
        with self.lock:
            self.cpu_history.clear()
            self.memory_history.clear()
            self.disk_history.clear()
            self.network_history.clear()
            self.process_history.clear()
        
        logger.info("All histories cleared")
    
    def get_stats(self) -> Dict:
        """Get monitoring statistics"""
        with self.lock:
            return {
                'cpu_history_size': len(self.cpu_history),
                'memory_history_size': len(self.memory_history),
                'disk_history_size': len(self.disk_history),
                'network_history_size': len(self.network_history),
                'process_history_size': len(self.process_history),
                'running': self.running,
                'update_interval': self.update_interval
            }
    
    def set_mock_mode(self, enabled: bool):
        """Enable or disable mock mode for testing"""
        self.mock_mode = enabled
        logger.info(f"Mock mode {'enabled' if enabled else 'disabled'}")
    
    def set_update_interval(self, interval: float):
        """Change the update interval (for testing)"""
        self.update_interval = max(0.1, interval)  # Minimum 0.1 seconds
        logger.info(f"Update interval changed to {self.update_interval}s")
    
    def start_monitoring(self):
        """Alias for start() for compatibility"""
        self.start()
    
    def stop_monitoring(self):
        """Alias for stop() for compatibility"""
        self.stop()