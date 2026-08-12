"""
Cloud Sync Manager - Supabase cloud synchronization.
"""
import os
import sys
import json
import time
import uuid
import gzip
import sqlite3
import threading
import queue
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from pathlib import Path
from enum import Enum
import logging

# Third-party imports
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

# Local imports
from .alert_manager import AlertManager, AlertSeverity, AlertCategory
from .config_manager import ConfigManager
from .encryption import EncryptionManager

# Setup logging
logger = logging.getLogger(__name__)

class PrivacyLevel(Enum):
    """Privacy levels for cloud sync."""
    FULL_PRIVACY = "full_privacy"      # Nothing to cloud
    METRICS_ONLY = "metrics_only"      # Only system metrics
    ALERTS_ONLY = "alerts_only"        # Only security alerts
    FULL_SYNC = "full_sync"            # Everything (with encryption)

class SyncStatus(Enum):
    """Cloud sync status."""
    OFFLINE = "offline"
    CONNECTING = "connecting"
    ONLINE = "online"
    SYNCING = "syncing"
    ERROR = "error"

class SyncItem:
    """Represents an item to sync to cloud."""
    
    def __init__(self, 
                 table: str,
                 data: Dict,
                 id_field: str = "id",
                 timestamp_field: str = "created_at"):
        self.table = table
        self.data = data
        self.id_field = id_field
        self.timestamp_field = timestamp_field
        self.created_at = datetime.now()
        self.attempts = 0
        self.last_attempt = None
        self.error = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        return {
            'table': self.table,
            'data': self.data,
            'id_field': self.id_field,
            'timestamp_field': self.timestamp_field,
            'created_at': self.created_at.isoformat(),
            'attempts': self.attempts,
            'last_attempt': self.last_attempt.isoformat() if self.last_attempt else None,
            'error': self.error
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SyncItem':
        """Create from dictionary."""
        item = cls(
            table=data['table'],
            data=data['data'],
            id_field=data.get('id_field', 'id'),
            timestamp_field=data.get('timestamp_field', 'created_at')
        )
        item.created_at = datetime.fromisoformat(data['created_at']) if data['created_at'] else datetime.now()
        item.attempts = data.get('attempts', 0)
        if data.get('last_attempt'):
            item.last_attempt = datetime.fromisoformat(data['last_attempt'])
        item.error = data.get('error')
        return item

class CloudSync:
    """
    Manages synchronization with Supabase cloud storage.
    """
    
    # Max sync items per batch
    MAX_BATCH_SIZE = 100
    
    # Retry configuration
    MAX_RETRY_ATTEMPTS = 3
    RETRY_DELAYS = [5, 30, 300]  # seconds
    
    # API timeout (seconds)
    REQUEST_TIMEOUT = 30
    
    def __init__(self, config_manager: ConfigManager, alert_manager: AlertManager):
        self.config_manager = config_manager
        self.config = config_manager.config
        self.alert_manager = alert_manager
        self.encryption_manager = EncryptionManager(config_manager)
        
        # Supabase configuration
        self.supabase_config = self.config.get('cloud.supabase', {})
        self.supabase_url = self.supabase_config.get('url', '').rstrip('/')
        self.service_key = self.supabase_config.get('service_key', '')
        self.enabled = self.supabase_config.get('enabled', False)
        
        # Privacy settings
        privacy_config = self.config.get('cloud.privacy', {})
        self.privacy_level = PrivacyLevel(privacy_config.get('level', 'metrics_only'))
        self.anonymize = privacy_config.get('anonymize', True)
        self.encrypt_sensitive = privacy_config.get('encrypt_sensitive', True)
        
        # Sync settings
        sync_config = self.config.get('cloud.sync', {})
        self.sync_interval = sync_config.get('interval', 30)  # seconds
        self.batch_size = sync_config.get('batch_size', 100)
        self.retry_attempts = sync_config.get('retry_attempts', 3)
        
        # Machine identification
        machine_config = self.config.get('cloud.machine', {})
        self.machine_name = machine_config.get('name', self._generate_machine_name())
        self.machine_id = machine_config.get('id', self._generate_machine_id())
        self.machine_group = machine_config.get('group', 'default')
        
        # State
        self.status = SyncStatus.OFFLINE
        self.last_sync = None
        self.sync_stats = {
            'sent': 0,
            'received': 0,
            'failed': 0,
            'last_success': None
        }
        
        # Queues
        self.sync_queue = queue.Queue()
        self.retry_queue = []
        
        # Database
        self.db_path = Path('~/.vigil/cloud_queue.db').expanduser()
        self.db_conn = None
        self._init_database()
        
        # Thread management
        self.sync_thread = None
        self._running = False
        
        # Request session
        self.session = requests.Session()
        self.session.headers.update({
            'apikey': self.service_key,
            'Authorization': f'Bearer {self.service_key}',
            'Content-Type': 'application/json',
            'Prefer': 'return=minimal'
        })
        
        # Connection health
        self.last_health_check = None
        self.connection_errors = 0
        self.max_connection_errors = 5
        
        logger.info(f"Cloud Sync Manager initialized (Privacy: {self.privacy_level.value})")
    
    def _generate_machine_id(self) -> str:
        """Generate unique machine ID."""
        # Try to get machine-specific ID
        try:
            import hashlib
            import platform
            import socket
            
            # Create hash from machine identifiers
            identifiers = [
                platform.node(),  # Hostname
                socket.gethostname(),
                str(os.getpid()),
                str(datetime.now().timestamp())
            ]
            
            identifier_string = ''.join(identifiers)
            machine_hash = hashlib.sha256(identifier_string.encode()).hexdigest()[:16]
            return f"machine_{machine_hash}"
            
        except:
            # Fallback to UUID
            return f"machine_{uuid.uuid4().hex[:16]}"
    
    def _generate_machine_name(self) -> str:
        """Generate friendly machine name."""
        import platform
        import socket
        
        try:
            hostname = platform.node() or socket.gethostname()
            return f"{hostname}-vigil"
        except:
            return f"vigil-{uuid.uuid4().hex[:8]}"
    
    def _init_database(self):
        """Initialize SQLite database for sync queue."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            self.db_conn = sqlite3.connect(self.db_path)
            cursor = self.db_conn.cursor()
            
            # Create sync queue table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    table_name TEXT NOT NULL,
                    data TEXT NOT NULL,
                    id_field TEXT DEFAULT 'id',
                    timestamp_field TEXT DEFAULT 'created_at',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    attempts INTEGER DEFAULT 0,
                    last_attempt TIMESTAMP,
                    error TEXT,
                    priority INTEGER DEFAULT 0
                )
            ''')
            
            # Create sync history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    operation TEXT NOT NULL,
                    table_name TEXT,
                    items_count INTEGER,
                    success BOOLEAN,
                    error TEXT,
                    duration REAL
                )
            ''')
            
            # Create machine info table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS machine_info (
                    id INTEGER PRIMARY KEY,
                    machine_id TEXT UNIQUE NOT NULL,
                    machine_name TEXT,
                    machine_group TEXT,
                    last_seen TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_queue_priority ON sync_queue(priority)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_queue_attempts ON sync_queue(attempts)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_timestamp ON sync_history(timestamp)')
            
            self.db_conn.commit()
            logger.info(f"Cloud sync database initialized at {self.db_path}")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            self.db_conn = sqlite3.connect(':memory:')
    
    def _load_queue_from_db(self):
        """Load pending sync items from database."""
        try:
            cursor = self.db_conn.cursor()
            cursor.execute('''
                SELECT * FROM sync_queue 
                WHERE attempts < ? 
                ORDER BY priority DESC, created_at ASC
                LIMIT 1000
            ''', (self.MAX_RETRY_ATTEMPTS,))
            
            for row in cursor.fetchall():
                item = SyncItem(
                    table=row[1],
                    data=json.loads(row[2]),
                    id_field=row[3] or 'id',
                    timestamp_field=row[4] or 'created_at'
                )
                item.created_at = datetime.fromisoformat(row[5]) if row[5] else datetime.now()
                item.attempts = row[6] or 0
                if row[7]:
                    item.last_attempt = datetime.fromisoformat(row[7])
                item.error = row[8]
                
                # Add to retry queue
                self.retry_queue.append(item)
            
            logger.info(f"Loaded {len(self.retry_queue)} items from sync queue")
            
        except Exception as e:
            logger.error(f"Failed to load queue from database: {e}")
    
    def _save_to_queue(self, item: SyncItem):
        """Save sync item to database queue."""
        try:
            cursor = self.db_conn.cursor()
            cursor.execute('''
                INSERT INTO sync_queue 
                (table_name, data, id_field, timestamp_field, created_at, attempts, last_attempt, error, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                item.table,
                json.dumps(item.data),
                item.id_field,
                item.timestamp_field,
                item.created_at.isoformat(),
                item.attempts,
                item.last_attempt.isoformat() if item.last_attempt else None,
                item.error,
                0  # Default priority
            ))
            
            self.db_conn.commit()
            item_id = cursor.lastrowid
            
            # Also add to memory queue for immediate processing
            self.sync_queue.put(item)
            
            logger.debug(f"Saved sync item to queue: {item.table} (ID: {item_id})")
            return item_id
            
        except Exception as e:
            logger.error(f"Failed to save to queue: {e}")
            return None
    
    def _update_queue_item(self, item_id: int, item: SyncItem):
        """Update sync item in database."""
        try:
            cursor = self.db_conn.cursor()
            cursor.execute('''
                UPDATE sync_queue 
                SET attempts = ?, last_attempt = ?, error = ?
                WHERE id = ?
            ''', (
                item.attempts,
                item.last_attempt.isoformat() if item.last_attempt else None,
                item.error,
                item_id
            ))
            self.db_conn.commit()
            
        except Exception as e:
            logger.error(f"Failed to update queue item: {e}")
    
    def _remove_from_queue(self, item_id: int):
        """Remove sync item from database."""
        try:
            cursor = self.db_conn.cursor()
            cursor.execute('DELETE FROM sync_queue WHERE id = ?', (item_id,))
            self.db_conn.commit()
            
        except Exception as e:
            logger.error(f"Failed to remove from queue: {e}")
    
    def _log_sync_history(self, operation: str, table_name: Optional[str], 
                         items_count: int, success: bool, error: Optional[str] = None,
                         duration: Optional[float] = None):
        """Log sync operation to history."""
        try:
            cursor = self.db_conn.cursor()
            cursor.execute('''
                INSERT INTO sync_history 
                (timestamp, operation, table_name, items_count, success, error, duration)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                operation,
                table_name,
                items_count,
                success,
                error,
                duration
            ))
            self.db_conn.commit()
            
        except Exception as e:
            logger.error(f"Failed to log sync history: {e}")
    
    def _check_connection(self) -> bool:
        """Check if Supabase connection is available."""
        if not self.enabled or not self.supabase_url or not self.service_key:
            self.status = SyncStatus.OFFLINE
            return False
        
        # Don't check too frequently
        current_time = time.time()
        if (self.last_health_check and 
            current_time - self.last_health_check < 30):  # 30 seconds cooldown
            return self.status == SyncStatus.ONLINE
        
        try:
            # Simple ping to Supabase
            response = self.session.get(
                f"{self.supabase_url}/rest/v1/",
                timeout=10
            )
            
            if response.status_code == 200:
                self.status = SyncStatus.ONLINE
                self.connection_errors = 0
                self.last_health_check = current_time
                return True
            else:
                self.status = SyncStatus.ERROR
                logger.warning(f"Supabase connection check failed: {response.status_code}")
                return False
                
        except (RequestException, Timeout, ConnectionError) as e:
            self.status = SyncStatus.OFFLINE
            self.connection_errors += 1
            self.last_health_check = current_time
            
            if self.connection_errors >= self.max_connection_errors:
                logger.error(f"Multiple connection errors: {e}")
                if self.alert_manager:
                    self.alert_manager.add_alert(
                        source="CloudSync",
                        severity=AlertSeverity.WARNING,
                        category=AlertCategory.SYSTEM,
                        title="Cloud Sync Connection Failed",
                        description=f"Unable to connect to Supabase: {str(e)[:100]}",
                        recommendations=["Check internet connection", "Verify Supabase credentials"]
                    )
            
            return False
    
    def _apply_privacy_filter(self, data: Dict, table: str) -> Dict:
        """Apply privacy filters to data based on privacy level."""
        if self.privacy_level == PrivacyLevel.FULL_PRIVACY:
            return {}  # Empty data for full privacy
        
        filtered_data = data.copy()
        
        if self.privacy_level == PrivacyLevel.METRICS_ONLY:
            # Only allow system metrics
            if table not in ['system_metrics', 'machine_status']:
                return {}
            
            # Remove any potentially sensitive fields
            sensitive_fields = ['username', 'file_path', 'source_ip', 'command', 'process_name']
            for field in sensitive_fields:
                if field in filtered_data:
                    del filtered_data[field]
        
        elif self.privacy_level == PrivacyLevel.ALERTS_ONLY:
            # Only allow alerts
            if table not in ['alerts', 'security_events']:
                return {}
            
            # Anonymize sensitive fields
            if self.anonymize:
                anonymize_fields = ['user', 'source_ip', 'file_path']
                for field in anonymize_fields:
                    if field in filtered_data and filtered_data[field]:
                        import hashlib
                        value = filtered_data[field]
                        hashed = hashlib.sha256(value.encode()).hexdigest()[:8]
                        filtered_data[field] = f"anon_{hashed}"
        
        # Encrypt sensitive fields if enabled
        if self.encrypt_sensitive and self.encryption_manager:
            encrypt_fields = {
                'system_metrics': [],
                'security_events': ['user', 'source_ip', 'file_path', 'description'],
                'alerts': ['title', 'description', 'evidence', 'recommendations']
            }
            
            fields_to_encrypt = encrypt_fields.get(table, [])
            for field in fields_to_encrypt:
                if field in filtered_data and filtered_data[field]:
                    try:
                        encrypted = self.encryption_manager.encrypt(filtered_data[field])
                        filtered_data[f"{field}_encrypted"] = encrypted
                        filtered_data[field] = "[ENCRYPTED]"  # Replace with placeholder
                    except Exception as e:
                        logger.warning(f"Failed to encrypt field {field}: {e}")
        
        # Add machine identifier (always included)
        filtered_data['machine_id'] = self.machine_id
        filtered_data['machine_name'] = self.machine_name if not self.anonymize else "anonymous"
        
        return filtered_data
    
    def _compress_data(self, data: List[Dict]) -> bytes:
        """Compress data for transmission."""
        try:
            json_data = json.dumps(data).encode('utf-8')
            compressed = gzip.compress(json_data)
            return compressed
        except Exception as e:
            logger.error(f"Failed to compress data: {e}")
            return json.dumps(data).encode('utf-8')
    
    def _upload_batch(self, table: str, items: List[SyncItem]) -> Tuple[int, int]:
        """Upload a batch of items to Supabase."""
        if not items:
            return 0, 0
        
        success_count = 0
        error_count = 0
        
        try:
            # Prepare data for upload
            upload_data = []
            for item in items:
                filtered_data = self._apply_privacy_filter(item.data, table)
                if filtered_data:  # Only upload if data passed privacy filter
                    upload_data.append(filtered_data)
            
            if not upload_data:
                logger.debug(f"No data to upload for {table} (privacy filter)")
                return 0, 0
            
            # Compress data
            compressed_data = self._compress_data(upload_data)
            
            # Upload to Supabase
            headers = {
                'Content-Encoding': 'gzip',
                'Content-Type': 'application/json',
                'Prefer': 'return=minimal'
            }
            
            response = self.session.post(
                f"{self.supabase_url}/rest/v1/{table}",
                data=compressed_data,
                headers=headers,
                timeout=self.REQUEST_TIMEOUT
            )
            
            if response.status_code in [200, 201]:
                success_count = len(upload_data)
                logger.info(f"Uploaded {success_count} items to {table}")
                
                # Log success
                self._log_sync_history(
                    operation="upload",
                    table_name=table,
                    items_count=success_count,
                    success=True,
                    duration=None
                )
                
            else:
                error_count = len(items)
                error_msg = f"Upload failed: {response.status_code} - {response.text[:200]}"
                logger.error(error_msg)
                
                # Log failure
                self._log_sync_history(
                    operation="upload",
                    table_name=table,
                    items_count=error_count,
                    success=False,
                    error=error_msg
                )
                
                # Update error for all items
                for item in items:
                    item.attempts += 1
                    item.last_attempt = datetime.now()
                    item.error = error_msg
            
        except Exception as e:
            error_count = len(items)
            error_msg = f"Upload exception: {str(e)}"
            logger.error(error_msg)
            
            # Log failure
            self._log_sync_history(
                operation="upload",
                table_name=table,
                items_count=error_count,
                success=False,
                error=error_msg
            )
            
            # Update error for all items
            for item in items:
                item.attempts += 1
                item.last_attempt = datetime.now()
                item.error = error_msg
        
        return success_count, error_count
    
    def _sync_machine_status(self):
        """Sync machine status/heartbeat to cloud."""
        if not self._check_connection():
            return False
        
        try:
            machine_data = {
                'machine_id': self.machine_id,
                'machine_name': self.machine_name,
                'machine_group': self.machine_group,
                'last_seen': datetime.now().isoformat(),
                'status': self.status.value,
                'version': '1.0.0',  # TODO: Get actual version
                'platform': sys.platform,
                'python_version': sys.version
            }
            
            # Check if machine already exists
            response = self.session.get(
                f"{self.supabase_url}/rest/v1/machines",
                params={'machine_id': f'eq.{self.machine_id}'},
                timeout=10
            )
            
            if response.status_code == 200:
                existing = response.json()
                if existing:
                    # Update existing
                    response = self.session.patch(
                        f"{self.supabase_url}/rest/v1/machines",
                        params={'machine_id': f'eq.{self.machine_id}'},
                        json=machine_data,
                        timeout=10
                    )
                else:
                    # Insert new
                    response = self.session.post(
                        f"{self.supabase_url}/rest/v1/machines",
                        json=machine_data,
                        timeout=10
                    )
                
                if response.status_code in [200, 201, 204]:
                    logger.debug(f"Machine status synced: {self.machine_id}")
                    return True
                else:
                    logger.warning(f"Failed to sync machine status: {response.status_code}")
                    return False
            
        except Exception as e:
            logger.error(f"Error syncing machine status: {e}")
            return False
    
    def _process_sync_queue(self):
        """Process items from sync queue."""
        if not self._check_connection():
            return
        
        start_time = time.time()
        processed_count = 0
        success_count = 0
        error_count = 0
        
        try:
            # Group items by table for batch processing
            items_by_table = {}
            
            # Get items from both queues
            all_items = []
            
            # Get from memory queue
            while not self.sync_queue.empty():
                try:
                    item = self.sync_queue.get_nowait()
                    all_items.append(item)
                except queue.Empty:
                    break
            
            # Add from retry queue
            all_items.extend(self.retry_queue)
            self.retry_queue = []  # Clear retry queue
            
            if not all_items:
                return
            
            # Group by table
            for item in all_items:
                if item.table not in items_by_table:
                    items_by_table[item.table] = []
                items_by_table[item.table].append(item)
            
            # Process each table
            for table, items in items_by_table.items():
                # Process in batches
                for i in range(0, len(items), self.batch_size):
                    batch = items[i:i + self.batch_size]
                    
                    # Upload batch
                    success, errors = self._upload_batch(table, batch)
                    success_count += success
                    error_count += errors
                    processed_count += len(batch)
                    
                    # Update queue based on results
                    for item in batch:
                        item_id = None  # We'd need to track IDs in real implementation
                        
                        if success > 0:
                            # Successful upload, remove from queue
                            if item_id:
                                self._remove_from_queue(item_id)
                        else:
                            # Failed upload, add to retry queue
                            if item.attempts < self.MAX_RETRY_ATTEMPTS:
                                self.retry_queue.append(item)
                                if item_id:
                                    self._update_queue_item(item_id, item)
                            else:
                                # Max retries reached, remove from queue
                                logger.warning(f"Max retries reached for item: {item.table}")
                                if item_id:
                                    self._remove_from_queue(item_id)
                    
                    # Don't overwhelm the API
                    time.sleep(0.1)
            
            # Sync machine status
            self._sync_machine_status()
            
            # Update stats
            self.last_sync = datetime.now()
            self.sync_stats['sent'] += success_count
            self.sync_stats['failed'] += error_count
            self.sync_stats['last_success'] = self.last_sync if success_count > 0 else None
            
            duration = time.time() - start_time
            logger.info(f"Sync completed: {success_count} sent, {error_count} failed in {duration:.2f}s")
            
        except Exception as e:
            logger.error(f"Error processing sync queue: {e}")
    
    def _sync_loop(self):
        """Main sync loop running in background thread."""
        logger.info("Cloud sync thread started")
        
        while self._running:
            try:
                # Check if sync is enabled
                if not self.enabled:
                    time.sleep(self.sync_interval)
                    continue
                
                # Process sync queue
                self._process_sync_queue()
                
                # Sleep until next sync
                time.sleep(self.sync_interval)
                
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")
                time.sleep(60)  # Wait longer on error
        
        logger.info("Cloud sync thread stopped")
    
    def start(self):
        """Start cloud sync manager."""
        if self._running:
            logger.warning("Cloud sync already started")
            return False
        
        if not self.enabled:
            logger.info("Cloud sync disabled in config")
            return False
        
        if not self.supabase_url or not self.service_key:
            logger.error("Supabase URL or service key not configured")
            return False
        
        try:
            self._running = True
            
            # Load existing queue
            self._load_queue_from_db()
            
            # Start sync thread
            self.sync_thread = threading.Thread(
                target=self._sync_loop,
                name="CloudSyncThread",
                daemon=True
            )
            self.sync_thread.start()
            
            logger.info("Cloud sync manager started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start cloud sync: {e}")
            self._running = False
            return False
    
    def stop(self):
        """Stop cloud sync manager."""
        self._running = False
        
        if self.sync_thread and self.sync_thread.is_alive():
            self.sync_thread.join(timeout=5)
        
        # Close database connection
        if self.db_conn:
            try:
                self.db_conn.close()
            except:
                pass
        
        logger.info("Cloud sync manager stopped")
        return True
    
    def sync_now(self) -> Dict:
        """Trigger immediate synchronization."""
        if not self._running:
            return {'error': 'Cloud sync not running'}
        
        start_time = time.time()
        
        try:
            # Process queue immediately
            self._process_sync_queue()
            
            duration = time.time() - start_time
            
            stats = {
                'sent': self.sync_stats['sent'],
                'received': self.sync_stats['received'],
                'failed': self.sync_stats['failed'],
                'duration': duration,
                'queue_size': self.get_queue_size(),
                'status': 'success' if self.sync_stats['failed'] == 0 else 'partial'
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Manual sync failed: {e}")
            return {
                'error': str(e),
                'duration': time.time() - start_time,
                'status': 'failed'
            }
    
    def get_sync_status(self) -> Dict:
        """Get current sync status."""
        queue_size = self.get_queue_size()
        
        status = {
            'online': self.status == SyncStatus.ONLINE,
            'status': self.status.value,
            'queue_size': queue_size,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'machine_id': self.machine_id,
            'machine_name': self.machine_name,
            'privacy_level': self.privacy_level.value,
            'enabled': self.enabled
        }
        
        # Add stats if available
        if self.last_sync:
            status.update({
                'sent_total': self.sync_stats.get('sent', 0),
                'failed_total': self.sync_stats.get('failed', 0),
                'last_success': self.sync_stats.get('last_success')
            })
        
        return status
    
    def get_queue_size(self) -> int:
        """Get number of items in sync queue."""
        try:
            cursor = self.db_conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM sync_queue WHERE attempts < ?', 
                         (self.MAX_RETRY_ATTEMPTS,))
            count = cursor.fetchone()[0]
            
            # Add memory queue items
            count += self.sync_queue.qsize()
            count += len(self.retry_queue)
            
            return count
            
        except Exception as e:
            logger.error(f"Failed to get queue size: {e}")
            return 0
    
    def set_privacy_level(self, level: Union[str, PrivacyLevel]) -> bool:
        """Change privacy level."""
        try:
            if isinstance(level, str):
                level = PrivacyLevel(level)
            
            old_level = self.privacy_level
            self.privacy_level = level
            
            # Update config
            self.config['cloud']['privacy']['level'] = level.value
            self.config_manager.save_config()
            
            logger.info(f"Privacy level changed: {old_level.value} -> {level.value}")
            
            if self.alert_manager:
                self.alert_manager.add_alert(
                    source="CloudSync",
                    severity=AlertSeverity.INFO,
                    category=AlertCategory.SYSTEM,
                    title="Privacy Level Changed",
                    description=f"Cloud sync privacy level changed to: {level.value}",
                    recommendations=[]
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to set privacy level: {e}")
            return False
    
    def queue_system_metrics(self, metrics: Dict):
        """Queue system metrics for sync."""
        if self.privacy_level == PrivacyLevel.FULL_PRIVACY:
            return
        
        if self.privacy_level not in [PrivacyLevel.METRICS_ONLY, PrivacyLevel.FULL_SYNC]:
            return
        
        try:
            # Prepare metrics data
            metric_data = {
                'timestamp': datetime.now().isoformat(),
                'machine_id': self.machine_id,
                'cpu_percent': metrics.get('cpu_percent', 0),
                'memory_percent': metrics.get('memory_percent', 0),
                'disk_percent': metrics.get('disk_percent', 0),
                'network_sent_kbps': metrics.get('network_sent_kbps', 0),
                'network_recv_kbps': metrics.get('network_recv_kbps', 0),
                'process_count': metrics.get('process_count', 0),
                'load_avg_1m': metrics.get('load_avg_1m', 0),
                'load_avg_5m': metrics.get('load_avg_5m', 0),
                'load_avg_15m': metrics.get('load_avg_15m', 0)
            }
            
            item = SyncItem(
                table='system_metrics',
                data=metric_data
            )
            
            self._save_to_queue(item)
            
        except Exception as e:
            logger.error(f"Failed to queue system metrics: {e}")
    
    def queue_security_event(self, event: Dict):
        """Queue security event for sync."""
        if self.privacy_level == PrivacyLevel.FULL_PRIVACY:
            return
        
        if self.privacy_level not in [PrivacyLevel.ALERTS_ONLY, PrivacyLevel.FULL_SYNC]:
            return
        
        try:
            # Prepare event data
            event_data = {
                'timestamp': event.get('timestamp'),
                'event_type': event.get('event_type'),
                'severity': event.get('severity'),
                'user': event.get('user'),
                'source_ip': event.get('source_ip'),
                'file_path': event.get('file_path'),
                'process_id': event.get('process_id'),
                'description': event.get('description'),
                'machine_id': self.machine_id
            }
            
            # Add metadata if present
            if 'metadata' in event and event['metadata']:
                event_data['metadata'] = json.dumps(event['metadata'])
            
            item = SyncItem(
                table='security_events',
                data=event_data
            )
            
            self._save_to_queue(item)
            
        except Exception as e:
            logger.error(f"Failed to queue security event: {e}")
    
    def queue_alert(self, alert: Dict):
        """Queue alert for sync."""
        if self.privacy_level == PrivacyLevel.FULL_PRIVACY:
            return
        
        if self.privacy_level not in [PrivacyLevel.ALERTS_ONLY, PrivacyLevel.FULL_SYNC]:
            return
        
        try:
            # Prepare alert data
            alert_data = {
                'timestamp': alert.get('timestamp'),
                'source': alert.get('source'),
                'severity': alert.get('severity'),
                'category': alert.get('category'),
                'title': alert.get('title'),
                'description': alert.get('description'),
                'acknowledged': alert.get('acknowledged', False),
                'machine_id': self.machine_id
            }
            
            # Add evidence if present
            if 'evidence' in alert and alert['evidence']:
                alert_data['evidence'] = json.dumps(alert['evidence'])
            
            # Add recommendations if present
            if 'recommendations' in alert and alert['recommendations']:
                alert_data['recommendations'] = json.dumps(alert['recommendations'])
            
            item = SyncItem(
                table='alerts',
                data=alert_data
            )
            
            self._save_to_queue(item)
            
        except Exception as e:
            logger.error(f"Failed to queue alert: {e}")
    
    def purge_local_data(self) -> bool:
        """Purge local data after successful cloud sync."""
        try:
            # This would typically remove local data that has been synced
            # For now, just clear the sync queue
            cursor = self.db_conn.cursor()
            cursor.execute('DELETE FROM sync_queue WHERE attempts < ?', (self.MAX_RETRY_ATTEMPTS,))
            deleted_count = cursor.rowcount
            
            # Clear memory queues
            while not self.sync_queue.empty():
                try:
                    self.sync_queue.get_nowait()
                except queue.Empty:
                    break
            
            self.retry_queue.clear()
            self.db_conn.commit()
            
            logger.info(f"Purged {deleted_count} items from local queue")
            return True
            
        except Exception as e:
            logger.error(f"Failed to purge local data: {e}")
            return False
    
    def get_cloud_dashboard_url(self) -> Optional[str]:
        """Get URL to view data in Supabase dashboard."""
        if not self.supabase_url:
            return None
        
        # Construct dashboard URL (Supabase specific)
        # This is a guess at the URL structure
        url_parts = self.supabase_url.split('//')
        if len(url_parts) > 1:
            domain = url_parts[1].split('/')[0]
            return f"https://app.supabase.com/project/{domain}/editor"
        
        return None
    
    def get_sync_history(self, limit: int = 100) -> List[Dict]:
        """Get sync history."""
        try:
            cursor = self.db_conn.cursor()
            cursor.execute('''
                SELECT * FROM sync_history 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (limit,))
            
            history = []
            for row in cursor.fetchall():
                history.append({
                    'id': row[0],
                    'timestamp': row[1],
                    'operation': row[2],
                    'table_name': row[3],
                    'items_count': row[4],
                    'success': bool(row[5]),
                    'error': row[6],
                    'duration': row[7]
                })
            
            return history
            
        except Exception as e:
            logger.error(f"Failed to get sync history: {e}")
            return []
    
    def __del__(self):
        """Cleanup on destruction."""
        self.stop()