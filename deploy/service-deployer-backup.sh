#!/bin/bash
# /usr/local/bin/service-deployer-backup.sh — 每日 pg_dump
# 由 systemd timer 或 cron 调用
set -euo pipefail

DB_NAME="service_deployer"
BACKUP_DIR="/var/backups/service-deployer"
RETENTION_DAYS=14
TS=$(date +%Y%m%d-%H%M%S)
OUT="${BACKUP_DIR}/${DB_NAME}-${TS}.sql.gz"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# 用 postgres 系统账号执行（peer auth，无密码）
sudo -u postgres pg_dump -Fc "$DB_NAME" | gzip > "$OUT"
chmod 600 "$OUT"

# 清理超过 RETENTION_DAYS 的备份
find "$BACKUP_DIR" -name "${DB_NAME}-*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete

# 输出最近 3 个备份
echo "[$(date -Iseconds)] Backup OK: $OUT ($(stat -c %s "$OUT") bytes)"
ls -lh "$BACKUP_DIR" | tail -4
