# dankweather-govee-monitor

A small background service that watches log files produced by
[`goveebttemplogger`](https://github.com/wcbonner/GoveeBTTempLogger) and
forwards new sensor readings to the [DankWeather](https://dankweather.com)
`/log` API.

## How it works

`goveebttemplogger` writes one log file per Bluetooth Govee sensor, named
`gvh-<sensor_id>-<YYYY>-<MM>.txt`, into a directory (default
`/var/log/goveebttemplogger/`). Each line is one reading:

```
YYYY-MM-DD HH:MM:SS  <temperature_C>  <humidity_%>  <battery_%>
```

`dankweather-govee-monitor` does three things:

1. **Discovery** – scans the log directory every 60 seconds for files that
   match the `gvh-*-YYYY-MM.txt` pattern and starts a worker thread for each
   new sensor it finds.
2. **Tail** – each worker `tail -F`-style tracks the current month's file for
   its sensor, parses each new line, and `POST`s the reading to the API.
3. **Rollover** – when the month changes, workers automatically switch to the
   next month's file once it appears.

If `goveebttemplogger` is not running yet (the file does not exist), the
worker quietly waits for it to appear instead of erroring out.

## Installing

### One-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/drakeapps/dankweather-govee-logger/master/install.sh | sh
```

The script downloads the latest `.deb`, installs it, prompts you to drop
your provisioning key into `/etc/dankweather-govee-monitor.conf`, then
enables and starts the service. You'll be prompted for `sudo` along the
way. Set `provision_key` to the value generated in your
[dankweather.com](https://dankweather.com) account settings; the other
fields have sensible defaults (see [Configuration](#configuration) for
details).

### Manual install

If you'd rather not pipe a script, grab the latest `.deb` from the
[releases page](https://github.com/drakeapps/dankweather-govee-logger/releases/latest)
and install it yourself:

```bash
curl -fL -o /tmp/dankweather-govee-monitor.deb \
    https://github.com/drakeapps/dankweather-govee-logger/releases/latest/download/dankweather-govee-monitor.deb
sudo apt install /tmp/dankweather-govee-monitor.deb
sudoedit /etc/dankweather-govee-monitor.conf
sudo systemctl enable --now dankweather-govee-monitor
```

`apt install ./<file>.deb` pulls in the runtime dependencies
(`python3-requests`, `goveebttemplogger`) automatically. Plain
`sudo dpkg -i /tmp/dankweather-govee-monitor.deb` works too if you'd
rather resolve those yourself. Downloading to `/tmp` keeps apt's `_apt`
sandbox user happy; if you put the `.deb` in your home directory, apt
prints a harmless `Permission denied` Notice and falls back to fetching
unsandboxed.

The service unit waits for `goveebttemplogger.service` to be up before
starting and runs as the unprivileged `nobody:nogroup` user.

## Configuration

The service reads an INI-style config file. By default it looks at
`/etc/dankweather-govee-monitor.conf`. Override the location with the
`--config` flag or the `GOVEE_MONITOR_CONFIG` environment variable.

```ini
[govee_monitor]
# Directory where goveebttemplogger writes its per-sensor log files.
log_dir = /var/log/goveebttemplogger/

# DankWeather API endpoint that accepts POST /log requests.
api_url = https://api.dankweather.com/log

# Provisioning key tied to your DankWeather account. When set, it is sent
# alongside every reading so newly seen sensors are auto-associated with
# your account on first upload. Leave blank to disable.
provision_key =
```

Any field omitted from the file falls back to the built-in default. If the
file itself is missing the service starts with all defaults and no
provisioning key.

### Provisioning keys

Log in to [dankweather.com](https://dankweather.com), generate a provisioning
key in your account settings, and paste it into `provision_key`. Once it is
set, every reading the monitor sends will carry the key in the request body:

```json
{
  "id": "AABBCCDDEEFF",
  "datetime": "2024-05-12 19:32:14",
  "temperature": "22.5",
  "humidity": "47",
  "battery": "88",
  "provision_key": "..."
}
```

The API uses the key to look up the owning user and associate any new
sensors with that account – no manual claim step required. Subsequent
readings from a sensor that has already been claimed are unaffected by the
key.

The key is low-sensitivity – it only authorizes auto-claiming new sensors
into your account – so the conf file ships with the standard `root:root`
mode `0644` and is readable by other users on the system. Treat it as you
would any other identifier rather than a password.

## Logs and troubleshooting

```bash
journalctl -u dankweather-govee-monitor -f
```

Each successful upload prints `[+] Sent <sensor_id>: <timestamp>`; HTTP
errors print `[!]` lines with the response body. If you see no output at
all, double-check that `log_dir` matches where `goveebttemplogger` is
actually writing files.

## Development

### Running locally

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 govee_monitor.py --config ./govee_monitor.conf
```

The `id` sent to the API is the sensor MAC, lifted from the log filename.
Temperature is in celsius, matching `goveebttemplogger`'s default output and
what the API expects.

### Running tests

```bash
python3 -m unittest test_govee_monitor.py
```

### Building the Debian package from source

If you need an unreleased build (e.g. to test a local change), build the
`.deb` yourself instead of pulling from GitHub releases:

```bash
sudo apt install debhelper-compat dh-python
dpkg-buildpackage -us -uc
sudo apt install ../dankweather-govee-monitor_*.deb
sudo systemctl enable --now dankweather-govee-monitor
```
