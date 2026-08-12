"""
Encryption utilities for VIGIL.
"""
import os
import base64
import json
from typing import Optional, Dict, Any
import logging
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

class EncryptionManager:
    """Manages encryption and decryption for sensitive data."""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.config = config_manager.config
        
        # Get encryption settings
        encryption_config = self.config.get('security.encryption', {})
        self.enabled = encryption_config.get('enabled', True)
        self.algorithm = encryption_config.get('algorithm', 'Fernet')
        self.key_rotation_days = encryption_config.get('key_rotation_days', 30)
        
        # Generate or load encryption key
        self.key = self._get_or_create_key()
        self.cipher = Fernet(self.key) if self.key else None
        
        logger.info(f"EncryptionManager initialized (enabled: {self.enabled})")
    
    def _get_or_create_key(self) -> Optional[bytes]:
        """Get existing encryption key or create a new one."""
        if not self.enabled:
            return None
        
        key_path = os.path.expanduser('~/.vigil/encryption.key')
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        
        try:
            # Try to load existing key
            if os.path.exists(key_path):
                with open(key_path, 'rb') as f:
                    key = f.read()
                    # Verify it's a valid Fernet key
                    if len(key) == 44:  # Fernet keys are 44 bytes base64 encoded
                        logger.info("Loaded existing encryption key")
                        return key
            
            # Generate new key
            key = Fernet.generate_key()
            with open(key_path, 'wb') as f:
                f.write(key)
            
            # Set secure permissions
            try:
                os.chmod(key_path, 0o600)
            except:
                pass
            
            logger.info("Generated new encryption key")
            return key
            
        except Exception as e:
            logger.error(f"Failed to get/create encryption key: {e}")
            return None
    
    def encrypt(self, data: str) -> Optional[str]:
        """Encrypt a string."""
        if not self.enabled or not self.cipher or not data:
            return data
        
        try:
            # Convert string to bytes and encrypt
            encrypted = self.cipher.encrypt(data.encode())
            # Return base64 encoded string for storage
            return base64.b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return data
    
    def decrypt(self, encrypted_data: str) -> Optional[str]:
        """Decrypt a string."""
        if not self.enabled or not self.cipher or not encrypted_data:
            return encrypted_data
        
        try:
            # Decode base64 and decrypt
            encrypted_bytes = base64.b64decode(encrypted_data)
            decrypted = self.cipher.decrypt(encrypted_bytes)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return encrypted_data
    
    def encrypt_dict(self, data: Dict[str, Any], fields: list) -> Dict[str, Any]:
        """Encrypt specific fields in a dictionary."""
        if not self.enabled or not self.cipher or not fields:
            return data
        
        result = data.copy()
        for field in fields:
            if field in result and result[field]:
                try:
                    encrypted = self.encrypt(str(result[field]))
                    result[f"{field}_encrypted"] = encrypted
                    result[field] = "[ENCRYPTED]"  # Replace with placeholder
                except Exception as e:
                    logger.warning(f"Failed to encrypt field {field}: {e}")
        
        return result
    
    def decrypt_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Decrypt encrypted fields in a dictionary."""
        if not self.enabled or not self.cipher:
            return data
        
        result = data.copy()
        
        # Find and decrypt encrypted fields
        for key in list(result.keys()):
            if key.endswith('_encrypted') and result[key]:
                original_field = key.replace('_encrypted', '')
                try:
                    decrypted = self.decrypt(result[key])
                    result[original_field] = decrypted
                    del result[key]
                except Exception as e:
                    logger.warning(f"Failed to decrypt field {key}: {e}")
        
        return result
    
    def rotate_key(self) -> bool:
        """Rotate encryption key (for key rotation policy)."""
        if not self.enabled:
            return False
        
        try:
            # Generate new key
            new_key = Fernet.generate_key()
            old_key = self.key
            
            # Update key file
            key_path = os.path.expanduser('~/.vigil/encryption.key')
            with open(key_path, 'wb') as f:
                f.write(new_key)
            
            # Update instance
            self.key = new_key
            self.cipher = Fernet(new_key)
            
            logger.info("Encryption key rotated successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to rotate encryption key: {e}")
            return False
    
    def is_encrypted(self, data: str) -> bool:
        """Check if data appears to be encrypted."""
        if not data:
            return False
        
        try:
            # Check if it's base64 encoded and has the right length
            decoded = base64.b64decode(data)
            # Fernet tokens are always a multiple of 4 bytes
            return len(decoded) % 4 == 0
        except:
            return False
    
    def health_check(self) -> Dict[str, Any]:
        """Check encryption system health."""
        return {
            'enabled': self.enabled,
            'algorithm': self.algorithm,
            'key_available': self.key is not None,
            'cipher_available': self.cipher is not None
        }