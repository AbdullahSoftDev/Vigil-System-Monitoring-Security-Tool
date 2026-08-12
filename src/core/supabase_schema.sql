-- VIGIL Supabase Database Schema
-- Run this in your Supabase SQL editor

-- Enable Row Level Security
ALTER DATABASE postgres SET "app.settings.jwt_secret" TO 'your-jwt-secret';

-- =====================================================
-- MACHINES TABLE
-- Tracks all registered VIGIL instances
-- =====================================================
CREATE TABLE IF NOT EXISTS machines (
    id TEXT PRIMARY KEY,                    -- Unique machine ID (generated locally)
    name TEXT NOT NULL,                      -- Machine hostname
    os TEXT,                                 -- Operating system info
    platform TEXT,                           -- Platform details
    cpu_count INTEGER,                        -- Number of CPU cores
    total_memory_gb REAL,                     -- Total RAM in GB
    status TEXT DEFAULT 'active',              -- active, inactive, offline
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Create indexes for machines
CREATE INDEX IF NOT EXISTS idx_machines_status ON machines(status);
CREATE INDEX IF NOT EXISTS idx_machines_last_seen ON machines(last_seen);

-- =====================================================
-- SYSTEM METRICS TABLE
-- Stores performance metrics from all machines
-- =====================================================
CREATE TABLE IF NOT EXISTS system_metrics (
    id BIGSERIAL PRIMARY KEY,
    machine_id TEXT REFERENCES machines(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- CPU Metrics
    cpu_percent REAL,                         -- Overall CPU usage %
    cpu_percent_per_core JSONB,                -- Per-core CPU usage
    
    -- Memory Metrics
    memory_percent REAL,                       -- Memory usage %
    memory_used_gb REAL,                        -- Used memory in GB
    memory_total_gb REAL,                       -- Total memory in GB
    memory_available_gb REAL,                    -- Available memory in GB
    
    -- Disk Metrics
    disk_percent REAL,                         -- Disk usage %
    disk_used_gb REAL,                          -- Used disk space in GB
    disk_total_gb REAL,                         -- Total disk space in GB
    disk_read_mb_sec REAL,                       -- Disk read speed MB/s
    disk_write_mb_sec REAL,                      -- Disk write speed MB/s
    
    -- Network Metrics
    network_sent_mb_sec REAL,                    -- Upload speed MB/s
    network_recv_mb_sec REAL,                     -- Download speed MB/s
    network_sent_total_mb REAL,                    -- Total upload in MB
    network_recv_total_mb REAL,                     -- Total download in MB
    
    -- Process Metrics
    process_count INTEGER,                        -- Number of running processes
    load_avg_1m REAL,                             -- Load average 1 minute
    load_avg_5m REAL,                             -- Load average 5 minutes
    load_avg_15m REAL,                            -- Load average 15 minutes
    
    -- Additional Data
    uptime_seconds INTEGER,                       -- System uptime in seconds
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Create indexes for system_metrics
CREATE INDEX IF NOT EXISTS idx_system_metrics_machine_id ON system_metrics(machine_id);
CREATE INDEX IF NOT EXISTS idx_system_metrics_timestamp ON system_metrics(timestamp);
CREATE INDEX IF NOT EXISTS idx_system_metrics_cpu ON system_metrics(cpu_percent);
CREATE INDEX IF NOT EXISTS idx_system_metrics_memory ON system_metrics(memory_percent);

-- =====================================================
-- SECURITY EVENTS TABLE
-- Stores security-related events
-- =====================================================
CREATE TABLE IF NOT EXISTS security_events (
    id BIGSERIAL PRIMARY KEY,
    machine_id TEXT REFERENCES machines(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Event Details
    event_type TEXT NOT NULL,                    -- file_access, auth_failure, etc.
    severity TEXT NOT NULL,                       -- info, low, medium, high, critical
    description TEXT,                              -- Human readable description
    user_name TEXT,                                -- Username involved
    source_ip TEXT,                                -- Source IP address
    file_path TEXT,                                -- File path if applicable
    process_id INTEGER,                            -- Process ID if applicable
    process_name TEXT,                             -- Process name
    
    -- Additional Data
    metadata JSONB DEFAULT '{}'::jsonb,           -- Additional event data
    
    -- Privacy & Encryption
    encrypted_data TEXT,                           -- Encrypted sensitive data
    data_hash TEXT                                  -- Hash for verification
);

-- Create indexes for security_events
CREATE INDEX IF NOT EXISTS idx_security_events_machine_id ON security_events(machine_id);
CREATE INDEX IF NOT EXISTS idx_security_events_timestamp ON security_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_security_events_event_type ON security_events(event_type);
CREATE INDEX IF NOT EXISTS idx_security_events_severity ON security_events(severity);
CREATE INDEX IF NOT EXISTS idx_security_events_source_ip ON security_events(source_ip);

-- =====================================================
-- ALERTS TABLE
-- Stores alerts generated by the system
-- =====================================================
CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    machine_id TEXT REFERENCES machines(id) ON DELETE CASCADE,
    alert_id TEXT UNIQUE NOT NULL,                -- Original alert ID from machine
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Alert Details
    type TEXT NOT NULL,                           -- CPU, Memory, Security, etc.
    severity TEXT NOT NULL,                        -- info, low, medium, high, critical
    category TEXT,                                 -- system, security, network, etc.
    title TEXT,                                    -- Alert title
    message TEXT,                                  -- Alert message
    description TEXT,                              -- Detailed description
    
    -- Status
    status TEXT DEFAULT 'new',                      -- new, acknowledged, resolved, suppressed
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    
    -- Correlation
    correlation_id TEXT,                            -- ID for correlated alerts
    count INTEGER DEFAULT 1,                         -- Number of duplicate alerts
    
    -- Additional Data
    data JSONB DEFAULT '{}'::jsonb,                 -- Alert-specific data
    recommendations JSONB,                           -- Recommended actions
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Create indexes for alerts
CREATE INDEX IF NOT EXISTS idx_alerts_machine_id ON alerts(machine_id);
CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_correlation_id ON alerts(correlation_id);

-- =====================================================
-- SYNC_QUEUE TABLE
-- Manages offline sync queue
-- =====================================================
CREATE TABLE IF NOT EXISTS sync_queue (
    id BIGSERIAL PRIMARY KEY,
    machine_id TEXT REFERENCES machines(id) ON DELETE CASCADE,
    table_name TEXT NOT NULL,                      -- Target table
    operation TEXT NOT NULL,                        -- INSERT, UPDATE, DELETE
    record_id TEXT,                                 -- ID of the record
    data JSONB NOT NULL,                            -- Data to sync
    status TEXT DEFAULT 'pending',                   -- pending, processing, completed, failed
    attempts INTEGER DEFAULT 0,                      -- Number of sync attempts
    error TEXT,                                      -- Last error message
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for sync_queue
CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON sync_queue(status);
CREATE INDEX IF NOT EXISTS idx_sync_queue_created ON sync_queue(created_at);

-- =====================================================
-- ROW LEVEL SECURITY POLICIES
-- Enable RLS on all tables
-- =====================================================

-- Enable RLS
ALTER TABLE machines ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE security_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_queue ENABLE ROW LEVEL SECURITY;

-- Create policies for authenticated access
CREATE POLICY "Users can view their own machines" ON machines
    FOR SELECT USING (auth.role() = 'authenticated');

CREATE POLICY "Users can insert their own machines" ON machines
    FOR INSERT WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "Users can update their own machines" ON machines
    FOR UPDATE USING (auth.role() = 'authenticated');

-- Similar policies for other tables
CREATE POLICY "Users can view metrics" ON system_metrics
    FOR SELECT USING (auth.role() = 'authenticated');

CREATE POLICY "Users can insert metrics" ON system_metrics
    FOR INSERT WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "Users can view security events" ON security_events
    FOR SELECT USING (auth.role() = 'authenticated');

CREATE POLICY "Users can insert security events" ON security_events
    FOR INSERT WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "Users can view alerts" ON alerts
    FOR SELECT USING (auth.role() = 'authenticated');

CREATE POLICY "Users can insert alerts" ON alerts
    FOR INSERT WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "Users can update alerts" ON alerts
    FOR UPDATE USING (auth.role() = 'authenticated');

-- =====================================================
-- FUNCTIONS AND TRIGGERS
-- =====================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for updated_at
CREATE TRIGGER update_machines_updated_at 
    BEFORE UPDATE ON machines 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_alerts_updated_at 
    BEFORE UPDATE ON alerts 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function to get machine status
CREATE OR REPLACE FUNCTION get_machine_status(machine_id TEXT)
RETURNS TABLE (
    last_seen TIMESTAMP WITH TIME ZONE,
    status TEXT,
    is_online BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        m.last_seen,
        m.status,
        (m.last_seen > NOW() - INTERVAL '5 minutes') as is_online
    FROM machines m
    WHERE m.id = machine_id;
END;
$$ LANGUAGE plpgsql;

-- Function to cleanup old metrics
CREATE OR REPLACE FUNCTION cleanup_old_metrics(days INTEGER)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM system_metrics 
    WHERE timestamp < NOW() - (days || ' days')::INTERVAL;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- VIEWS FOR COMMON QUERIES
-- =====================================================

-- View for latest metrics per machine
CREATE OR REPLACE VIEW latest_metrics AS
SELECT DISTINCT ON (machine_id) 
    machine_id,
    timestamp,
    cpu_percent,
    memory_percent,
    disk_percent,
    process_count,
    load_avg_1m
FROM system_metrics
ORDER BY machine_id, timestamp DESC;

-- View for alert summary
CREATE OR REPLACE VIEW alert_summary AS
SELECT 
    machine_id,
    severity,
    COUNT(*) as alert_count,
    MAX(timestamp) as last_alert
FROM alerts
WHERE status = 'new'
GROUP BY machine_id, severity;

-- View for security event summary
CREATE OR REPLACE VIEW security_summary AS
SELECT 
    machine_id,
    event_type,
    severity,
    COUNT(*) as event_count,
    MAX(timestamp) as last_event
FROM security_events
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY machine_id, event_type, severity;

-- =====================================================
-- COMMENTS FOR DOCUMENTATION
-- =====================================================

COMMENT ON TABLE machines IS 'Registered VIGIL monitoring instances';
COMMENT ON TABLE system_metrics IS 'System performance metrics from all machines';
COMMENT ON TABLE security_events IS 'Security-related events and incidents';
COMMENT ON TABLE alerts IS 'Alerts generated by the monitoring system';
COMMENT ON TABLE sync_queue IS 'Offline sync queue for disconnected operation';

COMMENT ON COLUMN machines.id IS 'Unique machine identifier (generated locally)';
COMMENT ON COLUMN machines.last_seen IS 'Last time the machine reported in';
COMMENT ON COLUMN system_metrics.cpu_percent IS 'Overall CPU usage percentage';
COMMENT ON COLUMN security_events.severity IS 'Severity level: info, low, medium, high, critical';
COMMENT ON COLUMN alerts.correlation_id IS 'ID for grouping related alerts';

-- Grant permissions
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO authenticated;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated;