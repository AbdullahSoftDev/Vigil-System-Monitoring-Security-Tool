"""
Supabase Client for VIGIL
Core cloud connection manager
"""

import os
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from enum import Enum
import uuid
import asyncio
import aiohttp
from dataclasses import dataclass, asdict
import sqlite3
from pathlib import Path

from supabase import create_client, Client
from cryptography.fernet import Fernet
import hashlib
import base64

class ConnectionStatus(Enum):
    """Connection status enumeration"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    OFFLINE = "offline"

class PrivacyLevel(Enum):
    """Privacy level enumeration"""
    FULL_PRIVACY = "full_privacy"
    METRICS_ONLY = "metrics_only"
    ALERTS_ONLY = "alerts_only"
    FULL_SYNC = "full_sync"

@dataclass
class SyncQueueItem:
    """Sync queue item data structure"""
    id: str
    machine_id: str
    table_name: str
    action: str  # INSERT, UPDATE, DELETE
    data: Dict[str, Any]
    created_at: datetime
    attempts: int = 0
    last_attempt: Optional[datetime] = None
    error: Optional[str] = None

class SupabaseClient:
    """Core Supabase connection manager for VIGIL"""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.status = ConnectionStatus.DISCONNECTED
        self.client: Optional[Client] = None
        self.machine_id: Optional[str] = None
        self.encryption_key: Optional[bytes] = None
        self.fernet: Optional[Fernet] = None
        self.lock = threading.Lock()
        self.running = False
        self.sync_thread: Optional[threading.Thread] = None
        
        # Load configuration
        self.supabase_config = self.config.get('supabase', {})
        self.cloud_config = self.config.get('cloud', {})
        self.privacy_config = self.config.get('privacy', {})
        
        # Get settings
        self.supabase_url = os.getenv('SUPABASE_URL') or self.supabase_config.get('url', '')
        self.supabase_key = os.getenv('SUPABASE_SERVICE_KEY') or self.supabase_config.get('service_key', '')
        self.machine_name = os.getenv('MACHINE_NAME') or ''
        self.encryption_key_env = os.getenv('ENCRYPTION_KEY')
        
        # Sync settings
        self.sync_interval = self.cloud_config.get('sync_interval', 30)
        self.max_retries = self.cloud_config.get('max_retries', 5)
        self.batch_size = self.cloud_config.get('batch_size', 100)
        self.offline_queue_size = self.cloud_config.get('offline_queue_size', 1000)
        self.retry_backoff_base = self.cloud_config.get('retry_backoff_base', 2)
        self.max_backoff_seconds = self.cloud_config.get('max_backoff_seconds', 3600)
        
        # Privacy settings
        self.privacy_level = PrivacyLevel(self.privacy_config.get('level', 'metrics_only'))
        self.encryption_enabled = self.privacy_config.get('encryption_enabled', True)
        
        # Initialize local SQLite database for offline queue
        self.db_path = Path('data/vigil_sync.db')
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_local_db()
        
        # Load machine ID
        self._load_machine_id()
        
        # Initialize encryption
        self._init_encryption()
        
        # Statistics
        self.stats = {
            'successful_syncs': 0,
            'failed_syncs': 0,
            'queued_items': 0,
            'last_sync': None,
            'total_bytes_sent': 0,
            'total_bytes_received': 0
        }
        
        logging.info(f"SupabaseClient initialized with privacy level: {self.privacy_level.value}")
    
    def _init_local_db(self):
        """Initialize local SQLite database for offline queue"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create sync queue table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_queue (
                    id TEXT PRIMARY KEY,
                    machine_id TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    attempts INTEGER DEFAULT 0,
                    last_attempt TIMESTAMP,
                    error TEXT,
                    FOREIGN KEY (machine_id) REFERENCES machines(id)
                )
            ''')
            
            # Create machines table for local cache
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS machines (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    os TEXT,
                    last_seen TIMESTAMP,
                    status TEXT DEFAULT 'active'
                )
            ''')
            
            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_queue_created ON sync_queue(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_queue_attempts ON sync_queue(attempts)')
            
            conn.commit()
            conn.close()
            
            logging.debug("Local SQLite database initialized")
            
        except Exception as e:
            logging.error(f"Failed to initialize local database: {e}")
    
    def _load_machine_id(self):
        """Load or generate machine ID"""
        machine_id_path = Path('data/machine_id')
        
        if machine_id_path.exists():
            try:
                with open(machine_id_path, 'r') as f:
                    self.machine_id = f.read().strip()
                logging.info(f"Loaded existing machine ID: {self.machine_id[:8]}...")
            except Exception as e:
                logging.error(f"Failed to load machine ID: {e}")
                self._generate_machine_id()
        else:
            self._generate_machine_id()
    
    def _generate_machine_id(self):
        """Generate a new machine ID"""
        try:
            # Try to get unique system identifiers
            import socket
            import platform
            import psutil
            
            # Create a hash from system information
            system_info = {
                'hostname': socket.gethostname(),
                'platform': platform.platform(),
                'processor': platform.processor(),
                'machine': platform.machine(),
                'boot_time': str(psutil.boot_time())
            }
            
            info_str = json.dumps(system_info, sort_keys=True)
            hash_obj = hashlib.sha256(info_str.encode())
            self.machine_id = hash_obj.hexdigest()[:32]  # Use first 32 chars
            
            # Save to file
            machine_id_path = Path('data/machine_id')
            machine_id_path.parent.mkdir(exist_ok=True)
            with open(machine_id_path, 'w') as f:
                f.write(self.machine_id)
            
            logging.info(f"Generated new machine ID: {self.machine_id[:8]}...")
            
        except Exception as e:
            # Fallback to UUID
            logging.warning(f"Could not generate system-based ID: {e}")
            self.machine_id = str(uuid.uuid4())
            logging.info(f"Generated UUID machine ID: {self.machine_id[:8]}...")
    
    def _init_encryption(self):
        """Initialize encryption system"""
        if not self.encryption_enabled:
            logging.info("Encryption disabled")
            return
        
        try:
            # Try to load from environment variable
            if self.encryption_key_env:
                key = base64.urlsafe_b64decode(self.encryption_key_env)
                if len(key) == 32:  # Fernet requires 32 bytes
                    self.encryption_key = key
                    logging.info("Loaded encryption key from environment")
                else:
                    logging.warning("Invalid encryption key length from environment")
                    self._generate_encryption_key()
            else:
                self._generate_encryption_key()
            
            # Create Fernet instance
            if self.encryption_key:
                key_b64 = base64.urlsafe_b64encode(self.encryption_key)
                self.fernet = Fernet(key_b64)
                logging.info("Encryption system initialized")
            else:
                logging.warning("No encryption key available")
                
        except Exception as e:
            logging.error(f"Failed to initialize encryption: {e}")
            self.encryption_enabled = False
    
    def _generate_encryption_key(self):
        """Generate a new encryption key"""
        try:
            self.encryption_key = Fernet.generate_key()
            
            # Save to file (in a secure location for production)
            key_path = Path('data/encryption_key.txt')
            key_path.parent.mkdir(exist_ok=True)
            
            with open(key_path, 'wb') as f:
                f.write(self.encryption_key)
            
            # Set restrictive permissions (Unix only)
            try:
                os.chmod(key_path, 0o600)
            except:
                pass
            
            logging.warning(f"Generated new encryption key. Save this key securely!")
            logging.warning(f"Key: {base64.urlsafe_b64encode(self.encryption_key).decode()}")
            logging.warning("Add to .env as ENCRYPTION_KEY=")
            
        except Exception as e:
            logging.error(f"Failed to generate encryption key: {e}")
            self.encryption_key = None
    
    def encrypt_data(self, data: Union[str, Dict]) -> str:
        """Encrypt sensitive data"""
        if not self.encryption_enabled or not self.fernet:
            if isinstance(data, dict):
                return json.dumps(data)
            return str(data)
        
        try:
            if isinstance(data, dict):
                data_str = json.dumps(data)
            else:
                data_str = str(data)
            
            encrypted = self.fernet.encrypt(data_str.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
            
        except Exception as e:
            logging.error(f"Encryption failed: {e}")
            if isinstance(data, dict):
                return json.dumps(data)
            return str(data)
    
    def decrypt_data(self, encrypted_data: str) -> Optional[Union[str, Dict]]:
        """Decrypt encrypted data"""
        if not self.encryption_enabled or not self.fernet:
            try:
                return json.loads(encrypted_data)
            except:
                return encrypted_data
        
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data)
            decrypted = self.fernet.decrypt(encrypted_bytes).decode()
            
            # Try to parse as JSON
            try:
                return json.loads(decrypted)
            except:
                return decrypted
                
        except Exception as e:
            logging.error(f"Decryption failed: {e}")
            return None
    
    def connect(self) -> bool:
        """Connect to Supabase"""
        with self.lock:
            if self.status == ConnectionStatus.CONNECTED:
                return True
            
            if not self.supabase_url or not self.supabase_key:
                logging.error("Supabase URL or Service Key not configured")
                self.status = ConnectionStatus.ERROR
                return False
            
            try:
                logging.info(f"Connecting to Supabase at {self.supabase_url}")
                self.status = ConnectionStatus.CONNECTING
                
                # Create Supabase client
                self.client = create_client(self.supabase_url, self.supabase_key)
                
                # Test connection with a simple query
                response = self.client.table('machines').select('count', count='exact').eq('id', self.machine_id).execute()
                
                self.status = ConnectionStatus.CONNECTED
                logging.info("Successfully connected to Supabase")
                
                # Register or update machine
                self._register_machine()
                
                return True
                
            except Exception as e:
                logging.error(f"Failed to connect to Supabase: {e}")
                self.status = ConnectionStatus.ERROR
                return False
    
    def disconnect(self):
        """Disconnect from Supabase"""
        with self.lock:
            if self.status == ConnectionStatus.CONNECTED:
                logging.info("Disconnecting from Supabase")
                self.client = None
                self.status = ConnectionStatus.DISCONNECTED
    
    def is_online(self) -> bool:
        """Check if connected to Supabase"""
        return self.status == ConnectionStatus.CONNECTED
    
    def get_status(self) -> Dict:
        """Get connection status and statistics"""
        with self.lock:
            return {
                'status': self.status.value,
                'machine_id': self.machine_id[:8] + '...' if self.machine_id else None,
                'encryption_enabled': self.encryption_enabled,
                'privacy_level': self.privacy_level.value,
                'stats': self.stats.copy(),
                'queue_size': self._get_queue_size(),
                'supabase_configured': bool(self.supabase_url and self.supabase_key)
            }
    
    def _register_machine(self):
        """Register or update machine in Supabase"""
        if not self.client:
            return
        
        try:
            import platform
            import psutil
            
            # Get system info
            system_info = self._get_system_info()
            
            machine_data = {
                'id': self.machine_id,
                'name': self.machine_name or platform.node(),
                'os': f"{platform.system()} {platform.release()}",
                'last_seen': datetime.utcnow().isoformat(),
                'status': 'online'
            }
            
            # Check if machine exists
            response = self.client.table('machines').select('*').eq('id', self.machine_id).execute()
            
            if response.data:
                # Update existing
                self.client.table('machines').update(machine_data).eq('id', self.machine_id).execute()
                logging.debug(f"Updated machine record: {self.machine_id[:8]}...")
            else:
                # Insert new
                self.client.table('machines').insert(machine_data).execute()
                logging.info(f"Registered new machine: {self.machine_id[:8]}...")
                
        except Exception as e:
            logging.error(f"Failed to register machine: {e}")
    
    def _get_system_info(self) -> Dict:
        """Get system information for registration"""
        try:
            import platform
            import psutil
            
            return {
                'hostname': platform.node(),
                'platform': platform.platform(),
                'processor': platform.processor(),
                'architecture': platform.machine(),
                'python_version': platform.python_version(),
                'cpu_count': psutil.cpu_count(),
                'total_memory_gb': psutil.virtual_memory().total / (1024**3),
                'boot_time': psutil.boot_time()
            }
        except:
            return {}
    
    def queue_data(self, table_name: str, data: Dict, action: str = "INSERT") -> bool:
        """Queue data for sync to Supabase"""
        if not self.machine_id:
            logging.error("No machine ID available")
            return False
        
        try:
            # Apply privacy rules
            processed_data = self._apply_privacy_rules(data.copy())
            
            # Create queue item
            queue_item = SyncQueueItem(
                id=str(uuid.uuid4()),
                machine_id=self.machine_id,
                table_name=table_name,
                action=action,
                data=processed_data,
                created_at=datetime.utcnow()
            )
            
            # Save to local SQLite
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO sync_queue (id, machine_id, table_name, action, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                queue_item.id,
                queue_item.machine_id,
                queue_item.table_name,
                queue_item.action,
                json.dumps(asdict(queue_item)),
                queue_item.created_at.isoformat()
            ))
            
            conn.commit()
            conn.close()
            
            # Update queue size
            self.stats['queued_items'] = self._get_queue_size()
            
            logging.debug(f"Queued {action} for {table_name}: {queue_item.id[:8]}...")
            return True
            
        except Exception as e:
            logging.error(f"Failed to queue data: {e}")
            return False
    
    def _apply_privacy_rules(self, data: Dict) -> Dict:
        """Apply privacy rules to data based on privacy level"""
        if self.privacy_level == PrivacyLevel.FULL_PRIVACY:
            # Encrypt all user-identifiable data
            for key in list(data.keys()):
                if key in ['username', 'path', 'file_path', 'hostname', 'cmdline']:
                    if data[key]:
                        data[f'{key}_encrypted'] = self.encrypt_data(data[key])
                        del data[key]
        
        elif self.privacy_level == PrivacyLevel.METRICS_ONLY:
            # Only send metrics, encrypt sensitive data
            allowed_fields = {
                'system_metrics': ['timestamp', 'cpu_percent', 'memory_percent', 'disk_read_mb', 
                                 'disk_write_mb', 'network_sent_mb', 'network_recv_mb'],
                'security_events': ['timestamp', 'event_type', 'severity', 'description']
            }
            
            # Filter out non-metric fields
            table_type = None
            if 'cpu_percent' in data:
                table_type = 'system_metrics'
            elif 'event_type' in data:
                table_type = 'security_events'
            
            if table_type:
                for key in list(data.keys()):
                    if key not in allowed_fields[table_type]:
                        if self.encryption_enabled and data[key]:
                            data[f'{key}_encrypted'] = self.encrypt_data(data[key])
                        del data[key]
        
        elif self.privacy_level == PrivacyLevel.ALERTS_ONLY:
            # Only send alerts
            if 'event_type' not in data and 'alert_type' not in data:
                # Not an alert, don't send
                return {}
        
        # FULL_SYNC sends everything as-is
        
        return data
    
    def _get_queue_size(self) -> int:
        """Get current queue size"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM sync_queue')
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return 0
    
    def start_sync(self):
        """Start the background sync thread"""
        if self.running:
            return
        
        self.running = True
        self.sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.sync_thread.start()
        logging.info("Sync thread started")
    
    def stop_sync(self):
        """Stop the background sync thread"""
        self.running = False
        if self.sync_thread:
            self.sync_thread.join(timeout=5.0)
        logging.info("Sync thread stopped")
    
    def _sync_loop(self):
        """Background sync loop"""
        while self.running:
            try:
                # Try to connect if not connected
                if not self.is_online():
                    self.connect()
                    if not self.is_online():
                        # Still offline, wait and retry
                        time.sleep(self.sync_interval * 2)
                        continue
                
                # Process sync queue
                self._process_sync_queue()
                
                # Update machine last_seen
                if self.is_online():
                    self._update_machine_last_seen()
                
                # Sleep until next sync
                time.sleep(self.sync_interval)
                
            except Exception as e:
                logging.error(f"Error in sync loop: {e}")
                time.sleep(self.sync_interval)
    
    def _process_sync_queue(self):
        """Process items from the sync queue"""
        if not self.is_online():
            return
        
        try:
            # Get items from queue (oldest first, limited by batch size)
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT data FROM sync_queue 
                WHERE attempts < ? 
                ORDER BY created_at ASC 
                LIMIT ?
            ''', (self.max_retries, self.batch_size))
            
            rows = cursor.fetchall()
            
            successful_items = []
            failed_items = []
            
            for row in rows:
                try:
                    item_data = json.loads(row['data'])
                    queue_item = SyncQueueItem(**item_data)
                    
                    if self._sync_item(queue_item):
                        successful_items.append(queue_item.id)
                    else:
                        failed_items.append(queue_item.id)
                        
                except Exception as e:
                    logging.error(f"Error processing queue item: {e}")
                    failed_items.append(row['data']['id'] if isinstance(row['data'], dict) else 'unknown')
            
            # Remove successful items
            if successful_items:
                placeholders = ','.join('?' * len(successful_items))
                cursor.execute(f'DELETE FROM sync_queue WHERE id IN ({placeholders})', successful_items)
                self.stats['successful_syncs'] += len(successful_items)
            
            # Update failed items with retry count
            if failed_items:
                for item_id in failed_items:
                    cursor.execute('''
                        UPDATE sync_queue 
                        SET attempts = attempts + 1, 
                            last_attempt = ?,
                            error = ?
                        WHERE id = ?
                    ''', (datetime.utcnow().isoformat(), 'Sync failed', item_id))
                
                self.stats['failed_syncs'] += len(failed_items)
            
            conn.commit()
            conn.close()
            
            if successful_items:
                logging.info(f"Synced {len(successful_items)} items to Supabase")
            
            # Update queue size
            self.stats['queued_items'] = self._get_queue_size()
            self.stats['last_sync'] = datetime.utcnow().isoformat()
            
        except Exception as e:
            logging.error(f"Error processing sync queue: {e}")
    
    def _sync_item(self, item: SyncQueueItem) -> bool:
        """Sync a single item to Supabase"""
        if not self.client:
            return False
        
        try:
            table = self.client.table(item.table_name)
            
            if item.action == "INSERT":
                response = table.insert(item.data).execute()
            elif item.action == "UPDATE":
                # Need an ID for update
                if 'id' in item.data:
                    response = table.update(item.data).eq('id', item.data['id']).execute()
                else:
                    logging.error(f"No ID for UPDATE in {item.table_name}")
                    return False
            elif item.action == "DELETE":
                if 'id' in item.data:
                    response = table.delete().eq('id', item.data['id']).execute()
                else:
                    logging.error(f"No ID for DELETE in {item.table_name}")
                    return False
            else:
                logging.error(f"Unknown action: {item.action}")
                return False
            
            # Update statistics
            if hasattr(response, 'text'):
                self.stats['total_bytes_sent'] += len(str(item.data))
                self.stats['total_bytes_received'] += len(response.text)
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to sync item {item.id[:8]}...: {e}")
            return False
    
    def _update_machine_last_seen(self):
        """Update machine's last_seen timestamp"""
        if not self.client:
            return
        
        try:
            self.client.table('machines').update({
                'last_seen': datetime.utcnow().isoformat()
            }).eq('id', self.machine_id).execute()
            
        except Exception as e:
            logging.debug(f"Failed to update machine last_seen: {e}")
    
    def queue_system_metrics(self, metrics: Dict):
        """Queue system metrics for sync"""
        if not metrics:
            return
        
        try:
            # Extract relevant data
            data = {
                'machine_id': self.machine_id,
                'timestamp': metrics.get('timestamp', datetime.utcnow()).isoformat(),
                'cpu_percent': metrics.get('cpu', {}).get('percent', 0.0),
                'memory_percent': metrics.get('memory', {}).get('percent', 0.0),
                'disk_read_mb': metrics.get('disk', {}).get('read_bytes_sec', 0.0) / (1024**2),
                'disk_write_mb': metrics.get('disk', {}).get('write_bytes_sec', 0.0) / (1024**2),
                'network_sent_mb': metrics.get('network', {}).get('bytes_sent_sec', 0.0) / (1024**2),
                'network_recv_mb': metrics.get('network', {}).get('bytes_recv_sec', 0.0) / (1024**2)
            }
            
            self.queue_data('system_metrics', data)
            
        except Exception as e:
            logging.error(f"Failed to queue system metrics: {e}")
    
    def queue_security_event(self, event: Dict):
        """Queue security event for sync"""
        if not event:
            return
        
        try:
            data = {
                'machine_id': self.machine_id,
                'timestamp': event.get('timestamp', datetime.utcnow()).isoformat(),
                'event_type': event.get('type', 'unknown'),
                'severity': event.get('severity', 'info'),
                'description': event.get('message', ''),
                'metadata': event.get('data', {}),
                'encrypted_data': None
            }
            
            # Encrypt sensitive data if needed
            if self.encryption_enabled and self.fernet:
                sensitive_data = {
                    'raw_data': event.get('data', {})
                }
                data['encrypted_data'] = self.encrypt_data(sensitive_data)
                data['metadata'] = {}  # Clear metadata when encrypted
            
            self.queue_data('security_events', data)
            
        except Exception as e:
            logging.error(f"Failed to queue security event: {e}")
    
    def queue_alert(self, alert: Dict):
        """Queue alert for sync (handled as security event)"""
        self.queue_security_event(alert)
    
    def clear_queue(self):
        """Clear all items from sync queue"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sync_queue')
            conn.commit()
            conn.close()
            
            self.stats['queued_items'] = 0
            logging.info("Sync queue cleared")
            
        except Exception as e:
            logging.error(f"Failed to clear sync queue: {e}")
    
    def get_queue_stats(self) -> Dict:
        """Get statistics about the sync queue"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) as total, SUM(attempts) as total_attempts FROM sync_queue')
            total_row = cursor.fetchone()
            
            cursor.execute('SELECT table_name, COUNT(*) as count FROM sync_queue GROUP BY table_name')
            table_rows = cursor.fetchall()
            
            cursor.execute('''
                SELECT attempts, COUNT(*) as count 
                FROM sync_queue 
                GROUP BY attempts 
                ORDER BY attempts
            ''')
            attempt_rows = cursor.fetchall()
            
            conn.close()
            
            return {
                'total': total_row[0] if total_row else 0,
                'total_attempts': total_row[1] if total_row and total_row[1] else 0,
                'by_table': {row[0]: row[1] for row in table_rows},
                'by_attempts': {row[0]: row[1] for row in attempt_rows}
            }
            
        except Exception as e:
            logging.error(f"Failed to get queue stats: {e}")
            return {}