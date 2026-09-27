-- Schema for fresh installs. `python -m gotracker migrate` creates missing tables from
-- this file, and upgrades existing ones (see db.plan_migration).

-- One row per first sighting of a vehicle and per detected movement.
-- Column names match the table the original 2022 gopoll.py wrote to.
CREATE TABLE IF NOT EXISTS `go` (
  `row_id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `provider`            VARCHAR(32)     NOT NULL DEFAULT 'go_sharing',
  `id`                  VARCHAR(64)     NOT NULL,          -- vehicle id from the API
  `licensePlate`        VARCHAR(64)     NOT NULL,          -- plate (GO Sharing) or GBFS vehicle id
  `stateOfCharge`       DECIMAL(5,2)    NULL,              -- battery %
  `lat`                 DECIMAL(9,6)    NOT NULL,
  `lng`                 DECIMAL(9,6)    NOT NULL,
  `remainingKilometers` DECIMAL(7,2)    NULL,
  `date`                TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`row_id`),
  KEY `idx_go_provider_plate_date` (`provider`, `licensePlate`, `date`)
);

-- Every vehicle on every poll, for providers with snapshots enabled
-- (GOPOLL_STORE_SNAPSHOTS=gbfs by default).
CREATE TABLE IF NOT EXISTS `go_snapshot` (
  `row_id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `provider`            VARCHAR(32)     NOT NULL DEFAULT 'go_sharing',
  `observed_at`         TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id`                  VARCHAR(64)     NOT NULL,
  `licensePlate`        VARCHAR(64)     NOT NULL,
  `stateOfCharge`       DECIMAL(5,2)    NULL,
  `lat`                 DECIMAL(9,6)    NOT NULL,
  `lng`                 DECIMAL(9,6)    NOT NULL,
  `remainingKilometers` DECIMAL(7,2)    NULL,
  PRIMARY KEY (`row_id`),
  KEY `idx_snapshot_provider_plate_time` (`provider`, `licensePlate`, `observed_at`),
  KEY `idx_snapshot_provider_time` (`provider`, `observed_at`)
);
