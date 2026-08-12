"""
Encryption utilities for VIGIL
Handles data encryption, decryption, and key management
"""

import os
import base64
import hashlib
import json
import logging
from typing import Dict, Any, Optional, Union
from datetime import datetime, timedelta
from pathlib import Path
import secrets

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding

class EncryptionManager:
    """Main encryption manager for VIGIL"""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.fernet_key = None
        self.fernet = None
        self.key_rotation_days = 90
        self.key_generated_date = None
        
        # Load configuration
        self._load_config()
        
        # Initialize encryption
        self._initialize_encryption()
        
        logging.info("EncryptionManager initialized")
    
    def _load_config(self):
        """Load encryption configuration"""
        privacy_config = self.config.get('privacy', {})
        self.encryption_enabled = privacy_config.get('encryption_enabled', True)
        self.key_rotation_days = privacy_config.get('key_rotation_days', 90)
        
        # Get encryption key from environment or config
        self.env_key = os.getenv('ENCRYPTION_KEY', '')
    
    def _initialize_encryption(self):
        """Initialize encryption system"""
        if not self.encryption_enabled:
            logging.info("Encryption disabled by configuration")
            return
        
        try:
            # Try to load existing key
            if self._load_encryption_key():
                logging.info("Loaded existing encryption key")
            else:
                # Generate new key
                self._generate_encryption_key()
                logging.info("Generated new encryption key")
            
            # Create Fernet instance
            if self.fernet_key:
                self.fernet = Fernet(self.fernet_key)
                logging.info("Fernet encryption initialized")
            else:
                logging.warning("No encryption key available")
                
        except Exception as e:
            logging.error(f"Failed to initialize encryption: {e}")
            self.encryption_enabled = False
    
    def _load_encryption_key(self) -> bool:
        """Load encryption key from file or environment"""
        # First try environment variable
        if self.env_key:
            try:
                # Decode base64 key
                key_bytes = base64.urlsafe_b64decode(self.env_key)
                if len(key_bytes) == 32:  # Fernet requires 32 bytes
                    self.fernet_key = key_bytes
                    self.key_generated_date = datetime.now()
                    logging.info("Loaded encryption key from environment")
                    return True
                else:
                    logging.warning(f"Invalid key length from environment: {len(key_bytes)}")
            except Exception as e:
                logging.warning(f"Failed to load key from environment: {e}")
        
        # Try to load from key file
        key_file = Path('data/encryption_key.bin')
        info_file = Path('data/encryption_key.info')
        
        if key_file.exists() and info_file.exists():
            try:
                # Load key
                with open(key_file, 'rb') as f:
                    encrypted_key = f.read()
                
                # Load key info
                with open(info_file, 'r') as f:
                    key_info = json.load(f)
                
                # Derive decryption key from system information
                decryption_key = self._derive_system_key()
                
                # Decrypt the key
                iv = base64.b64decode(key_info['iv'])
                cipher = Cipher(
                    algorithms.AES(decryption_key),
                    modes.CBC(iv),
                    backend=default_backend()
                )
                decryptor = cipher.decryptor()
                padded_key = decryptor.update(encrypted_key) + decryptor.finalize()
                
                # Remove padding
                unpadder = padding.PKCS7(128).unpadder()
                self.fernet_key = unpadder.update(padded_key) + unpadder.finalize()
                
                self.key_generated_date = datetime.fromisoformat(key_info['generated_date'])
                
                # Check if key needs rotation
                if self._key_needs_rotation():
                    logging.warning("Encryption key needs rotation")
                    self._generate_encryption_key()
                
                logging.info("Loaded encryption key from file")
                return True
                
            except Exception as e:
                logging.error(f"Failed to load key from file: {e}")
        
        return False
    
    def _generate_encryption_key(self):
        """Generate a new encryption key"""
        try:
            # Generate random key
            self.fernet_key = Fernet.generate_key()
            self.key_generated_date = datetime.now()
            
            # Save key securely
            self._save_encryption_key()
            
            # Log warning about new key
            key_b64 = base64.urlsafe_b64encode(self.fernet_key).decode()
            logging.warning("=" * 60)
            logging.warning("NEW ENCRYPTION KEY GENERATED")
            logging.warning("=" * 60)
            logging.warning(f"Key: {key_b64}")
            logging.warning("Add this to your .env file as ENCRYPTION_KEY=")
            logging.warning("Without this key, encrypted data cannot be decrypted!")
            logging.warning("=" * 60)
            
        except Exception as e:
            logging.error(f"Failed to generate encryption key: {e}")
            self.fernet_key = None
    
    def _save_encryption_key(self):
        """Save encryption key securely"""
        if not self.fernet_key:
            return
        
        try:
            # Create data directory
            data_dir = Path('data')
            data_dir.mkdir(exist_ok=True)
            
            # Derive encryption key from system information
            system_key = self._derive_system_key()
            
            # Generate IV
            iv = os.urandom(16)
            
            # Pad the key
            padder = padding.PKCS7(128).padder()
            padded_key = padder.update(self.fernet_key) + padder.finalize()
            
            # Encrypt the key
            cipher = Cipher(
                algorithms.AES(system_key),
                modes.CBC(iv),
                backend=default_backend()
            )
            encryptor = cipher.encryptor()
            encrypted_key = encryptor.update(padded_key) + encryptor.finalize()
            
            # Save encrypted key
            key_file = data_dir / 'encryption_key.bin'
            with open(key_file, 'wb') as f:
                f.write(encrypted_key)
            
            # Save key info
            info_file = data_dir / 'encryption_key.info'
            key_info = {
                'generated_date': self.key_generated_date.isoformat(),
                'iv': base64.b64encode(iv).decode(),
                'key_length': len(self.fernet_key)
            }
            
            with open(info_file, 'w') as f:
                json.dump(key_info, f)
            
            # Set restrictive permissions (Unix only)
            try:
                os.chmod(key_file, 0o600)
                os.chmod(info_file, 0o600)
            except:
                pass
            
            logging.info("Encryption key saved securely")
            
        except Exception as e:
            logging.error(f"Failed to save encryption key: {e}")
    
    def _derive_system_key(self) -> bytes:
        """Derive encryption key from system information"""
        try:
            import platform
            import socket
            import psutil
            
            # Collect system information
            system_info = {
                'hostname': socket.gethostname(),
                'machine': platform.machine(),
                'processor': platform.processor(),
                'boot_time': str(psutil.boot_time())
            }
            
            # Create a stable string from system info
            info_str = json.dumps(system_info, sort_keys=True)
            
            # Use PBKDF2 to derive key
            salt = b'vigil_salt_'  # Should be stored separately in production
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,  # 32 bytes for AES-256
                salt=salt,
                iterations=100000,
                backend=default_backend()
            )
            
            return kdf.derive(info_str.encode())
            
        except Exception as e:
            logging.error(f"Failed to derive system key: {e}")
            # Fallback to a hardcoded key (less secure)
            return hashlib.sha256(b'vigil_fallback_key').digest()
    
    def _key_needs_rotation(self) -> bool:
        """Check if encryption key needs rotation"""
        if not self.key_generated_date:
            return True
        
        rotation_date = self.key_generated_date + timedelta(days=self.key_rotation_days)
        return datetime.now() > rotation_date
    
    def encrypt_data(self, data: Union[str, Dict, bytes], 
                    encryption_type: str = 'fernet') -> Optional[str]:
        """
        Encrypt data
        
        Args:
            data: Data to encrypt (string, dict, or bytes)
            encryption_type: Type of encryption ('fernet' or 'aes')
            
        Returns:
            Base64 encoded encrypted string or None if encryption fails
        """
        if not self.encryption_enabled or not self.fernet_key:
            # Return plain data as JSON string
            if isinstance(data, dict):
                return json.dumps(data)
            elif isinstance(data, bytes):
                return base64.b64encode(data).decode()
            else:
                return str(data)
        
        try:
            # Convert data to bytes
            if isinstance(data, dict):
                data_bytes = json.dumps(data).encode()
            elif isinstance(data, str):
                data_bytes = data.encode()
            elif isinstance(data, bytes):
                data_bytes = data
            else:
                data_bytes = str(data).encode()
            
            if encryption_type == 'fernet' and self.fernet:
                # Use Fernet encryption
                encrypted = self.fernet.encrypt(data_bytes)
                return base64.urlsafe_b64encode(encrypted).decode()
            
            elif encryption_type == 'aes':
                # Use AES encryption
                iv = os.urandom(16)
                cipher = Cipher(
                    algorithms.AES(self.fernet_key),
                    modes.CBC(iv),
                    backend=default_backend()
                )
                encryptor = cipher.encryptor()
                
                # Pad the data
                padder = padding.PKCS7(128).padder()
                padded_data = padder.update(data_bytes) + padder.finalize()
                
                # Encrypt
                encrypted = encryptor.update(padded_data) + encryptor.finalize()
                
                # Combine IV and encrypted data
                combined = iv + encrypted
                return base64.b64encode(combined).decode()
            
            else:
                logging.error(f"Unsupported encryption type: {encryption_type}")
                return None
                
        except Exception as e:
            logging.error(f"Encryption failed: {e}")
            # Fallback to returning plain data
            if isinstance(data, dict):
                return json.dumps(data)
            return str(data)
    
    def decrypt_data(self, encrypted_data: str, 
                    encryption_type: str = 'fernet') -> Optional[Union[str, Dict, bytes]]:
        """
        Decrypt data
        
        Args:
            encrypted_data: Base64 encoded encrypted string
            encryption_type: Type of encryption ('fernet' or 'aes')
            
        Returns:
            Decrypted data (string, dict, or bytes) or None if decryption fails
        """
        if not self.encryption_enabled or not self.fernet_key:
            # Try to parse as JSON, otherwise return as string
            try:
                return json.loads(encrypted_data)
            except:
                return encrypted_data
        
        try:
            if encryption_type == 'fernet' and self.fernet:
                # Use Fernet decryption
                encrypted_bytes = base64.urlsafe_b64decode(encrypted_data)
                decrypted = self.fernet.decrypt(encrypted_bytes)
                
            elif encryption_type == 'aes':
                # Use AES decryption
                combined = base64.b64decode(encrypted_data)
                iv = combined[:16]
                encrypted = combined[16:]
                
                cipher = Cipher(
                    algorithms.AES(self.fernet_key),
                    modes.CBC(iv),
                    backend=default_backend()
                )
                decryptor = cipher.decryptor()
                
                padded_data = decryptor.update(encrypted) + decryptor.finalize()
                
                # Remove padding
                unpadder = padding.PKCS7(128).unpadder()
                decrypted = unpadder.update(padded_data) + unpadder.finalize()
            
            else:
                logging.error(f"Unsupported encryption type: {encryption_type}")
                return None
            
            # Try to parse as JSON
            try:
                return json.loads(decrypted.decode())
            except:
                # Return as string or bytes
                try:
                    return decrypted.decode()
                except:
                    return decrypted
                
        except Exception as e:
            logging.error(f"Decryption failed: {e}")
            return None
    
    def encrypt_sensitive_fields(self, data: Dict, fields_to_encrypt: list) -> Dict:
        """
        Encrypt specific fields in a dictionary
        
        Args:
            data: Dictionary containing data
            fields_to_encrypt: List of field names to encrypt
            
        Returns:
            Dictionary with specified fields encrypted
        """
        if not self.encryption_enabled:
            return data
        
        result = data.copy()
        
        for field in fields_to_encrypt:
            if field in result and result[field]:
                try:
                    encrypted = self.encrypt_data(result[field])
                    result[f"{field}_encrypted"] = encrypted
                    del result[field]  # Remove plain text field
                except Exception as e:
                    logging.error(f"Failed to encrypt field {field}: {e}")
                    # Keep original field if encryption fails
        
        return result
    
    def decrypt_sensitive_fields(self, data: Dict, fields_to_decrypt: list) -> Dict:
        """
        Decrypt specific fields in a dictionary
        
        Args:
            data: Dictionary containing encrypted data
            fields_to_decrypt: List of field names to decrypt
            
        Returns:
            Dictionary with specified fields decrypted
        """
        if not self.encryption_enabled:
            return data
        
        result = data.copy()
        
        for field in fields_to_decrypt:
            encrypted_field = f"{field}_encrypted"
            if encrypted_field in result and result[encrypted_field]:
                try:
                    decrypted = self.decrypt_data(result[encrypted_field])
                    result[field] = decrypted
                    del result[encrypted_field]
                except Exception as e:
                    logging.error(f"Failed to decrypt field {field}: {e}")
                    # Keep encrypted field if decryption fails
        
        return result
    
    def hash_sensitive_data(self, data: str, algorithm: str = 'sha256') -> str:
        """
        Hash sensitive data (one-way encryption)
        
        Args:
            data: Data to hash
            algorithm: Hash algorithm ('sha256', 'sha512', 'md5')
            
        Returns:
            Hex digest of hashed data
        """
        algorithms = {
            'sha256': hashlib.sha256,
            'sha512': hashlib.sha512,
            'md5': hashlib.md5
        }
        
        if algorithm not in algorithms:
            algorithm = 'sha256'
        
        # Add pepper for additional security
        pepper = os.getenv('ENCRYPTION_PEPPER', 'vigil_default_pepper')
        data_to_hash = f"{data}{pepper}".encode()
        
        return algorithms[algorithm](data_to_hash).hexdigest()
    
    def anonymize_data(self, data: Dict, fields_to_anonymize: list) -> Dict:
        """
        Anonymize data by replacing with hashes
        
        Args:
            data: Dictionary containing data
            fields_to_anonymize: List of field names to anonymize
            
        Returns:
            Dictionary with specified fields anonymized
        """
        result = data.copy()
        
        for field in fields_to_anonymize:
            if field in result and result[field]:
                try:
                    # Hash the data
                    hashed = self.hash_sensitive_data(str(result[field]))
                    result[f"{field}_hash"] = hashed
                    del result[field]  # Remove original field
                except Exception as e:
                    logging.error(f"Failed to anonymize field {field}: {e}")
        
        return result
    
    def generate_secure_token(self, length: int = 32) -> str:
        """
        Generate a secure random token
        
        Args:
            length: Length of token in bytes
            
        Returns:
            Base64 encoded secure token
        """
        token = secrets.token_bytes(length)
        return base64.urlsafe_b64encode(token).decode()
    
    def rotate_key(self):
        """Rotate encryption key"""
        if not self.encryption_enabled:
            logging.warning("Encryption is disabled, cannot rotate key")
            return False
        
        try:
            logging.info("Starting key rotation...")
            
            # Generate new key
            old_key = self.fernet_key
            self._generate_encryption_key()
            
            if self.fernet_key and old_key:
                logging.info("Key rotation completed successfully")
                return True
            else:
                logging.error("Key rotation failed")
                return False
                
        except Exception as e:
            logging.error(f"Key rotation failed: {e}")
            return False
    
    def get_key_info(self) -> Dict:
        """Get encryption key information"""
        return {
            'encryption_enabled': self.encryption_enabled,
            'key_available': bool(self.fernet_key),
            'key_generated': self.key_generated_date.isoformat() if self.key_generated_date else None,
            'key_rotation_days': self.key_rotation_days,
            'needs_rotation': self._key_needs_rotation() if self.key_generated_date else False
        }
    
    def test_encryption(self) -> Dict:
        """Test encryption/decryption functionality"""
        test_data = {
            'message': 'Test encryption',
            'timestamp': datetime.now().isoformat(),
            'number': 42
        }
        
        results = {
            'fernet_encryption': False,
            'aes_encryption': False,
            'field_encryption': False,
            'hashing': False
        }
        
        try:
            # Test Fernet encryption
            encrypted = self.encrypt_data(test_data, 'fernet')
            decrypted = self.decrypt_data(encrypted, 'fernet')
            results['fernet_encryption'] = (decrypted == test_data)
            
            # Test AES encryption
            encrypted = self.encrypt_data(test_data, 'aes')
            decrypted = self.decrypt_data(encrypted, 'aes')
            results['aes_encryption'] = (decrypted == test_data)
            
            # Test field encryption
            data_with_fields = {'username': 'testuser', 'password': 'testpass'}
            encrypted_fields = self.encrypt_sensitive_fields(data_with_fields, ['password'])
            decrypted_fields = self.decrypt_sensitive_fields(encrypted_fields, ['password'])
            results['field_encryption'] = ('password' in decrypted_fields)
            
            # Test hashing
            hash_result = self.hash_sensitive_data('testdata')
            results['hashing'] = bool(hash_result and len(hash_result) == 64)
            
        except Exception as e:
            logging.error(f"Encryption test failed: {e}")
        
        return results


# Utility functions for common encryption tasks
def encrypt_for_privacy_level(data: Dict, privacy_level: str, 
                            encryption_manager: EncryptionManager) -> Dict:
    """
    Encrypt data according to privacy level
    
    Args:
        data: Data to encrypt
        privacy_level: Privacy level ('full_privacy', 'metrics_only', 'alerts_only', 'full_sync')
        encryption_manager: EncryptionManager instance
        
    Returns:
        Encrypted data according to privacy level
    """
    if not encryption_manager.encryption_enabled:
        return data
    
    result = data.copy()
    
    if privacy_level == 'full_privacy':
        # Encrypt all user-identifiable data
        sensitive_fields = ['username', 'hostname', 'path', 'file_path', 
                          'cmdline', 'process_name', 'source_ip', 'destination_ip']
        result = encryption_manager.encrypt_sensitive_fields(result, sensitive_fields)
        
    elif privacy_level == 'metrics_only':
        # Only keep metrics, encrypt everything else
        allowed_fields = ['cpu_percent', 'memory_percent', 'disk_read_mb', 
                         'disk_write_mb', 'network_sent_mb', 'network_recv_mb',
                         'timestamp', 'machine_id']
        
        # Extract allowed fields
        metrics_data = {k: v for k, v in result.items() if k in allowed_fields}
        
        # Encrypt remaining data and store in metadata
        other_data = {k: v for k, v in result.items() if k not in allowed_fields}
        if other_data:
            encrypted_other = encryption_manager.encrypt_data(other_data)
            metrics_data['encrypted_metadata'] = encrypted_other
        
        result = metrics_data
        
    elif privacy_level == 'alerts_only':
        # Only send alerts, encrypt details
        if 'type' not in result and 'alert_type' not in result:
            # Not an alert, don't send
            return {}
        
        # Encrypt alert details
        sensitive_fields = ['username', 'hostname', 'path', 'file_path', 
                          'source_ip', 'destination_ip']
        result = encryption_manager.encrypt_sensitive_fields(result, sensitive_fields)
    
    # 'full_sync' sends everything as-is
    
    return result


def generate_machine_id() -> str:
    """
    Generate a unique machine ID
    
    Returns:
        Unique machine ID string
    """
    try:
        import platform
        import socket
        import psutil
        
        # Collect system information
        system_info = {
            'hostname': socket.gethostname(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'boot_time': str(psutil.boot_time())
        }
        
        # Create hash
        info_str = json.dumps(system_info, sort_keys=True)
        machine_id = hashlib.sha256(info_str.encode()).hexdigest()[:32]
        
        return machine_id
        
    except Exception as e:
        logging.error(f"Failed to generate machine ID: {e}")
        # Fallback to random ID
        return secrets.token_hex(16)