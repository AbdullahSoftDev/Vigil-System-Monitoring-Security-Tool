"""
Alert Manager for VIGIL
Handles alert processing, correlation, and notifications
"""

import threading
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
import collections
import hashlib

# Setup logging
logger = logging.getLogger(__name__)

class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class AlertCategory(Enum):
    """Alert categories"""
    SYSTEM = "system"
    SECURITY = "security"
    NETWORK = "network"
    APPLICATION = "application"
    PERFORMANCE = "performance"
    CORRELATION = "correlation"

class AlertStatus(Enum):
    """Alert status"""
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"

@dataclass
class Alert:
    """Alert data structure"""
    id: str
    type: str
    severity: AlertSeverity
    message: str
    timestamp: datetime
    description: str = ''
    source: str = "system"
    category: AlertCategory = AlertCategory.SYSTEM
    status: AlertStatus = AlertStatus.NEW
    data: Dict[str, Any] = field(default_factory=dict)
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    machine_id: Optional[str] = None
    correlation_id: Optional[str] = None
    count: int = 1
    
    def to_dict(self) -> Dict:
        """Convert alert to dictionary"""
        result = asdict(self)
        result['severity'] = self.severity.value
        result['category'] = self.category.value
        result['status'] = self.status.value
        result['timestamp'] = self.timestamp.isoformat()
        if self.acknowledged_at:
            result['acknowledged_at'] = self.acknowledged_at.isoformat()
        if self.resolved_at:
            result['resolved_at'] = self.resolved_at.isoformat()
        return result

class AlertManager:
    """Main alert management class"""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        
        # Alert storage
        self.alerts: Dict[str, Alert] = {}
        self.alert_history = collections.deque(maxlen=1000)
        
        # Correlation engine
        self.correlation_window = timedelta(minutes=5)
        self.recent_alerts = collections.deque(maxlen=100)
        
        # Notification callbacks
        self.on_alert = []
        self.on_alert_acknowledged = []
        self.on_alert_resolved = []
        
        # Alert suppression
        self.suppression_rules = self._load_suppression_rules()
        self.suppressed_alerts = {}
        
        # Cloud sync reference
        self.cloud_sync = None
        
        # Statistics
        self.stats = {
            'total_alerts': 0,
            'active_alerts': 0,
            'acknowledged_alerts': 0,
            'resolved_alerts': 0,
            'suppressed_alerts': 0,
            'correlated_alerts': 0
        }
        
        # Load configuration
        self._load_config()
        
        logger.info("AlertManager initialized")
    
    def set_cloud_sync(self, cloud_sync):
        """Set cloud sync reference for automatic alert queuing."""
        self.cloud_sync = cloud_sync
        logger.info("Cloud sync reference set in AlertManager")
    
    def _load_config(self):
        """Load configuration"""
        alerts_config = self.config.get('alerts', {})
        self.cpu_threshold = alerts_config.get('cpu_threshold', 80.0)
        self.memory_threshold = alerts_config.get('memory_threshold', 90.0)
        self.disk_threshold = alerts_config.get('disk_threshold', 95.0)
        self.failed_logins_threshold = alerts_config.get('failed_logins_threshold', 5)
        self.network_multiplier = alerts_config.get('network_baseline_multiplier', 2.0)
        self.consecutive_readings = alerts_config.get('consecutive_readings', 3)
        
        # Correlation settings
        self.correlation_enabled = self.config.get('correlation', {}).get('enabled', True)
        self.correlation_window_seconds = self.config.get('correlation', {}).get('window_seconds', 300)
        self.correlation_window = timedelta(seconds=self.correlation_window_seconds)
        
        # Notification settings
        self.notification_config = self.config.get('notifications', {})
    
    def _load_suppression_rules(self) -> List[Dict]:
        """Load alert suppression rules"""
        default_rules = [
            {
                'pattern': '.*test.*',
                'severity': ['info', 'low'],
                'suppress_for_minutes': 5
            },
            {
                'pattern': 'disk.*usage',
                'severity': ['low'],
                'suppress_for_minutes': 15
            }
        ]
        
        config_rules = self.config.get('suppression_rules', [])
        return config_rules if config_rules else default_rules
    
    def start(self):
        """Start the alert manager"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._alert_processing_loop, daemon=True)
        self.thread.start()
        
        logger.info("AlertManager started")
    
    def stop(self):
        """Stop the alert manager"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5.0)
        
        logger.info("AlertManager stopped")
    
    def _alert_processing_loop(self):
        """Background loop for alert processing"""
        while self.running:
            try:
                # Clean up old suppressed alerts
                self._cleanup_suppressed_alerts()
                
                # Check for alert escalation
                self._check_alert_escalation()
                
                # Process correlation
                if self.correlation_enabled:
                    self._process_correlation()
                
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in alert processing loop: {e}")
                time.sleep(5)
    
    def _cleanup_suppressed_alerts(self):
        """Clean up old suppressed alerts"""
        current_time = datetime.now()
        to_remove = []
        
        with self.lock:
            for alert_key, suppression_time in list(self.suppressed_alerts.items()):
                if isinstance(suppression_time, datetime):
                    if current_time - suppression_time > timedelta(minutes=30):
                        to_remove.append(alert_key)
            
            for alert_key in to_remove:
                del self.suppressed_alerts[alert_key]
    
    def _check_alert_escalation(self):
        """Check if alerts need to be escalated"""
        current_time = datetime.now()
        
        with self.lock:
            for alert_id, alert in self.alerts.items():
                if alert.status != AlertStatus.NEW:
                    continue
                
                alert_age = current_time - alert.timestamp
                
                if alert_age > timedelta(minutes=30) and alert.severity == AlertSeverity.MEDIUM:
                    self._escalate_alert(alert_id, AlertSeverity.HIGH)
                elif alert_age > timedelta(hours=1) and alert.severity == AlertSeverity.HIGH:
                    self._escalate_alert(alert_id, AlertSeverity.CRITICAL)
    
    def _escalate_alert(self, alert_id: str, new_severity: AlertSeverity):
        """Escalate an alert to higher severity"""
        with self.lock:
            if alert_id in self.alerts:
                alert = self.alerts[alert_id]
                old_severity = alert.severity
                alert.severity = new_severity
                alert.data['escalated_from'] = old_severity.value
                alert.data['escalated_at'] = datetime.now().isoformat()
                
                logger.warning(f"Alert {alert_id} escalated from {old_severity.value} to {new_severity.value}")
    
    def _process_correlation(self):
        """Process alert correlation"""
        current_time = datetime.now()
        window_start = current_time - self.correlation_window
        
        alerts_by_type = collections.defaultdict(list)
        
        with self.lock:
            for alert in list(self.alerts.values()):
                if alert.timestamp >= window_start and alert.status == AlertStatus.NEW:
                    alerts_by_type[(alert.type, alert.source)].append(alert)
        
        for (alert_type, source), alerts in alerts_by_type.items():
            if len(alerts) >= 3:
                self._create_correlated_alert(alerts, alert_type, source)
    
    def _create_correlated_alert(self, alerts: List[Alert], alert_type: str, source: str):
        """Create a correlated alert from multiple alerts"""
        if not alerts:
            return
        
        correlation_id = hashlib.md5(
            f"{alert_type}_{source}_{alerts[0].timestamp.timestamp()}".encode()
        ).hexdigest()[:16]
        
        with self.lock:
            for alert in self.alerts.values():
                if alert.correlation_id == correlation_id:
                    return
        
        message = f"Multiple {alert_type} alerts detected from {source} ({len(alerts)} occurrences)"
        
        severities = [alert.severity for alert in alerts]
        highest_severity = max(severities, key=lambda s: s.value)
        
        alert_data = {
            'original_alerts': [alert.id for alert in alerts],
            'occurrences': len(alerts),
            'first_occurrence': min(alert.timestamp for alert in alerts).isoformat(),
            'last_occurrence': max(alert.timestamp for alert in alerts).isoformat(),
            'alert_types': list(set(alert.type for alert in alerts))
        }
        
        correlated_alert = Alert(
            id=f"corr_{correlation_id}",
            type=f"correlated_{alert_type}",
            severity=highest_severity,
            message=message,
            timestamp=datetime.now(),
            source=source,
            data=alert_data,
            correlation_id=correlation_id,
            count=len(alerts)
        )
        
        self._add_alert_internal(correlated_alert)
        
        for alert in alerts:
            alert.correlation_id = correlation_id
            alert.data['correlated_in'] = correlated_alert.id
        
        self.stats['correlated_alerts'] += 1
        logger.info(f"Created correlated alert: {message}")
    
    def _add_alert_internal(self, alert: Alert):
        """Internal method to add an alert"""
        with self.lock:
            self.alerts[alert.id] = alert
            self.alert_history.append(alert.to_dict())
            self.recent_alerts.append(alert)
            
            self.stats['total_alerts'] += 1
            self.stats['active_alerts'] += 1
            
            self._queue_to_cloud_sync(alert)
            
            logger.info(f"New alert: {alert.severity.value} - {alert.message}")
    
    def _queue_to_cloud_sync(self, alert: Alert):
        """Queue alert to cloud sync if available"""
        if self.cloud_sync and hasattr(self.cloud_sync, 'queue_alert'):
            try:
                alert_data = {
                    'timestamp': alert.timestamp,
                    'source': alert.source,
                    'severity': alert.severity.value,
                    'title': alert.type,
                    'description': alert.message,
                    'acknowledged': alert.status == AlertStatus.ACKNOWLEDGED,
                    'evidence': alert.data,
                    'recommendations': []
                }
                self.cloud_sync.queue_alert(alert_data)
                logger.debug(f"Alert queued to cloud sync: {alert.id}")
            except Exception as e:
                logger.error(f"Failed to queue alert to cloud sync: {e}")
    
    def handle_system_alert(self, alert_data: Dict):
        """Handle system alerts from SystemMonitor"""
        try:
            alert_type = alert_data.get('type', 'system')
            message = alert_data.get('message', 'Unknown system alert')
            severity_str = alert_data.get('severity', 'medium').lower()
            
            severity_map = {
                'info': AlertSeverity.INFO,
                'low': AlertSeverity.LOW,
                'medium': AlertSeverity.MEDIUM,
                'high': AlertSeverity.HIGH,
                'critical': AlertSeverity.CRITICAL
            }
            
            severity = severity_map.get(severity_str, AlertSeverity.MEDIUM)
            
            alert = Alert(
                id=self._generate_alert_id(alert_type, message),
                type=alert_type,
                severity=severity,
                message=message,
                timestamp=alert_data.get('timestamp', datetime.now()),
                source='system_monitor',
                data=alert_data.get('data', {})
            )
            
            self.add_alert(alert)
            
        except Exception as e:
            logger.error(f"Error handling system alert: {e}")
    
    def handle_security_event(self, event_data: Dict):
        """Handle security events from SecurityLogger"""
        try:
            event_type = event_data.get('type', 'security')
            message = event_data.get('message', 'Unknown security event')
            severity_str = event_data.get('severity', 'medium').lower()
            
            severity_map = {
                'info': AlertSeverity.INFO,
                'low': AlertSeverity.LOW,
                'medium': AlertSeverity.MEDIUM,
                'high': AlertSeverity.HIGH,
                'critical': AlertSeverity.CRITICAL
            }
            
            severity = severity_map.get(severity_str, AlertSeverity.MEDIUM)
            
            alert = Alert(
                id=self._generate_alert_id(event_type, message),
                type=event_type,
                severity=severity,
                message=message,
                timestamp=event_data.get('timestamp', datetime.now()),
                source='security_logger',
                data=event_data.get('data', {})
            )
            
            self.add_alert(alert)
            
        except Exception as e:
            logger.error(f"Error handling security event: {e}")
    
    def add_alert(self, alert: Alert):
        """Add a new alert"""
        if self._should_suppress_alert(alert):
            logger.debug(f"Alert suppressed: {alert.message}")
            self.stats['suppressed_alerts'] += 1
            return
        
        duplicate_alert = self._find_duplicate_alert(alert)
        if duplicate_alert:
            self._update_duplicate_alert(duplicate_alert, alert)
            return
        
        self._add_alert_internal(alert)
        
        for callback in self.on_alert:
            try:
                callback(alert.to_dict())
            except Exception as e:
                logger.error(f"Error in alert callback: {e}")
    
    def _should_suppress_alert(self, alert: Alert) -> bool:
        """Check if alert should be suppressed"""
        for rule in self.suppression_rules:
            import re
            
            pattern = rule.get('pattern', '')
            if pattern and re.match(pattern, alert.message):
                allowed_severities = rule.get('severity', [])
                if alert.severity.value in allowed_severities:
                    return True
        
        alert_key = f"{alert.type}:{alert.message}"
        if alert_key in self.suppressed_alerts:
            return True
        
        return False
    
    def _find_duplicate_alert(self, alert: Alert) -> Optional[Alert]:
        """Find duplicate alert in recent alerts"""
        current_time = datetime.now()
        window_start = current_time - timedelta(minutes=5)
        
        with self.lock:
            for existing_alert in self.recent_alerts:
                if existing_alert.timestamp < window_start:
                    continue
                
                if (existing_alert.type == alert.type and 
                    existing_alert.message == alert.message and
                    existing_alert.source == alert.source and
                    existing_alert.severity == alert.severity):
                    return existing_alert
        
        return None
    
    def _update_duplicate_alert(self, existing_alert: Alert, new_alert: Alert):
        """Update duplicate alert count"""
        with self.lock:
            existing_alert.count += 1
            existing_alert.data['last_duplicate'] = new_alert.timestamp.isoformat()
            existing_alert.data['duplicate_count'] = existing_alert.count
            
            logger.debug(f"Duplicate alert updated: {existing_alert.message} (count: {existing_alert.count})")
    
    def _generate_alert_id(self, alert_type: str, message: str) -> str:
        """Generate unique alert ID"""
        timestamp = datetime.now().isoformat()
        id_string = f"{alert_type}:{message}:{timestamp}"
        return hashlib.md5(id_string.encode()).hexdigest()[:16]
    
    def acknowledge_alert(self, alert_id: str, acknowledged_by: str = "user"):
        """Acknowledge an alert"""
        with self.lock:
            if alert_id in self.alerts:
                alert = self.alerts[alert_id]
                if alert.status == AlertStatus.NEW:
                    alert.status = AlertStatus.ACKNOWLEDGED
                    alert.acknowledged_at = datetime.now()
                    alert.data['acknowledged_by'] = acknowledged_by
                    
                    self.stats['active_alerts'] -= 1
                    self.stats['acknowledged_alerts'] += 1
                    
                    for callback in self.on_alert_acknowledged:
                        try:
                            callback(alert.to_dict())
                        except Exception as e:
                            logger.error(f"Error in acknowledgement callback: {e}")
                    
                    logger.info(f"Alert acknowledged: {alert_id}")
                    return True
        
        return False
    
    def resolve_alert(self, alert_id: str, resolution_notes: str = "", resolved_by: str = "user"):
        """Resolve an alert"""
        with self.lock:
            if alert_id in self.alerts:
                alert = self.alerts[alert_id]
                alert.status = AlertStatus.RESOLVED
                alert.resolved_at = datetime.now()
                alert.data['resolution_notes'] = resolution_notes
                alert.data['resolved_by'] = resolved_by
                
                if alert.status == AlertStatus.NEW:
                    self.stats['active_alerts'] -= 1
                elif alert.status == AlertStatus.ACKNOWLEDGED:
                    self.stats['acknowledged_alerts'] -= 1
                
                self.stats['resolved_alerts'] += 1
                
                for callback in self.on_alert_resolved:
                    try:
                        callback(alert.to_dict())
                    except Exception as e:
                        logger.error(f"Error in resolution callback: {e}")
                
                logger.info(f"Alert resolved: {alert_id}")
                return True
        
        return False
    
    def suppress_alert(self, alert_id: str, suppress_for_minutes: int = 30):
        """Suppress an alert"""
        with self.lock:
            if alert_id in self.alerts:
                alert = self.alerts[alert_id]
                alert.status = AlertStatus.SUPPRESSED
                
                alert_key = f"{alert.type}:{alert.message}"
                self.suppressed_alerts[alert_key] = datetime.now()
                
                if alert.status == AlertStatus.NEW:
                    self.stats['active_alerts'] -= 1
                self.stats['suppressed_alerts'] += 1
                
                logger.info(f"Alert suppressed: {alert_id} for {suppress_for_minutes} minutes")
                return True
        
        return False
    
    def get_alerts(self, status: Optional[str] = None, severity: Optional[str] = None, 
                   limit: int = 100) -> List[Dict]:
        """Get alerts with optional filtering"""
        result = []
        
        with self.lock:
            for alert in self.alerts.values():
                if status and alert.status.value != status:
                    continue
                if severity and alert.severity.value != severity:
                    continue
                
                result.append(alert.to_dict())
                
                if len(result) >= limit:
                    break
        
        return result
    
    def get_alert(self, alert_id: str) -> Optional[Alert]:
        """Get a specific alert by ID"""
        with self.lock:
            if alert_id in self.alerts:
                return self.alerts[alert_id]
        return None
    
    def get_alert_history(self, limit: int = 100) -> List[Dict]:
        """Get alert history"""
        with self.lock:
            return list(self.alert_history)[-limit:]
    
    def get_stats(self) -> Dict:
        """Get alert statistics"""
        with self.lock:
            stats = self.stats.copy()
            stats['alerts_by_severity'] = self._get_alerts_by_severity()
            stats['alerts_by_status'] = self._get_alerts_by_status()
            stats['alerts_by_type'] = self._get_alerts_by_type()
            return stats
    
    def _get_alerts_by_severity(self) -> Dict:
        """Get alert count by severity"""
        counts = collections.defaultdict(int)
        
        with self.lock:
            for alert in self.alerts.values():
                counts[alert.severity.value] += 1
        
        return dict(counts)
    
    def _get_alerts_by_status(self) -> Dict:
        """Get alert count by status"""
        counts = collections.defaultdict(int)
        
        with self.lock:
            for alert in self.alerts.values():
                counts[alert.status.value] += 1
        
        return dict(counts)
    
    def _get_alerts_by_type(self) -> Dict:
        """Get alert count by type"""
        counts = collections.defaultdict(int)
        
        with self.lock:
            for alert in self.alerts.values():
                counts[alert.type] += 1
        
        return dict(counts)
    
    def clear_alerts(self, status: Optional[str] = None):
        """Clear alerts (with optional status filter)"""
        with self.lock:
            if status:
                to_remove = []
                for alert_id, alert in self.alerts.items():
                    if alert.status.value == status:
                        to_remove.append(alert_id)
                
                for alert_id in to_remove:
                    del self.alerts[alert_id]
                
                logger.info(f"Cleared {len(to_remove)} alerts with status: {status}")
            else:
                count = len(self.alerts)
                self.alerts.clear()
                logger.info(f"Cleared all {count} alerts")
    
    def register_alert_callback(self, callback: Callable):
        """Register callback for new alerts"""
        if callback not in self.on_alert:
            self.on_alert.append(callback)
    
    def register_acknowledgement_callback(self, callback: Callable):
        """Register callback for acknowledged alerts"""
        if callback not in self.on_alert_acknowledged:
            self.on_alert_acknowledged.append(callback)
    
    def register_resolution_callback(self, callback: Callable):
        """Register callback for resolved alerts"""
        if callback not in self.on_alert_resolved:
            self.on_alert_resolved.append(callback)
    
    def get_recent_alerts(self, limit: int = 50):
        """Get recent alerts for dashboard compatibility."""
        with self.lock:
            alerts = list(self.alerts.values())
            sorted_alerts = sorted(alerts, key=lambda x: x.timestamp, reverse=True)
            return sorted_alerts[:limit]
    
    def create_test_alert(self):
        """Create a test alert for debugging."""
        import time
        test_alert = Alert(
            id="test_" + str(int(time.time())),
            type="test",
            severity=AlertSeverity.INFO,
            message="This is a test alert",
            timestamp=datetime.now(),
            description="Test alert to verify dashboard is working",
            source="System Test",
            category=AlertCategory.SYSTEM
        )
        self.add_alert(test_alert)
        logger.info("Created test alert with ID: %s", test_alert.id)
        return test_alert.id