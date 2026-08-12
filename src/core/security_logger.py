"""
Security Logger - Project #49
File system and log monitoring with security event detection.
"""
import os
import re
import sys
import json
import sqlite3
import threading
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from enum import Enum
import logging
from threading import Lock, RLock
import sqlite3
from contextlib import contextmanager
import queue

# Third-party imports
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
import psutil

# Local imports
from .alert_manager import AlertManager, AlertSeverity, AlertCategory
from .config_manager import ConfigManager

# Setup logging
logger = logging.getLogger(__name__)

class EventType(Enum):
    """Types of security events."""
    FILE_ACCESS = "file_access"
    FILE_MODIFICATION = "file_modification"
    FILE_DELETION = "file_deletion"
    FILE_CREATION = "file_creation"
    PERMISSION_VIOLATION = "permission_violation"
    AUTH_FAILURE = "auth_failure"
    AUTH_SUCCESS = "auth_success"
    SUSPICIOUS_PROCESS = "suspicious_process"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    BRUTE_FORCE = "brute_force"
    UNAUTHORIZED_ACCESS = "unauthorized_access"

class SecurityEvent:
    """Represents a security event."""
    
    def __init__(self, 
                 event_type: EventType,
                 severity: AlertSeverity,
                 description: str,
                 user: Optional[str] = None,
                 source_ip: Optional[str] = None,
                 file_path: Optional[str] = None,
                 process_id: Optional[int] = None,
                 metadata: Optional[Dict] = None):
        self.id = None  # Will be set by database
        self.timestamp = datetime.now()
        self.event_type = event_type
        self.severity = severity
        self.user = user
        self.source_ip = source_ip
        self.file_path = file_path
        self.process_id = process_id
        self.description = description
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'event_type': self.event_type.value,
            'severity': self.severity.value,
            'user': self.user,
            'source_ip': self.source_ip,
            'file_path': self.file_path,
            'process_id': self.process_id,
            'description': self.description,
            'metadata': json.dumps(self.metadata) if self.metadata else '{}'
        }

class ThreadSafeDatabase:
    """Thread-safe SQLite database wrapper."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection_pool = queue.Queue(maxsize=5)
        self.init_connection_pool()
        
    def init_connection_pool(self):
        """Initialize connection pool."""
        for _ in range(5):
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=10.0
            )
            conn.row_factory = sqlite3.Row
            self.connection_pool.put(conn)
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool (thread-safe)."""
        conn = None
        try:
            conn = self.connection_pool.get(timeout=5.0)
            yield conn
        finally:
            if conn:
                self.connection_pool.put(conn)
    
    def close_all(self):
        """Close all connections in the pool."""
        while not self.connection_pool.empty():
            try:
                conn = self.connection_pool.get_nowait()
                conn.close()
            except:
                pass

class SecurityLogger:
    """
    Main Security Logger class with thread-safe database operations.
    """
    
    def __init__(self, config_manager: ConfigManager, alert_manager: AlertManager):
        self.config_manager = config_manager
        self.config = config_manager.config
        self.alert_manager = alert_manager
        
        # Thread-safe database
        self.db_path = Path('~/.vigil/security_events.db').expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = ThreadSafeDatabase(str(self.db_path))
        self._init_database()
        
        # Event queue for thread-safe processing
        self.event_queue = queue.Queue()
        
        # Monitoring components
        self.file_monitor = None
        self.auth_monitor = None
        self.process_monitor = None
        
        # Thread management
        self.monitoring_threads = []
        self.event_processor_thread = None
        self._monitoring = False
        self._shutdown_event = threading.Event()
        
        # Event listeners
        self.event_listeners = []
        
        # Start event processor thread
        self._start_event_processor()
        
        logger.info(f"Security Logger initialized with database at {self.db_path}")
    
    def _init_database(self):
        """Initialize SQLite database for security events."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create events table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    user TEXT,
                    source_ip TEXT,
                    file_path TEXT,
                    process_id INTEGER,
                    description TEXT NOT NULL,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create indexes for faster queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON security_events(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_event_type ON security_events(event_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_severity ON security_events(severity)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_user ON security_events(user)')
            
            conn.commit()
    
    def _start_event_processor(self):
        """Start background thread to process events from queue."""
        self.event_processor_thread = threading.Thread(
            target=self._process_event_queue,
            name="SecurityEventProcessor",
            daemon=True
        )
        self.event_processor_thread.start()
    
    def _process_event_queue(self):
        """Process events from the queue (runs in background thread)."""
        while not self._shutdown_event.is_set():
            try:
                event = self.event_queue.get(timeout=1.0)
                if event is None:  # Shutdown signal
                    break
                
                self._add_event_to_database(event)
                self._notify_alert_manager(event)
                self._notify_listeners(event)
                
                self.event_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing security event: {e}")
    
    def _add_event_to_database(self, event: SecurityEvent):
        """Add event to database (called from processor thread)."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO security_events 
                    (timestamp, event_type, severity, user, source_ip, file_path, process_id, description, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    event.timestamp.isoformat(),
                    event.event_type.value,
                    event.severity.value,
                    event.user,
                    event.source_ip,
                    event.file_path,
                    event.process_id,
                    event.description,
                    json.dumps(event.metadata) if event.metadata else None
                ))
                conn.commit()
                event.id = cursor.lastrowid
                
        except Exception as e:
            logger.error(f"Failed to add security event to database: {e}")
    
    def _notify_alert_manager(self, event: SecurityEvent):
        """Notify alert manager about security event."""
        try:
            if self.alert_manager and hasattr(self.alert_manager, 'handle_security_event'):
                self.alert_manager.handle_security_event({
                    'type': event.event_type.value,
                    'message': event.description,
                    'severity': event.severity.value,
                    'timestamp': event.timestamp,
                    'data': {
                        'user': event.user,
                        'source_ip': event.source_ip,
                        'file_path': event.file_path,
                        'process_id': event.process_id,
                        'metadata': event.metadata
                    }
                })
        except Exception as e:
            logger.error(f"Failed to notify alert manager: {e}")
    
    def _notify_listeners(self, event: SecurityEvent):
        """Notify event listeners."""
        for listener in self.event_listeners:
            try:
                listener(event)
            except Exception as e:
                logger.error(f"Error in event listener: {e}")
    
    def add_security_event(self, event: SecurityEvent):
        """Add a security event (thread-safe)."""
        try:
            self.event_queue.put(event)
            logger.debug(f"Security event queued: {event.event_type.value} - {event.description}")
            return True
        except Exception as e:
            logger.error(f"Failed to queue security event: {e}")
            return False
    
    def add_event_listener(self, callback):
        """Add a callback function to be called on new security events."""
        self.event_listeners.append(callback)
    
    def start_monitoring(self) -> bool:
        """Start all monitoring threads."""
        if self._monitoring:
            logger.warning("Security monitoring already started")
            return False
        
        try:
            self._monitoring = True
            self._shutdown_event.clear()
            
            # Start file system monitoring
            if self.config.get('security.file_monitoring.enabled', True):
                self._start_file_monitoring()
            
            # Start authentication log monitoring
            if self.config.get('security.auth_monitoring.enabled', True):
                self._start_auth_monitoring()
            
            # Start process monitoring
            if self.config.get('security.process_monitoring.enabled', True):
                self._start_process_monitoring()
            
            logger.info("Security monitoring started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start security monitoring: {e}")
            self._monitoring = False
            return False
    
    def _start_file_monitoring(self):
        """Start file system monitoring with watchdog."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
            
            class FileMonitorHandler(FileSystemEventHandler):
                def __init__(self, security_logger, config):
                    super().__init__()
                    self.security_logger = security_logger
                    self.config = config
                
                def on_modified(self, event):
                    if not event.is_directory:
                        from .alert_manager import AlertSeverity
                        event_obj = SecurityEvent(
                            event_type=EventType.FILE_MODIFICATION,
                            severity=AlertSeverity.MEDIUM,
                            description=f"File modified: {event.src_path}",
                            file_path=event.src_path
                        )
                        self.security_logger.add_security_event(event_obj)
                
                def on_created(self, event):
                    if not event.is_directory:
                        from .alert_manager import AlertSeverity
                        event_obj = SecurityEvent(
                            event_type=EventType.FILE_CREATION,
                            severity=AlertSeverity.LOW,
                            description=f"File created: {event.src_path}",
                            file_path=event.src_path
                        )
                        self.security_logger.add_security_event(event_obj)
                
                def on_deleted(self, event):
                    if not event.is_directory:
                        from .alert_manager import AlertSeverity
                        event_obj = SecurityEvent(
                            event_type=EventType.FILE_DELETION,
                            severity=AlertSeverity.MEDIUM,
                            description=f"File deleted: {event.src_path}",
                            file_path=event.src_path
                        )
                        self.security_logger.add_security_event(event_obj)
            
            watch_paths = self.config.get('security.sensitive_paths', ['/etc', '/home', '/var/log'])
            
            self.file_monitor = Observer()
            handler = FileMonitorHandler(self, self.config)
            
            for path in watch_paths:
                if os.path.exists(path):
                    self.file_monitor.schedule(handler, path, recursive=True)
                    logger.info(f"Monitoring file system path: {path}")
            
            self.file_monitor.start()
            logger.info("File system monitoring started")
            
        except Exception as e:
            logger.error(f"Failed to start file monitoring: {e}")
    
    def _start_auth_monitoring(self):
        """Start authentication log monitoring."""
        try:
            class AuthMonitor(threading.Thread):
                def __init__(self, security_logger, config):
                    super().__init__()
                    self.security_logger = security_logger
                    self.config = config
                    self._monitoring = True
                    self.daemon = True
                
                def run(self):
                    while self._monitoring:
                        # Simulate auth monitoring
                        time.sleep(5)
            
            self.auth_monitor = AuthMonitor(self, self.config)
            self.auth_monitor._monitoring = True
            self.auth_monitor.start()
            self.monitoring_threads.append(self.auth_monitor)
            
            logger.info("Authentication log monitoring started")
            
        except Exception as e:
            logger.error(f"Failed to start auth monitoring: {e}")
    
    def _start_process_monitoring(self):
        """Start process monitoring."""
        try:
            class ProcessMonitor(threading.Thread):
                def __init__(self, security_logger, config):
                    super().__init__()
                    self.security_logger = security_logger
                    self.config = config
                    self._monitoring = True
                    self.daemon = True
                
                def run(self):
                    while self._monitoring:
                        # Simulate process monitoring
                        time.sleep(5)
            
            self.process_monitor = ProcessMonitor(self, self.config)
            self.process_monitor._monitoring = True
            self.process_monitor.start()
            self.monitoring_threads.append(self.process_monitor)
            
            logger.info("Process monitoring started")
            
        except Exception as e:
            logger.error(f"Failed to start process monitoring: {e}")
    
    def stop_monitoring(self) -> bool:
        """Stop all monitoring gracefully."""
        if not self._monitoring:
            logger.warning("Security monitoring not running")
            return False
        
        try:
            self._monitoring = False
            self._shutdown_event.set()
            
            # Stop file monitor
            if self.file_monitor:
                self.file_monitor.stop()
                self.file_monitor.join()
            
            # Stop monitoring flags
            if self.auth_monitor:
                self.auth_monitor._monitoring = False
            
            if self.process_monitor:
                self.process_monitor._monitoring = False
            
            # Wait for threads
            for thread in self.monitoring_threads:
                if thread.is_alive():
                    thread.join(timeout=5)
            
            # Send shutdown signal to event processor
            self.event_queue.put(None)
            if self.event_processor_thread and self.event_processor_thread.is_alive():
                self.event_processor_thread.join(timeout=5)
            
            # Clean up database connections
            self.db.close_all()
            
            logger.info("Security monitoring stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping security monitoring: {e}")
            return False
    
    def get_recent_events(self, limit: int = 50) -> List[Dict]:
        """Get most recent security events."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM security_events 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                ''', (limit,))
                
                events = []
                for row in cursor.fetchall():
                    event = {
                        'id': row[0],
                        'timestamp': row[1],
                        'event_type': row[2],
                        'severity': row[3],
                        'user': row[4],
                        'source_ip': row[5],
                        'file_path': row[6],
                        'process_id': row[7],
                        'description': row[8],
                        'metadata': json.loads(row[9]) if row[9] else {},
                        'created_at': row[10]
                    }
                    events.append(event)
                
                return events
                
        except Exception as e:
            logger.error(f"Failed to get recent events: {e}")
            return []
    
    def get_recent_events_count(self, hours: int = 1) -> int:
        """Get count of recent events in the last X hours."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM security_events 
                    WHERE timestamp >= datetime('now', ?)
                ''', (f'-{hours} hours',))
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Failed to get recent events count: {e}")
            return 0
    
    def search_events(self, 
                     start_time: Optional[datetime] = None,
                     end_time: Optional[datetime] = None,
                     event_type: Optional[str] = None,
                     user: Optional[str] = None,
                     severity: Optional[str] = None,
                     limit: int = 100) -> List[Dict]:
        """Search for events with filters."""
        try:
            query = "SELECT * FROM security_events WHERE 1=1"
            params = []
            
            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time.isoformat())
            
            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time.isoformat())
            
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            
            if user:
                query += " AND user = ?"
                params.append(user)
            
            if severity:
                query += " AND severity = ?"
                params.append(severity)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                events = []
                for row in cursor.fetchall():
                    event = {
                        'id': row[0],
                        'timestamp': row[1],
                        'event_type': row[2],
                        'severity': row[3],
                        'user': row[4],
                        'source_ip': row[5],
                        'file_path': row[6],
                        'process_id': row[7],
                        'description': row[8],
                        'metadata': json.loads(row[9]) if row[9] else {},
                        'created_at': row[10]
                    }
                    events.append(event)
                
                return events
                
        except Exception as e:
            logger.error(f"Failed to search events: {e}")
            return []
    
    def get_stats(self) -> Dict:
        """Get statistics about monitored events."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                stats = {
                    'total_events': 0,
                    'events_by_type': {},
                    'events_by_severity': {},
                    'recent_activity': [],
                    'top_users': [],
                    'top_source_ips': []
                }
                
                # Total events
                cursor.execute("SELECT COUNT(*) FROM security_events")
                stats['total_events'] = cursor.fetchone()[0]
                
                # Events by type
                cursor.execute("""
                    SELECT event_type, COUNT(*) 
                    FROM security_events 
                    GROUP BY event_type 
                    ORDER BY COUNT(*) DESC
                """)
                for event_type, count in cursor.fetchall():
                    stats['events_by_type'][event_type] = count
                
                # Events by severity
                cursor.execute("""
                    SELECT severity, COUNT(*) 
                    FROM security_events 
                    GROUP BY severity 
                    ORDER BY COUNT(*) DESC
                """)
                for severity, count in cursor.fetchall():
                    stats['events_by_severity'][severity] = count
                
                # Recent activity (last 24 hours)
                cursor.execute("""
                    SELECT event_type, severity, COUNT(*) 
                    FROM security_events 
                    WHERE timestamp >= datetime('now', '-24 hours')
                    GROUP BY event_type, severity
                """)
                for event_type, severity, count in cursor.fetchall():
                    stats['recent_activity'].append({
                        'event_type': event_type,
                        'severity': severity,
                        'count': count
                    })
                
                # Top users
                cursor.execute("""
                    SELECT user, COUNT(*) 
                    FROM security_events 
                    WHERE user IS NOT NULL 
                    GROUP BY user 
                    ORDER BY COUNT(*) DESC 
                    LIMIT 10
                """)
                for user, count in cursor.fetchall():
                    stats['top_users'].append({'user': user, 'count': count})
                
                # Top source IPs
                cursor.execute("""
                    SELECT source_ip, COUNT(*) 
                    FROM security_events 
                    WHERE source_ip IS NOT NULL 
                    GROUP BY source_ip 
                    ORDER BY COUNT(*) DESC 
                    LIMIT 10
                """)
                for ip, count in cursor.fetchall():
                    stats['top_source_ips'].append({'ip': ip, 'count': count})
                
                return stats
                
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}
    
    def __del__(self):
        """Cleanup on destruction."""
        if self._monitoring:
            self.stop_monitoring()