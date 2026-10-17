BEGIN TRANSACTION;
CREATE TABLE appearances (player_id TEXT PRIMARY KEY, appearance TEXT NOT NULL);
CREATE TABLE clock (id INTEGER PRIMARY KEY CHECK (id = 1), seconds INTEGER NOT NULL);
INSERT INTO "clock" VALUES(1,28800);
CREATE TABLE coop_results (battle_id TEXT PRIMARY KEY, outcome INTEGER NOT NULL, players TEXT NOT NULL);
CREATE TABLE event_reports (
        report_id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, player_id TEXT NOT NULL,
        verdict TEXT NOT NULL, at REAL NOT NULL);
INSERT INTO "event_reports" VALUES(1,1,'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','winner',1792212000.0);
INSERT INTO "event_reports" VALUES(2,2,'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','winner',1792212000.0);
CREATE TABLE event_resolutions (
        event_id INTEGER PRIMARY KEY, winner TEXT NOT NULL, seq INTEGER NOT NULL, resolved REAL NOT NULL,
        species INTEGER NOT NULL, level INTEGER NOT NULL, shiny INTEGER NOT NULL, mega INTEGER NOT NULL,
        held_item INTEGER NOT NULL, category TEXT, claimants TEXT NOT NULL);
INSERT INTO "event_resolutions" VALUES(1,'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',1,1792212000.0,359,33,0,0,0,'rare','["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"]');
INSERT INTO "event_resolutions" VALUES(2,'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',2,1792212000.0,383,38,0,0,0,'legendary','["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"]');
CREATE TABLE events (
        event_id INTEGER PRIMARY KEY, record TEXT NOT NULL, state TEXT NOT NULL,
        winner TEXT, created REAL NOT NULL);
INSERT INTO "events" VALUES(1,'{"category": "rare", "claimants": ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"], "event_id": 1, "held_item": 0, "level": 33, "map_group": 0, "map_number": 16, "mega": false, "name": "ABSOL", "perfect_ivs": 1, "place": "ROUTE 101", "remaining": 900.0, "reminded": [], "shiny": false, "species": 359, "x": 10, "y": 7}','caught','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',1792212000.0);
INSERT INTO "events" VALUES(2,'{"category": "legendary", "claimants": ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"], "event_id": 2, "held_item": 0, "level": 38, "map_group": 0, "map_number": 16, "mega": false, "name": "GROUDON", "perfect_ivs": 3, "place": "ROUTE 101", "remaining": 900.0, "reminded": [], "shiny": false, "species": 383, "x": 10, "y": 7}','caught','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',1792212000.0);
INSERT INTO "events" VALUES(3,'{"category": "mega", "claim": {"grace_remaining": null, "player_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}, "claimants": ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"], "event_id": 3, "held_item": 576, "last_claimant": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "level": 33, "map_group": 0, "map_number": 16, "mega": true, "name": "VENUSAUR", "perfect_ivs": 1, "place": "ROUTE 101", "remaining": 900.0, "reminded": [], "shiny": false, "species": 3, "x": 10, "y": 7}','active',NULL,1792212000.0);
CREATE TABLE frontier_attempts (
        battle_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, round INTEGER NOT NULL, code INTEGER NOT NULL,
        level INTEGER NOT NULL, state TEXT NOT NULL, prizes TEXT, paid INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE frontier_records (
        player_id TEXT PRIMARY KEY, best_streak INTEGER NOT NULL, runs INTEGER NOT NULL, rounds INTEGER NOT NULL,
        earned INTEGER NOT NULL);
CREATE TABLE frontier_runs (
        run_id TEXT PRIMARY KEY, players TEXT NOT NULL, state TEXT NOT NULL, consent TEXT NOT NULL,
        round INTEGER NOT NULL, streak INTEGER NOT NULL, seed INTEGER NOT NULL, created REAL NOT NULL,
        updated REAL NOT NULL, ended_reason TEXT, mode TEXT NOT NULL DEFAULT 'frontier');
CREATE TABLE hall_of_fame (
        entry_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE, players TEXT NOT NULL,
        names TEXT NOT NULL, party TEXT NOT NULL, cleared REAL NOT NULL);
CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO "kv" VALUES('event_id','3');
INSERT INTO "kv" VALUES('last_place','ROUTE 101');
INSERT INTO "kv" VALUES('notice_id','5');
INSERT INTO "kv" VALUES('next_event_remaining','1798.8631872741094');
INSERT INTO "kv" VALUES('spawns','{"boards":[],"next_id":1,"version":1}');
INSERT INTO "kv" VALUES('spawn_next_id','1');
INSERT INTO "kv" VALUES('outbreaks','{"current":null,"last_map":"","next_id":1,"next_remaining":524.8679858346953,"version":1}');
CREATE TABLE league_records (
        player_id TEXT PRIMARY KEY, clears INTEGER NOT NULL, best_round INTEGER NOT NULL, first_clear REAL,
        last_clear REAL);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO "metadata" VALUES('world_id','11111111-1111-4111-8111-111111111111');
INSERT INTO "metadata" VALUES('scope','shared-world-v1');
CREATE TABLE secret_bases (
        player_id TEXT PRIMARY KEY, record TEXT NOT NULL, tomb TEXT NOT NULL,
        visibility TEXT NOT NULL, updated INTEGER NOT NULL);
CREATE INDEX frontier_attempts_run ON frontier_attempts (run_id, round);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('event_reports',2);
COMMIT;
