#!/bin/bash
# Backup script for production Postgres database
# Backs up to S3 weekly and keeps 4 weeks of history locally
# 
# Installation:
#   chmod +x scripts/backup_db.sh
#   crontab -e
#   Add: 0 2 * * 0  /path/to/scripts/backup_db.sh  # Every Sunday at 2 AM
#
# Requirements:
#   - AWS CLI configured with S3 access
#   - Postgres installed on system
#   - .env with DATABASE_URL set

set -e

# Source environment
if [ -f "$(dirname "$0")/../.env" ]; then
    export $(cat "$(dirname "$0")/../.env" | grep -v '#' | xargs)
fi

# Backup directory
BACKUP_DIR="/var/backups/agent_db"
mkdir -p "$BACKUP_DIR"

# Timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/agent_db_backup_$TIMESTAMP.sql.gz"

# Log file
LOG_FILE="$BACKUP_DIR/backup.log"

# Function to log
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "Starting database backup..."

# Perform backup (supports both DATABASE_URL and individual params)
if [ -n "$DATABASE_URL" ]; then
    # Parse PostgreSQL connection URL
    PGPASSWORD=$(echo "$DATABASE_URL" | sed -n 's/.*:\([^@]*\)@.*/\1/p')
    export PGPASSWORD
    HOST=$(echo "$DATABASE_URL" | sed -n 's/.*@\([^:]*\).*/\1/p')
    PORT=$(echo "$DATABASE_URL" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p' || echo 5432)
    DATABASE=$(echo "$DATABASE_URL" | sed -n 's/.*\/\([^?]*\).*/\1/p')
    
    pg_dump -h "$HOST" -p "$PORT" -d "$DATABASE" -U agent_user | gzip > "$BACKUP_FILE"
else
    # Fallback to environment variables
    PGPASSWORD="${DB_PASSWORD:-change_me_in_production}" pg_dump \
        -h "${DB_HOST:-localhost}" \
        -p "${DB_PORT:-5432}" \
        -d "${DB_NAME:-agent_db}" \
        -U "${DB_USER:-agent_user}" | gzip > "$BACKUP_FILE"
fi

if [ $? -eq 0 ]; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    log "✓ Backup created: $BACKUP_FILE ($BACKUP_SIZE)"
    
    # Upload to S3 if AWS CLI is available
    if command -v aws &> /dev/null && [ -n "$AWS_S3_BACKUP_BUCKET" ]; then
        log "Uploading to S3: $AWS_S3_BACKUP_BUCKET..."
        aws s3 cp "$BACKUP_FILE" "s3://$AWS_S3_BACKUP_BUCKET/agent_db/" \
            --storage-class STANDARD_IA \
            --metadata "timestamp=$TIMESTAMP,size=$BACKUP_SIZE"
        
        if [ $? -eq 0 ]; then
            log "✓ S3 upload successful"
        else
            log "✗ S3 upload failed"
        fi
    fi
    
    # Clean up old backups (keep 4 weeks = 28 days)
    log "Cleaning up backups older than 28 days..."
    find "$BACKUP_DIR" -name "agent_db_backup_*.sql.gz" -mtime +28 -delete
    log "✓ Cleanup complete"
    
    # Verify backup integrity
    if gzip -t "$BACKUP_FILE" 2>/dev/null; then
        log "✓ Backup integrity verified"
    else
        log "✗ WARNING: Backup file may be corrupted"
    fi
else
    log "✗ Backup failed"
    exit 1
fi

log "Backup completed successfully"
