-- Production Postgres schema for EC2 self-hosted stack
-- Run this after creating the database

-- Agents table
CREATE TABLE IF NOT EXISTS agents (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Customers table
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255),
    email VARCHAR(255),
    location VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Properties table
CREATE TABLE IF NOT EXISTS properties (
    id VARCHAR(50) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    location VARCHAR(255),
    price BIGINT,
    area_sqft INTEGER,
    bedrooms INTEGER,
    bathrooms INTEGER,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ad clicks table
CREATE TABLE IF NOT EXISTS ad_clicks (
    id SERIAL PRIMARY KEY,
    customer_phone VARCHAR(20) NOT NULL,
    ad_id VARCHAR(100),
    clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- Calls table (main log)
CREATE TABLE IF NOT EXISTS calls (
    id SERIAL PRIMARY KEY,
    customer_phone VARCHAR(20),
    agent_id INTEGER REFERENCES agents(id),
    duration INTEGER DEFAULT 0,
    transcript TEXT DEFAULT '',
    scenario VARCHAR(100),
    direction VARCHAR(20), -- 'inbound' or 'outbound'
    metadata JSONB DEFAULT '{}',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
CREATE INDEX IF NOT EXISTS idx_ad_clicks_phone ON ad_clicks(customer_phone);
CREATE INDEX IF NOT EXISTS idx_calls_phone ON calls(customer_phone);
CREATE INDEX IF NOT EXISTS idx_calls_agent ON calls(agent_id);
CREATE INDEX IF NOT EXISTS idx_calls_started ON calls(started_at DESC);

-- Create default agent for fallback
INSERT INTO agents (name, status) VALUES ('Default Agent', 'active')
ON CONFLICT DO NOTHING;

-- Grant permissions to application user (change password!)
CREATE USER IF NOT EXISTS agent_user WITH PASSWORD 'change_me_in_production';
GRANT CONNECT ON DATABASE agent_db TO agent_user;
GRANT USAGE ON SCHEMA public TO agent_user;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO agent_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO agent_user;

-- Enable automatic updated_at timestamp
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_agents_timestamp BEFORE UPDATE ON agents
FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER update_customers_timestamp BEFORE UPDATE ON customers
FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER update_properties_timestamp BEFORE UPDATE ON properties
FOR EACH ROW EXECUTE FUNCTION update_timestamp();
