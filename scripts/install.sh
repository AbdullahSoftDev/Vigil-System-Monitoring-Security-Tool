#!/bin/bash

# VIGIL Installation Script
# Compatible with Ubuntu 22.04 LTS and Kali Linux

set -e

echo "========================================="
echo "VIGIL Installation Script"
echo "Version 1.0"
echo "========================================="

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
    echo "ERROR: Do not run as root/sudo. Run as regular user."
    exit 1
fi

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$NAME
    VER=$VERSION_ID
else
    OS=$(uname -s)
    VER=$(uname -r)
fi

echo "Detected OS: $OS $VER"

# Check Python version
echo ""
echo "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]; }; then
    echo "ERROR: Python 3.10 or higher required. Found: $PYTHON_VERSION"
    echo "Please upgrade Python and try again."
    exit 1
fi
echo "✓ Python $PYTHON_VERSION (OK)"

# Check for required system packages
echo ""
echo "Checking system dependencies..."
MISSING_DEPS=""

# Check for pip
if ! command -v pip3 &> /dev/null; then
    MISSING_DEPS="$MISSING_DEPS python3-pip"
fi

# Check for venv
if ! python3 -c "import venv" &> /dev/null; then
    MISSING_DEPS="$MISSING_DEPS python3-venv"
fi

# Install missing dependencies
if [ ! -z "$MISSING_DEPS" ]; then
    echo "Installing missing dependencies:$MISSING_DEPS"
    
    if [ "$OS" = "Ubuntu" ] || [ "$OS" = "Debian" ]; then
        sudo apt-get update
        sudo apt-get install -y $MISSING_DEPS
    elif [ "$OS" = "Kali GNU/Linux" ]; then
        sudo apt-get update
        sudo apt-get install -y $MISSING_DEPS
    else
        echo "WARNING: Unsupported OS. Please install manually:"
        echo "  - python3-pip"
        echo "  - python3-venv"
        read -p "Continue anyway? (y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
else
    echo "✓ All system dependencies found"
fi

# Create virtual environment
echo ""
echo "Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip install -r requirements.txt

if [ $? -eq 0 ]; then
    echo "✓ All dependencies installed successfully"
else
    echo "ERROR: Failed to install dependencies"
    echo "Please check your internet connection and try again."
    exit 1
fi

# Create necessary directories
echo ""
echo "Creating necessary directories..."
mkdir -p logs data exports assets/icons assets/sounds assets/templates

# Setup configuration files
echo ""
echo "Setting up configuration..."

# Copy environment template if .env doesn't exist
if [ ! -f ".env" ]; then
    if [ -f ".env.template" ]; then
        cp .env.template .env
        echo "✓ Created .env file from template"
        echo "  IMPORTANT: Edit .env file with your Supabase credentials"
    else
        echo "WARNING: .env.template not found. Creating basic .env..."
        cat > .env << EOF
# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key-here

# Machine Identification
MACHINE_NAME=

# Security Settings
ENCRYPTION_KEY=

# Optional Settings
LOG_LEVEL=INFO
DATA_RETENTION_DAYS=30
EOF
        echo "✓ Created basic .env file"
    fi
else
    echo "✓ .env file already exists"
fi

# Copy default config if config.yaml doesn't exist
if [ ! -f "config.yaml" ]; then
    if [ -f "src/config/default_config.yaml" ]; then
        cp src/config/default_config.yaml config.yaml
        echo "✓ Created config.yaml from default"
    else
        echo "WARNING: Default config not found. Creating basic config..."
        cat > config.yaml << EOF
# VIGIL Configuration
monitoring:
  interval: 2
  history_size: 300
  process_update_interval: 5

security:
  sensitive_paths: ['/etc', '/home', '/var/log']
  log_files: ['/var/log/auth.log', '/var/log/syslog']
  scan_interval: 60

privacy:
  level: metrics_only
  encryption_enabled: true

alerts:
  cpu_threshold: 80
  memory_threshold: 90
  disk_threshold: 95
  failed_logins_threshold: 5

cloud:
  enabled: true
  sync_interval: 30
  max_retries: 5

ui:
  theme: DarkGrey14
  refresh_rate: 1000
EOF
        echo "✓ Created basic config.yaml"
    fi
else
    echo "✓ config.yaml already exists"
fi

# Generate machine ID if not exists
echo ""
echo "Generating machine identifier..."
if [ ! -f "data/machine_id" ]; then
    python3 -c "
import uuid
import os
os.makedirs('data', exist_ok=True)
with open('data/machine_id', 'w') as f:
    f.write(str(uuid.uuid4()))
print('  Machine ID generated and saved')
"
    echo "✓ Machine ID generated"
else
    echo "✓ Machine ID already exists"
fi

# Generate encryption key if not in .env
echo ""
echo "Checking encryption setup..."
if grep -q "ENCRYPTION_KEY=\s*$" .env 2>/dev/null || ! grep -q "ENCRYPTION_KEY=" .env 2>/dev/null; then
    echo "Generating encryption key..."
    python3 -c "
import base64
from cryptography.fernet import Fernet
key = Fernet.generate_key()
key_b64 = base64.urlsafe_b64encode(key).decode()
print(f'  New encryption key generated')
print(f'  Add to .env: ENCRYPTION_KEY={key_b64}')
"
    echo "  WARNING: Save this encryption key securely!"
    echo "  Without it, encrypted data cannot be recovered."
else
    echo "✓ Encryption key already configured in .env"
fi

# Make scripts executable
echo ""
echo "Setting up scripts..."
chmod +x scripts/*.sh 2>/dev/null || true

# Create systemd service file template
echo ""
echo "Creating systemd service template..."
cat > vigil.service << EOF
[Unit]
Description=VIGIL Security & Performance Dashboard
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
Environment="PATH=$(pwd)/venv/bin"
ExecStart=$(pwd)/venv/bin/python3 $(pwd)/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
echo "✓ Systemd service file created: vigil.service"

# Create diagnostic script
echo ""
echo "Creating diagnostic script..."
cat > scripts/diagnose.sh << 'EOF'
#!/bin/bash

# VIGIL Diagnostic Script

echo "========================================="
echo "VIGIL Diagnostic Tool"
echo "========================================="

# Check Python
echo ""
echo "[Python Environment]"
python3 --version
which python3

# Check virtual environment
echo ""
echo "[Virtual Environment]"
if [ -d "venv" ]; then
    echo "✓ Virtual environment exists"
    source venv/bin/activate
    pip list | grep -E "(psutil|watchdog|supabase|pysimplegui)"
else
    echo "✗ Virtual environment not found"
fi

# Check configuration
echo ""
echo "[Configuration]"
if [ -f ".env" ]; then
    echo "✓ .env file exists"
    grep -E "(SUPABASE|MACHINE|ENCRYPTION)" .env | head -5
else
    echo "✗ .env file missing"
fi

if [ -f "config.yaml" ]; then
    echo "✓ config.yaml exists"
else
    echo "✗ config.yaml missing"
fi

# Check machine ID
echo ""
echo "[Machine ID]"
if [ -f "data/machine_id" ]; then
    echo "✓ Machine ID: $(cat data/machine_id | head -c 8)..."
else
    echo "✗ Machine ID not found"
fi

# Check dependencies
echo ""
echo "[Dependencies]"
python3 -c "
try:
    import psutil; print('✓ psutil')
except: print('✗ psutil')
try:
    import watchdog; print('✓ watchdog')
except: print('✗ watchdog')
try:
    from supabase import create_client; print('✓ supabase')
except: print('✗ supabase')
try:
    import PySimpleGUI; print('✓ PySimpleGUI')
except: print('✗ PySimpleGUI')
"

# Disk space
echo ""
echo "[System Resources]"
df -h . | tail -1
free -h | grep Mem

echo ""
echo "========================================="
echo "Diagnostic complete"
EOF

chmod +x scripts/diagnose.sh
echo "✓ Diagnostic script created"

# Final instructions
echo ""
echo "========================================="
echo "INSTALLATION COMPLETE!"
echo "========================================="
echo ""
echo "NEXT STEPS:"
echo "1. Edit .env file with your Supabase credentials:"
echo "   - SUPABASE_URL: Get from Supabase project settings"
echo "   - SUPABASE_SERVICE_KEY: Service role key from Supabase"
echo ""
echo "2. Configure config.yaml as needed"
echo ""
echo "3. Run VIGIL:"
echo "   $ source venv/bin/activate"
echo "   $ python main.py"
echo ""
echo "4. Optional: Install as system service:"
echo "   $ sudo cp vigil.service /etc/systemd/system/"
echo "   $ sudo systemctl daemon-reload"
echo "   $ sudo systemctl enable vigil"
echo "   $ sudo systemctl start vigil"
echo ""
echo "5. Run diagnostics if issues occur:"
echo "   $ ./scripts/diagnose.sh"
echo ""
echo "For more information, see docs/INSTALL.md"
echo "========================================="