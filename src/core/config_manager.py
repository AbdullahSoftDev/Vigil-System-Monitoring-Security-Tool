"""
Configuration Manager for VIGIL
Handles loading, validation, and management of configuration files
"""

import os
import yaml
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass, field, asdict
import copy
from typing import List

@dataclass
class MonitoringConfig:
    """Monitoring configuration"""
    interval: float = 2.0
    history_size: int = 300
    process_update_interval: float = 5.0
    disk_check_interval: float = 60.0

@dataclass
class SecurityConfig:
    """Security monitoring configuration"""
    sensitive_paths: list = field(default_factory=lambda: ['/etc', '/home', '/var/log', '/root'])
    log_files: list = field(default_factory=lambda: ['/var/log/auth.log', '/var/log/syslog', '/var/log/secure'])
    scan_interval: float = 60.0
    file_event_timeout: float = 30.0

@dataclass
class PrivacyConfig:
    """Privacy configuration"""
    level: str = 'metrics_only'  # full_privacy, metrics_only, alerts_only, full_sync
    encryption_enabled: bool = True
    anonymize_hostname: bool = False
    encrypt_sensitive_paths: bool = True
    encrypt_usernames: bool = True

@dataclass
class AlertConfig:
    """Alert configuration"""
    cpu_threshold: float = 80.0
    memory_threshold: float = 90.0
    disk_threshold: float = 95.0
    failed_logins_threshold: int = 5
    network_baseline_multiplier: float = 2.0
    consecutive_readings: int = 3

@dataclass
class CloudConfig:
    """Cloud sync configuration"""
    enabled: bool = True
    sync_interval: float = 30.0
    max_retries: int = 5
    batch_size: int = 100
    offline_queue_size: int = 1000
    retry_backoff_base: float = 2.0
    max_backoff_seconds: float = 3600.0

@dataclass
class SupabaseConfig:
    """Supabase configuration"""
    url: str = ''
    service_key: str = ''
    realtime_enabled: bool = False
    rls_enabled: bool = True

@dataclass
class RetentionConfig:
    """Data retention configuration"""
    local_days: int = 7
    export_days: int = 30
    max_local_size_mb: int = 1024

@dataclass
class UIConfig:
    """UI configuration"""
    theme: str = 'DarkGrey14'
    refresh_rate: int = 1000
    graph_history_points: int = 100
    max_alerts_display: int = 50
    show_process_details: bool = True

@dataclass
class LoggingConfig:
    """Logging configuration"""
    level: str = 'INFO'
    file: str = 'vigil.log'
    max_size_mb: int = 10
    backup_count: int = 5

@dataclass
class TestingConfig:
    """Testing configuration"""
    mock_mode: bool = False
    test_interval: float = 0.1

class ConfigManager:
    """Main configuration manager for VIGIL"""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or 'config.yaml'
        self.default_config_path = Path(__file__).parent.parent / 'config' / 'default_config.yaml'
        self.config: Dict[str, Any] = {}
        self._validation_errors = []
        
        # Load environment variables
        self._load_env_vars()
        
        # Load configuration
        self.load()
        
        # Validate configuration
        self.validate()
        
        # Setup logging based on config
        self._setup_logging()
        
        logging.info(f"ConfigManager initialized from {self.config_path}")
    
    def _load_env_vars(self):
        """Load environment variables"""
        self.env_vars = {
            'SUPABASE_URL': os.getenv('SUPABASE_URL', ''),
            'SUPABASE_SERVICE_KEY': os.getenv('SUPABASE_SERVICE_KEY', ''),
            'MACHINE_NAME': os.getenv('MACHINE_NAME', ''),
            'ENCRYPTION_KEY': os.getenv('ENCRYPTION_KEY', ''),
            'LOG_LEVEL': os.getenv('LOG_LEVEL', 'INFO'),
            'DATA_RETENTION_DAYS': os.getenv('DATA_RETENTION_DAYS', '30')
        }
    
    def _setup_logging(self):
        """Setup logging based on configuration"""
        log_level = self.get('logging.level', 'INFO')
        log_file = self.get('logging.file', 'vigil.log')
        
        # Configure logging
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
    
    def load(self):
        """Load configuration from file"""
        try:
            # Check if config file exists
            config_file = Path(self.config_path)
            
            if not config_file.exists():
                logging.warning(f"Config file {self.config_path} not found. Creating from defaults.")
                self._create_default_config()
            
            # Load the config file
            with open(config_file, 'r') as f:
                self.config = yaml.safe_load(f) or {}
            
            logging.info(f"Loaded configuration from {self.config_path}")
            
            # Merge with environment variables
            self._merge_env_vars()
            
            return True
            
        except yaml.YAMLError as e:
            logging.error(f"Error parsing YAML config: {e}")
            self._load_default_config()
            return False
        except Exception as e:
            logging.error(f"Error loading config: {e}")
            self._load_default_config()
            return False
    
    def _load_default_config(self):
        """Load default configuration"""
        try:
            with open(self.default_config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}
            logging.info("Loaded default configuration")
        except Exception as e:
            logging.error(f"Error loading default config: {e}")
            self.config = self._get_default_config_dict()
    
    def _create_default_config(self):
        """Create default config file if it doesn't exist"""
        try:
            # Load default config
            with open(self.default_config_path, 'r') as f:
                default_config = yaml.safe_load(f)
            
            # Create directory if it doesn't exist
            config_file = Path(self.config_path)
            config_file.parent.mkdir(exist_ok=True)
            
            # Write default config
            with open(config_file, 'w') as f:
                yaml.dump(default_config, f, default_flow_style=False)
            
            logging.info(f"Created default config at {self.config_path}")
            
        except Exception as e:
            logging.error(f"Error creating default config: {e}")
            # Create minimal config
            minimal_config = self._get_default_config_dict()
            with open(self.config_path, 'w') as f:
                yaml.dump(minimal_config, f, default_flow_style=False)
    
    def _get_default_config_dict(self) -> Dict:
        """Get default configuration as dictionary"""
        return {
            'monitoring': asdict(MonitoringConfig()),
            'security': asdict(SecurityConfig()),
            'privacy': asdict(PrivacyConfig()),
            'alerts': asdict(AlertConfig()),
            'cloud': asdict(CloudConfig()),
            'supabase': asdict(SupabaseConfig()),
            'retention': asdict(RetentionConfig()),
            'ui': asdict(UIConfig()),
            'logging': asdict(LoggingConfig()),
            'testing': asdict(TestingConfig())
        }
    
    def _merge_env_vars(self):
        """Merge environment variables into configuration"""
        # Update Supabase URL and key from env vars
        if self.env_vars['SUPABASE_URL']:
            if 'supabase' not in self.config:
                self.config['supabase'] = {}
            self.config['supabase']['url'] = self.env_vars['SUPABASE_URL']
        
        if self.env_vars['SUPABASE_SERVICE_KEY']:
            if 'supabase' not in self.config:
                self.config['supabase'] = {}
            self.config['supabase']['service_key'] = self.env_vars['SUPABASE_SERVICE_KEY']
        
        # Update log level from env var
        if self.env_vars['LOG_LEVEL']:
            if 'logging' not in self.config:
                self.config['logging'] = {}
            self.config['logging']['level'] = self.env_vars['LOG_LEVEL']
        
        # Update retention days from env var
        if self.env_vars['DATA_RETENTION_DAYS']:
            try:
                retention_days = int(self.env_vars['DATA_RETENTION_DAYS'])
                if 'retention' not in self.config:
                    self.config['retention'] = {}
                self.config['retention']['export_days'] = retention_days
            except ValueError:
                logging.warning(f"Invalid DATA_RETENTION_DAYS value: {self.env_vars['DATA_RETENTION_DAYS']}")
    
    def validate(self):
        """Validate configuration"""
        self._validation_errors = []
        
        # Validate monitoring config
        if 'monitoring' in self.config:
            monitoring = self.config['monitoring']
            if monitoring.get('interval', 0) <= 0:
                self._validation_errors.append("Monitoring interval must be greater than 0")
            
            if monitoring.get('history_size', 0) < 10:
                self._validation_errors.append("History size must be at least 10")
        
        # Validate alert thresholds
        if 'alerts' in self.config:
            alerts = self.config['alerts']
            for key in ['cpu_threshold', 'memory_threshold', 'disk_threshold']:
                if key in alerts:
                    value = alerts[key]
                    if not 0 <= value <= 100:
                        self._validation_errors.append(f"{key} must be between 0 and 100")
            
            if 'consecutive_readings' in alerts and alerts['consecutive_readings'] < 1:
                self._validation_errors.append("consecutive_readings must be at least 1")
        
        # Validate privacy level
        if 'privacy' in self.config:
            privacy = self.config['privacy']
            valid_levels = ['full_privacy', 'metrics_only', 'alerts_only', 'full_sync']
            if privacy.get('level') not in valid_levels:
                self._validation_errors.append(f"privacy.level must be one of: {', '.join(valid_levels)}")
        
        # Validate sync settings
        if 'cloud' in self.config:
            cloud = self.config['cloud']
            if cloud.get('sync_interval', 0) < 1:
                self._validation_errors.append("cloud.sync_interval must be at least 1 second")
        
        # Log validation results
        if self._validation_errors:
            logging.warning(f"Configuration validation found {len(self._validation_errors)} issues:")
            for error in self._validation_errors:
                logging.warning(f"  - {error}")
        else:
            logging.info("Configuration validation passed")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation
        
        Args:
            key: Dot notation key (e.g., 'monitoring.interval')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any):
        """
        Set configuration value using dot notation
        
        Args:
            key: Dot notation key (e.g., 'monitoring.interval')
            value: Value to set
        """
        keys = key.split('.')
        config = self.config
        
        # Navigate to the nested dictionary
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        # Set the value
        config[keys[-1]] = value
        
        logging.debug(f"Set config {key} = {value}")
    
    def save(self, path: Optional[str] = None):
        """
        Save configuration to file
        
        Args:
            path: Path to save config (defaults to original path)
        """
        save_path = path or self.config_path
        
        try:
            # Create directory if it doesn't exist
            config_file = Path(save_path)
            config_file.parent.mkdir(exist_ok=True)
            
            # Save to file
            with open(config_file, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False)
            
            logging.info(f"Configuration saved to {save_path}")
            return True
            
        except Exception as e:
            logging.error(f"Error saving configuration: {e}")
            return False
    
    def reload(self):
        """Reload configuration from file"""
        logging.info("Reloading configuration...")
        old_config = copy.deepcopy(self.config)
        self.load()
        self.validate()
        
        # Check if config changed
        if old_config != self.config:
            logging.info("Configuration changed after reload")
            return True
        else:
            logging.info("No changes in configuration")
            return False
    
    def get_section(self, section: str) -> Dict:
        """
        Get entire configuration section
        
        Args:
            section: Configuration section name
            
        Returns:
            Section dictionary or empty dict
        """
        return self.config.get(section, {})
    
    def update_section(self, section: str, data: Dict):
        """
        Update entire configuration section
        
        Args:
            section: Configuration section name
            data: New section data
        """
        self.config[section] = data
        logging.debug(f"Updated config section: {section}")
    
    def to_dict(self) -> Dict:
        """Get entire configuration as dictionary"""
        return copy.deepcopy(self.config)
    
    def to_json(self) -> str:
        """Get entire configuration as JSON string"""
        return json.dumps(self.config, indent=2)
    
    def to_yaml(self) -> str:
        """Get entire configuration as YAML string"""
        return yaml.dump(self.config, default_flow_style=False)
    
    def get_validation_errors(self) -> List[str]:
        """Get list of validation errors"""
        return self._validation_errors.copy()
    
    def is_valid(self) -> bool:
        """Check if configuration is valid"""
        return len(self._validation_errors) == 0
    
    def get_monitoring_config(self) -> MonitoringConfig:
        """Get monitoring configuration as dataclass"""
        data = self.get_section('monitoring') or asdict(MonitoringConfig())
        return MonitoringConfig(**data)
    
    def get_security_config(self) -> SecurityConfig:
        """Get security configuration as dataclass"""
        data = self.get_section('security') or asdict(SecurityConfig())
        return SecurityConfig(**data)
    
    def get_privacy_config(self) -> PrivacyConfig:
        """Get privacy configuration as dataclass"""
        data = self.get_section('privacy') or asdict(PrivacyConfig())
        return PrivacyConfig(**data)
    
    def get_alert_config(self) -> AlertConfig:
        """Get alert configuration as dataclass"""
        data = self.get_section('alerts') or asdict(AlertConfig())
        return AlertConfig(**data)
    
    def get_cloud_config(self) -> CloudConfig:
        """Get cloud configuration as dataclass"""
        data = self.get_section('cloud') or asdict(CloudConfig())
        return CloudConfig(**data)
    
    def get_supabase_config(self) -> SupabaseConfig:
        """Get Supabase configuration as dataclass"""
        data = self.get_section('supabase') or asdict(SupabaseConfig())
        return SupabaseConfig(**data)
    
    def get_ui_config(self) -> UIConfig:
        """Get UI configuration as dataclass"""
        data = self.get_section('ui') or asdict(UIConfig())
        return UIConfig(**data)
    
    def print_summary(self):
        """Print configuration summary"""
        print("=" * 60)
        print("VIGIL Configuration Summary")
        print("=" * 60)
        
        # Monitoring
        monitoring = self.get_monitoring_config()
        print(f"\n[Monitoring]")
        print(f"  Interval: {monitoring.interval}s")
        print(f"  History size: {monitoring.history_size} readings")
        print(f"  Process update: {monitoring.process_update_interval}s")
        
        # Privacy
        privacy = self.get_privacy_config()
        print(f"\n[Privacy]")
        print(f"  Level: {privacy.level}")
        print(f"  Encryption: {'Enabled' if privacy.encryption_enabled else 'Disabled'}")
        
        # Alerts
        alerts = self.get_alert_config()
        print(f"\n[Alerts]")
        print(f"  CPU threshold: {alerts.cpu_threshold}%")
        print(f"  Memory threshold: {alerts.memory_threshold}%")
        print(f"  Disk threshold: {alerts.disk_threshold}%")
        
        # Cloud
        cloud = self.get_cloud_config()
        supabase = self.get_supabase_config()
        print(f"\n[Cloud]")
        print(f"  Enabled: {cloud.enabled}")
        print(f"  Sync interval: {cloud.sync_interval}s")
        print(f"  Supabase URL: {'Configured' if supabase.url else 'Not configured'}")
        
        # Security
        security = self.get_security_config()
        print(f"\n[Security]")
        print(f"  Sensitive paths: {len(security.sensitive_paths)}")
        print(f"  Log files: {len(security.log_files)}")
        print(f"  Scan interval: {security.scan_interval}s")
        
        print("\n" + "=" * 60)
        
        # Validation status
        if self._validation_errors:
            print(f"\nValidation Issues: {len(self._validation_errors)}")
            for error in self._validation_errors[:3]:  # Show first 3
                print(f"  ⚠ {error}")
            if len(self._validation_errors) > 3:
                print(f"  ... and {len(self._validation_errors) - 3} more")
        else:
            print("\n✓ Configuration is valid")
    
    def generate_env_template(self, path: str = '.env.template'):
        """Generate environment variable template file"""
        template = """# VIGIL Environment Variables
# Copy this file to .env and fill in the values

# Supabase Configuration (Required for cloud sync)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key-here

# Machine Identification
MACHINE_NAME=  # Leave empty for auto-detection

# Security Settings
ENCRYPTION_KEY=  # Leave empty for auto-generation

# Optional Settings
LOG_LEVEL=INFO
DATA_RETENTION_DAYS=30

# Development Settings (optional)
# DEBUG=true
# TEST_MODE=false
"""
        
        try:
            with open(path, 'w') as f:
                f.write(template)
            logging.info(f"Environment template generated at {path}")
            return True
        except Exception as e:
            logging.error(f"Error generating env template: {e}")
            return False