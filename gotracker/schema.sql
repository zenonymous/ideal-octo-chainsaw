-- Schema for gotracker. Safe to run repeatedly: it only creates missing tables and
-- never alters existing ones. (Run with: python -m gotracker init-db)

-- One row each time a vehicle is seen to have moved (plus a first-sighting baseline row).
-- Column names match the table the original 2022 gopoll.py wrote to, so an existing
-- `go` table keeps working as is.
CREATE TABLE IF NOT EXISTS `go` (
  `row_id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `id`                  VARCHAR(64)     NOT NULL,          -- vehicle id from the API
  `licensePlate`        VARCHAR(32)     NOT NULL,
  `stateOfCharge`       DECIMAL(5,2)    NULL,              -- battery %
  `lat`                 DECIMAL(9,6)    NOT NULL,
  `lng`                 DECIMAL(9,6)    NOT NULL,
  `remainingKilometers` DECIMAL(7,2)    NULL,
  `date`                TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`row_id`),
  KEY `idx_go_plate_date` (`licensePlate`, `date`)
);

-- Optional (GOPOLL_STORE_SNAPSHOTS=true): every vehicle on every poll. Gives exact
-- "last seen here / first seen there" times for ride detection, at the cost of volume.
CREATE TABLE IF NOT EXISTS `go_snapshot` (
  `row_id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `observed_at`         TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id`                  VARCHAR(64)     NOT NULL,
  `licensePlate`        VARCHAR(32)     NOT NULL,
  `stateOfCharge`       DECIMAL(5,2)    NULL,
  `lat`                 DECIMAL(9,6)    NOT NULL,
  `lng`                 DECIMAL(9,6)    NOT NULL,
  `remainingKilometers` DECIMAL(7,2)    NULL,
  PRIMARY KEY (`row_id`),
  KEY `idx_snapshot_plate_time` (`licensePlate`, `observed_at`),
  KEY `idx_snapshot_time` (`observed_at`)
);
