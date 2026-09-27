# systemd timer (alternative to cron)

```sh
sudo useradd --system --home /opt/ideal-octo-chainsaw gotracker
sudo git clone https://github.com/zenonymous/ideal-octo-chainsaw /opt/ideal-octo-chainsaw
cd /opt/ideal-octo-chainsaw
sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt
sudo cp .env.example .env && sudo chown gotracker .env && sudo chmod 600 .env   # then edit it
sudo -u gotracker .venv/bin/python gopoll.py migrate

sudo cp deploy/systemd/gotracker.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gotracker.timer
```

Check it: `systemctl list-timers gotracker.timer` and `journalctl -u gotracker.service`.
To change the interval, edit `OnCalendar=` in the timer (e.g. `*:0/2` for every 2 minutes).
