# ideal-octo-chainsaw

Read the GO Sharing vehicle API and store a record in a database when a scooter has moved.

`gopoll.py` is a small Python 3 script. Each run it:

1. Fetches every shared e-moped (GO Sharing, served by the goUrban platform) near
   Almere, NL from `https://greenmo.core.gourban-mobility.com/front/vehicles`.
2. For each vehicle, looks up the most recent row stored for its license plate in
   the MySQL/MariaDB table `go`.
3. Inserts a new row only when the vehicle appears to have been ridden, meaning its
   position changed by more than the threshold **and** its `remainingKilometers` changed.

Each run takes one snapshot. The script is meant to run on a schedule (for example
cron), and the history builds up over time in the database.

## Requirements

- Python 3
- `requests`, `PyMySQL` (`pip install -r requirements.txt`)
- A MySQL/MariaDB database with a `go` table (see [docs/DATA_MODEL.md](docs/DATA_MODEL.md))

## Running

```sh
pip install -r requirements.txt
# edit the DB credentials at the top of gopoll.py (they are placeholders)
./gopoll.py
```

An example cron entry, every 5 minutes (the real interval was never recorded in the repo):

```cron
*/5 * * * * /path/to/gopoll.py
```

> **Important:** the script only inserts a row when a *previous* row already exists
> for that license plate. With an empty table it inserts nothing. See
> [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) #1.

## Documentation

| File | Contents |
|------|----------|
| [CLAUDE.md](CLAUDE.md) / [AGENTS.md](AGENTS.md) | Guide for AI coding agents and new contributors |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | API response shape and the inferred DB schema |
| [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | Bugs and limitations found in the current code |
