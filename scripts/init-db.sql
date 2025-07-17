-- PostgreSQL initialization script for HR Teams Bot
-- This script is run when the PostgreSQL container starts for the first time

-- Create the database if it doesn't exist (though POSTGRES_DB will handle this)
-- CREATE DATABASE athr360;

-- Create the athr360 user if it doesn't exist (though POSTGRES_USER will handle this)
-- CREATE USER athr360 WITH PASSWORD 'athr360123';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE athr360 TO athr360;

-- Connect to the athr360 database
\c athr360;

-- Create necessary extensions if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Grant schema permissions
GRANT ALL ON SCHEMA public TO athr360;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO athr360;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO athr360;

-- Print success message
SELECT 'HR Teams Bot database initialized successfully!' AS status; 