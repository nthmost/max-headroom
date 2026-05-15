# Ansible Configuration for Max Headroom

Infrastructure-as-code for the Max Headroom video streaming system.

## Quick Start

```bash
cd ansible

# 1. Set up secrets (one-time)
cp group_vars/vault.yml.example group_vars/vault.yml
# Edit vault.yml with real passwords, then:
ansible-vault encrypt group_vars/vault.yml

# 2. Test connectivity
ansible all -m ping

# 3. Dry-run a deployment
ansible-playbook playbooks/zikzak.yml --check --diff

# 4. Deploy for real
ansible-playbook playbooks/zikzak.yml
```

## Inventory

| Host | Role | Access |
|------|------|--------|
| `zikzak` | Streaming server (liquidsoap, relays) | Via jump host `zephyr` |
| `loki` | Intake app, transcode | Direct SSH |
| `zephyr` | HLS segmenters, public relay | Direct SSH |
| `headroom` | Spare compute | Via jump host `zephyr` |

## Playbooks

| Playbook | Hosts | Purpose |
|----------|-------|---------|
| `site.yml` | All | Full deployment |
| `zikzak.yml` | zikzak | Liquidsoap + relays |
| `loki.yml` | loki | Intake app |
| `zephyr.yml` | zephyr | HLS segmenters |

## Roles

| Role | Description |
|------|-------------|
| `liquidsoap` | 4-channel video streaming via NVENC |
| `icecast-relay` | Relay streams from zikzak → zephyr |
| `hls-segmenter` | Convert Icecast streams to HLS |
| `intake-app` | Web UI for adding videos |

## Common Tasks

### Deploy just liquidsoap config
```bash
ansible-playbook playbooks/zikzak.yml --tags liquidsoap
```

### Check what would change (dry-run)
```bash
ansible-playbook playbooks/site.yml --check --diff
```

### Restart a specific service
```bash
ansible zikzak -m systemd -a "name=zikzak-liquidsoap state=restarted" --become
```

### View current secrets
```bash
ansible-vault view group_vars/vault.yml
```

### Edit secrets
```bash
ansible-vault edit group_vars/vault.yml
```

## Adding New Hosts

1. Add to `inventory.yml` under appropriate group
2. Add host-specific vars to `host_vars/<hostname>.yml` if needed
3. Run `ansible <hostname> -m ping` to test connectivity

## Secrets Management

Secrets are stored in `group_vars/vault.yml`, encrypted with ansible-vault.

To set up vault password file (optional, for automation):
```bash
echo "your-vault-password" > ~/.ansible/vault_password
chmod 600 ~/.ansible/vault_password
# Then uncomment vault_password_file in ansible.cfg
```

## Troubleshooting

### Can't reach zikzak/headroom
These hosts require jumping through zephyr. Ensure:
1. You can SSH to zephyr directly: `ssh zephyr`
2. WireGuard is up on zephyr
3. The host is online at Noisebridge

### Vault password prompts
Either:
- Enter password when prompted
- Set up `~/.ansible/vault_password` file
- Use `--vault-password-file` flag

### Service won't start after deploy
Check logs on the target host:
```bash
ansible zikzak -m shell -a "journalctl -u zikzak-liquidsoap -n 50" --become
```
