#!/bin/bash
# backup-sync.sh — 备份文件异地同步（v2.7 工程运维项）
# 把 data/backups/ 里新增的备份文件同步到远端（rsync/scp 皆可），建议 crontab：
#   15 * * * * /opt/itops-helpdesk/scripts/backup-sync.sh >> /var/log/itops-backup-sync.log 2>&1
#
# 用前配置：
#  REMOTE_HOST="backup@192.168.1.200"   # 远端主机（已配好 SSH 免密）
#  REMOTE_DIR="/backup/itops-helpdesk"  # 远端目录

REMOTE_HOST="${REMOTE_HOST:-backup@127.0.0.1}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/itops-backups}"
BACKUP_DIR="${BACKUP_DIR:-/opt/itops-helpdesk/backend/data/backups}"

if [ ! -d "$BACKUP_DIR" ]; then
  echo "备份目录不存在: $BACKUP_DIR"
  exit 1
fi

# rsync --ignore-existing：只同步新文件，远端不删除（本地轮换不影响异地留存）
rsync -av --ignore-existing "$BACKUP_DIR/" "$REMOTE_HOST:$REMOTE_DIR/"
RC=$?

if [ $RC -eq 0 ]; then
  echo "$(date '+%F %T') 同步完成 → $REMOTE_HOST:$REMOTE_DIR"
else
  echo "$(date '+%F %T') 同步失败（rsync 退出码 $RC）"
fi
exit $RC
