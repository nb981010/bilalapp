# Systemd deployment for Bilal

This directory contains helper files and recommended steps for running the Bilal service under `systemd`.

Files
- `bilal.env.example` — example environment file for `/etc/default/bilal`.
- `bilal.service.template` — templated unit (placeholders for templating workflows).
- `bilal.service.recommended` — recommended unit that runs as `bilal` system user.
- `create_bilal_user.sh` — small helper script to create a `bilal` system user and set permissions (run with `sudo`).

Recommended production setup
1. Create a dedicated system user and set ownership:

```bash
sudo /bin/bash systemd/create_bilal_user.sh /root/code/bilalapp bilal
```

This will create a system user `bilal`, make `/home/bilal`, and chown the application directory and sqlite DB to that user.

2. Copy and edit the env file example to `/etc/default/bilal` (required by the unit):

```bash
sudo cp bilal.env.example /etc/default/bilal
sudoedit /etc/default/bilal
```

3. Install and enable the systemd unit (from repo root):

```bash
./install.sh --service --user bilal
# or if you already created /etc/default/bilal and don't want the installer to overwrite it:
./install.sh --service --user bilal --force-env
```

4. Start and check status:

```bash
sudo systemctl start bilal.service
sudo systemctl status bilal.service
```

Notes
- The installer writes `/etc/default/bilal` by default when `--service` is used. Pass `--force-env` to overwrite an existing env file.
- The recommended unit runs the app from the virtualenv at `.venv` inside the repo; ensure the venv is created and dependencies installed before starting.
- For stricter isolation consider placing the app under `/opt/bilal` and running the service as `bilal` with restricted permissions.
