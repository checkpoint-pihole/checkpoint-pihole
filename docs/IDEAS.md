# Feature Ideas

A collection of potential features and improvements for Checkpoint Pi-hole.

## Backup & Restore

- **One-click restore** - Restore backups directly to Pi-hole via the Teleporter API
- **Selective restore** - Choose specific components (blocklists, DNS records, DHCP leases, etc.)
- **Backup diff viewer** - Compare two backups to see what changed
- **Backup integrity checks** - Periodic verification that backup files aren't corrupted

## Multi-Instance Support

- **Full multi-instance UI** - Manage multiple Pi-hole instances from one dashboard
- **Cross-instance sync** - Sync configs/blocklists between primary and secondary Pi-holes
- **Bulk operations** - Backup/restore all instances at once

## Monitoring & Alerts

- **Backup failure notifications** - Email/webhook alerts when backups fail
- **Pi-hole health monitoring** - Check if Pi-hole is reachable, query latency
- **Storage usage alerts** - Warn when backup storage is running low
- **Discord/Slack/Telegram integrations** - Push notifications for events

## Remote Storage

- **Cloud backup targets** - Upload backups to S3, Google Drive, Backblaze B2
- **SFTP/SCP export** - Push backups to a remote server
- **Encryption at rest** - Encrypt backup ZIPs before storage

## Analytics & Reporting

- **Backup history charts** - Visualize backup sizes over time
- **Scheduled reports** - Weekly email summary of backup status
- **Audit log** - Track all user actions and system events

## Quality of Life

- **Backup naming templates** - Custom naming with date/hostname placeholders
- **Manual backup notes** - Add descriptions to manual backups
- **Backup tagging** - Tag important backups to exclude from retention cleanup
- **Dark mode** - Theme toggle for the UI
- **API endpoints** - REST API for external automation/integration

## Advanced

- **Backup verification** - Test restore to a temporary Pi-hole container
- **Configuration templates** - Create and apply standard configs across instances
- **Import from v5** - Migration helper for users upgrading from Pi-hole v5
