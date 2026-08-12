# 🛡️ VIGIL — Cloud-Connected System Monitoring & Security Dashboard

<div align="center">

**A real-time desktop monitoring platform for system performance, security events, intelligent alerting, and cloud synchronization.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge\&logo=python\&logoColor=white)](https://www.python.org/)
[![Supabase](https://img.shields.io/badge/Supabase-Cloud%20Backend-3ECF8E?style=for-the-badge\&logo=supabase\&logoColor=white)](https://supabase.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-4169E1?style=for-the-badge\&logo=postgresql\&logoColor=white)](https://www.postgresql.org/)
[![PySimpleGUI](https://img.shields.io/badge/GUI-PySimpleGUI-FF6B35?style=for-the-badge)](https://www.pysimplegui.com/)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](#-license)

</div>

---

## 📌 About

**VIGIL** is a desktop-based **system monitoring and security observability platform** designed to provide real-time visibility into machine health, performance, security activity, and operational alerts.

It continuously collects system telemetry such as:

* CPU utilization
* Memory utilization
* Disk activity and storage usage
* Network traffic
* Running processes
* System uptime
* Load averages
* File-system activity
* Authentication-related events
* Process activity

VIGIL combines this information with an **alert management and correlation engine**, allowing multiple events to be analyzed and consolidated into meaningful alerts instead of simply displaying raw telemetry.

The platform also supports **encrypted cloud synchronization through Supabase**, allowing monitoring data and alerts to be synchronized beyond the local machine while maintaining configurable privacy controls and an offline synchronization queue.

---

## ✨ Key Features

### 📊 Real-Time System Monitoring

Monitor the health and performance of the machine in real time.

* CPU utilization
* Per-core CPU information
* RAM usage
* Disk usage
* Disk read/write activity
* Network upload/download activity
* Running process information
* Process CPU and memory consumption
* System uptime
* Load averages
* Historical metric tracking

---

### 🛡️ Security Event Monitoring

VIGIL provides security-oriented event monitoring in addition to traditional performance monitoring.

Supported monitoring includes:

* File-system activity
* Authentication events
* Process activity
* Security event logging
* Event severity classification
* Event searching
* Recent event history
* Security-event statistics

Security events can automatically flow into the alert management system.

---

### 🚨 Intelligent Alert Management

VIGIL includes a dedicated alert-management subsystem instead of treating every threshold violation as an independent notification.

Alerts support:

| Capability      | Description                                |
| --------------- | ------------------------------------------ |
| Severity        | INFO, LOW, MEDIUM, HIGH, CRITICAL          |
| Categories      | Performance, Security, System, Correlation |
| Status          | New, Acknowledged, Resolved, Suppressed    |
| Deduplication   | Detects duplicate alerts                   |
| Suppression     | Suppresses matching alert conditions       |
| Escalation      | Escalates important unresolved alerts      |
| Correlation     | Combines related events                    |
| Acknowledgement | Allows operators to acknowledge alerts     |
| Resolution      | Tracks resolved alerts                     |
| History         | Maintains alert history and statistics     |

---

### 🔗 Event Correlation

Rather than overwhelming the operator with individual events, VIGIL can correlate related alerts and generate higher-level correlated alerts.

This is particularly useful when multiple symptoms originate from the same underlying condition.

For example:

```text
High CPU
   ↓
Process consuming excessive resources
   ↓
System performance degradation
   ↓
Related alerts correlated
   ↓
Single meaningful incident
```

---

### ☁️ Cloud Synchronization

VIGIL integrates with **Supabase/PostgreSQL** for cloud-based data synchronization.

Cloud synchronization supports:

* Machine registration
* System metrics
* Security events
* Alerts
* Offline synchronization queue
* Batch synchronization
* Sync status tracking
* Sync history
* Machine health/status information
* Configurable privacy levels

If the cloud connection is temporarily unavailable, data can remain queued locally and synchronized later.

---

### 🔐 Privacy & Encryption

Sensitive information can be protected before being synchronized to the cloud.

VIGIL includes:

* Encryption support
* Configurable privacy levels
* Sensitive-data filtering
* Data hashing
* Environment-based secret management
* Local/cloud separation
* Configurable data retention

Secrets such as Supabase credentials are intended to be supplied through environment variables rather than committed directly to source control.

---

### 📈 Live Data Visualization

The desktop dashboard provides visual representations of system activity.

Live graphs can display:

* CPU usage
* Memory usage
* Disk activity
* Network activity
* Historical system metrics

Graphs dynamically update as new monitoring data is collected.

---

### 📤 Data Export

The project includes an export subsystem for working with collected monitoring information and generating data suitable for further analysis.

The project also includes Pandas-based data processing support.

---

## 🏗️ Architecture

VIGIL follows a modular architecture separating monitoring, security, alert processing, synchronization, configuration, and presentation.

```text
┌─────────────────────────────────────────────┐
│              VIGIL Desktop UI               │
│                                             │
│  Dashboard │ Graphs │ Processes │ Alerts   │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│             Core Monitoring Layer           │
│                                             │
│  SystemMonitor                              │
│  SecurityLogger                             │
│  AlertManager                               │
│  Correlation Engine                         │
└──────────────────────┬──────────────────────┘
                       │
              ┌────────┴────────┐
              ▼                 ▼
┌─────────────────────┐  ┌───────────────────┐
│ Local Data / Queue  │  │ Security & Crypto │
│                     │  │                   │
│ SQLite / Local DB   │  │ Encryption        │
│ Sync Queue          │  │ Privacy Filtering │
└──────────┬──────────┘  └───────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│              CloudSync Layer                │
│                                             │
│        Supabase PostgreSQL Backend          │
└─────────────────────────────────────────────┘
```

### Core Components

```text
main.py
   │
   ├── ConfigManager
   │
   ├── SystemMonitor
   │      ├── CPU
   │      ├── Memory
   │      ├── Disk
   │      ├── Network
   │      └── Processes
   │
   ├── SecurityLogger
   │      ├── File Monitoring
   │      ├── Authentication Monitoring
   │      └── Process Monitoring
   │
   ├── AlertManager
   │      ├── Deduplication
   │      ├── Suppression
   │      ├── Escalation
   │      └── Correlation
   │
   ├── CloudSync
   │      ├── Privacy Filtering
   │      ├── Encryption
   │      ├── Offline Queue
   │      └── Supabase Synchronization
   │
   └── VigilDashboard
          ├── Metrics
          ├── Graphs
          ├── Processes
          └── Alerts
```

---

## 🧰 Technology Stack

### Core

* **Python 3.10+**
* **PySimpleGUI** — Desktop user interface
* **PyYAML** — Configuration management
* **psutil** — System and process monitoring
* **watchdog** — File-system monitoring

### Data & Visualization

* **Pandas** — Data processing and export
* **Matplotlib** — Live monitoring graphs

### Cloud

* **Supabase**
* **PostgreSQL**
* **aiohttp** — Asynchronous HTTP communication

### Security

* **cryptography** — Encryption
* **python-dotenv** — Secure environment configuration

### Development

* **pytest**
* **pytest-asyncio**
* **Black**
* **Pylint**
* **MyPy**
* **pre-commit**

---

## 📁 Project Structure

```text
vigil/
│
├── main.py
├── config.yaml
├── requirements.txt
├── .env.template
│
├── src/
│   │
│   ├── core/
│   │   ├── alert_manager.py
│   │   ├── cloud_sync.py
│   │   ├── config_manager.py
│   │   ├── correlation_engine.py
│   │   ├── encryption.py
│   │   ├── export_manager.py
│   │   ├── security_logger.py
│   │   ├── supabase_client.py
│   │   └── system_monitor.py
│   │
│   ├── ui/
│   │   ├── dashboard.py
│   │   ├── themes.py
│   │   └── components/
│   │
│   ├── utils/
│   │   ├── diagnostic.py
│   │   ├── encryption.py
│   │   ├── helpers.py
│   │   └── logging.py
│   │
│   └── config/
│       └── default_config.yaml
│
├── scripts/
│   ├── install.sh
│   ├── setup_supabase.py
│   ├── diagnose.sh
│   └── vigil.service
│
├── tests/
│   ├── test_integration.py
│   ├── test_unit_system_monitor.py
│   ├── test_unit_supabase_client.py
│   ├── test_system_monitor_basic.py
│   └── diagnostic.py
│
└── assets/
```

---

## 🚀 Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/vigil.git
cd vigil
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
```

Activate it:

**Linux / macOS**

```bash
source venv/bin/activate
```

**Windows**

```powershell
venv\Scripts\activate
```

---

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuration

Create your environment file from the provided template:

```bash
cp .env.template .env
```

Then configure your Supabase credentials:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key

MACHINE_NAME=
ENCRYPTION_KEY=

LOG_LEVEL=INFO
DATA_RETENTION_DAYS=30
```

### Environment Variables

| Variable               | Purpose                              |
| ---------------------- | ------------------------------------ |
| `SUPABASE_URL`         | Supabase project URL                 |
| `SUPABASE_SERVICE_KEY` | Supabase service-role/API credential |
| `MACHINE_NAME`         | Custom machine identifier            |
| `ENCRYPTION_KEY`       | Encryption key                       |
| `LOG_LEVEL`            | Application logging level            |
| `DATA_RETENTION_DAYS`  | Metric retention period              |

> **Important:** Never commit `.env` or production Supabase credentials to GitHub.

---

## 🗄️ Supabase Setup

The repository contains the database schema required by VIGIL:

```text
src/core/supabase_schema.sql
```

The schema provides tables for:

```text
machines
    │
    ├── system_metrics
    │
    ├── security_events
    │
    └── alerts

sync_queue
```

It also includes:

* Indexes
* Row-Level Security policies
* Database functions
* Update triggers
* Machine-status helpers
* Metric cleanup functionality
* Latest-metric views

Run the schema in your Supabase PostgreSQL SQL editor before enabling cloud synchronization.

---

## ▶️ Running VIGIL

Start the application with:

```bash
python main.py
```

The application initializes:

```text
Configuration
      ↓
Alert Manager
      ↓
System Monitor
      ↓
Security Logger
      ↓
Cloud Sync
      ↓
Desktop Dashboard
```

Once running, VIGIL begins collecting system telemetry and monitoring configured security events.

---

## 🧪 Testing

Run the complete test suite using:

```bash
pytest
```

Run a specific test:

```bash
pytest tests/test_unit_system_monitor.py
```

Integration tests:

```bash
pytest tests/test_integration.py
```

The repository also contains diagnostic utilities for troubleshooting installation and runtime issues.

---

## 🩺 Diagnostics

For Linux environments, the project provides:

```bash
./scripts/diagnose.sh
```

Installation helper:

```bash
./scripts/install.sh
```

A systemd service definition is also included:

```text
scripts/vigil.service
```

This allows VIGIL to be configured as a background Linux service.

---

## 🔄 Monitoring Pipeline

VIGIL's monitoring pipeline can be summarized as:

```text
Operating System
       │
       ▼
   psutil / watchdog
       │
       ▼
 SystemMonitor ───────────────┐
       │                      │
       │                      ▼
       │                CloudSync Queue
       │                      │
       ▼                      │
 AlertManager                 │
       │                      │
       ├── Deduplication      │
       ├── Suppression        │
       ├── Escalation         │
       └── Correlation        │
       │                      │
       ▼                      │
 SecurityLogger ──────────────┤
       │                      │
       ▼                      ▼
   Dashboard             Supabase
                              │
                              ▼
                         PostgreSQL
```

---

## 🔐 Security Model

VIGIL is designed around several security principles:

### Secrets

Credentials are loaded from environment variables rather than hard-coded configuration.

### Encryption

Sensitive information can be encrypted before cloud synchronization.

### Privacy Filtering

Cloud synchronization supports configurable privacy levels to determine what information should be synchronized.

### Hash Verification

Security events can contain hashes that help verify data integrity.

### Row-Level Security

The Supabase schema enables PostgreSQL Row-Level Security policies for application tables.

---

## 📊 Database Model

The primary cloud data model contains:

### `machines`

Stores registered monitoring machines and their current status.

### `system_metrics`

Stores CPU, memory, disk, network, process, and load information.

### `security_events`

Stores security-related events such as file, authentication, and process activity.

### `alerts`

Stores generated and correlated alerts with severity and lifecycle state.

### `sync_queue`

Provides reliable synchronization when cloud connectivity is unavailable.

---

## 🎯 Design Goals

VIGIL was designed around five primary goals:

**1. Visibility**

Provide a single interface for understanding system health and security activity.

**2. Responsiveness**

Collect and display live telemetry without blocking the user interface.

**3. Reliability**

Continue collecting information even when cloud connectivity is unavailable.

**4. Security**

Protect sensitive monitoring information through encryption and privacy controls.

**5. Extensibility**

Maintain a modular architecture so additional monitors, alert types, data sources, and cloud integrations can be added independently.

---

## 🛠️ Development

The project separates responsibilities into independent modules:

```text
Core
 ├── Monitoring
 ├── Security
 ├── Alerting
 ├── Correlation
 ├── Synchronization
 ├── Encryption
 └── Configuration

UI
 ├── Dashboard
 ├── Themes
 └── Components

Utils
 ├── Logging
 ├── Diagnostics
 ├── Helpers
 └── Encryption
```

This separation makes the project easier to test, maintain, and extend.

---

## 🔮 Future Improvements

Potential areas for future development include:

* Multi-machine centralized monitoring
* Web-based management dashboard
* Advanced anomaly detection
* Machine-learning-based threat detection
* More security event sources
* Role-based access control
* Real-time cloud notifications
* Email/Slack/Discord alert integrations
* Advanced incident timelines
* Container and server monitoring
* Expanded Windows/macOS security telemetry
* More granular Supabase authorization policies

---

## ⚠️ Disclaimer

VIGIL is intended for **legitimate system monitoring, security observability, administration, and educational purposes**.

Only monitor systems and data that you own or have explicit authorization to monitor.

Because system and security monitoring capabilities vary across operating systems, some monitoring features may behave differently depending on platform permissions and available system APIs.

---

## 📜 License

This project is licensed under the **MIT License**.

See the `LICENSE` file for details.

---

## 👨‍💻 Author

**Muhammad Abdullah**

Computer Science Student & Full-Stack AI Developer

Interested in:

* Artificial Intelligence
* Cybersecurity
* Systems Programming
* Full-Stack Development
* Software Engineering
* Intelligent Monitoring Systems

---

<div align="center">

### 🛡️ VIGIL

**Observe. Detect. Correlate. Protect.**

⭐ If you find this project useful, consider giving the repository a star.

</div>
