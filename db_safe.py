"""
db_safe.py — Safe write utilities shared across all UCI scraper scripts.

Every scraper imports this module for:

  safe_json_write(path, data, required_keys, min_ratio)
      backup → write tmp → parse verify → key check → size check
      → atomic replace → read-back verify → restore on failure

  db_upsert(conn, table, row, pk_col)
      INSERT OR REPLACE → read back by PK → verify required fields match

  pre_scrape_check(source, sample_size, validator)
      Load existing JSON / DB rows, pick a random sample, run validator,
      abort with clear error if any sample fails.

  get_db()
      Returns an open connection to cycling.db (caller must close).

Usage:
  from db_safe import safe_json_write, db_upsert, pre_scrape_check, get_db
"""

import json
import os
import random
import shutil
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / 'cycling.db'


# ── Database connection ───────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    """Open cycling.db with WAL mode and return connection."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.row_factory = sqlite3.Row
    return conn


# ── Safe JSON write ───────────────────────────────────────────────────────────

def safe_json_write(
    path,
    data,
    required_keys=None,
    min_ratio=0.85,
    label=None,
):
    """
    Atomically write `data` as JSON to `path` with full validation.

    Steps:
      1. Serialise to tmp file
      2. Parse the tmp file back (JSON round-trip check)
      3. Verify required_keys present
      4. Verify file did not shrink below min_ratio of previous size
      5. Atomic os.replace(tmp → path)
      6. Read-back verify the live file once more
      7. On any failure: restore backup and raise RuntimeError

    Args:
      path          pathlib.Path or str
      data          dict/list to serialise
      required_keys list of keys that must appear at the top level
      min_ratio     minimum allowed size ratio vs previous file (0.85 = max 15% shrink)
      label         human name for error messages (defaults to filename)
    """
    path = Path(path)
    label = label or path.name
    required_keys = required_keys or []

    prev_size = path.stat().st_size if path.exists() else 0
    backup = path.with_suffix(path.suffix + '.bak')
    tmp    = path.with_suffix(path.suffix + '.tmp')

    # Backup existing file
    if path.exists():
        shutil.copy2(path, backup)

    try:
        # 1. Write to tmp
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, separators=(',', ':')),
            encoding='utf-8',
        )

        # 2. Round-trip parse
        try:
            parsed = json.loads(tmp.read_text(encoding='utf-8'))
        except Exception as e:
            raise RuntimeError(f'{label}: JSON parse of tmp file failed: {e}')

        # 3. Required keys
        for key in required_keys:
            if key not in parsed:
                raise RuntimeError(f'{label}: required key "{key}" missing after write')

        # 4. Size regression
        new_size = tmp.stat().st_size
        if prev_size > 0 and new_size < prev_size * min_ratio:
            raise RuntimeError(
                f'{label}: file shrank too much '
                f'({prev_size//1024} KB → {new_size//1024} KB, '
                f'ratio={new_size/prev_size:.2f}, min={min_ratio})'
            )

        # 5. Atomic replace
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                time.sleep(0.4)
        else:
            raise RuntimeError(f'{label}: could not replace file after 5 attempts')

        # 6. Read-back verify live file
        try:
            live = json.loads(path.read_text(encoding='utf-8'))
        except Exception as e:
            raise RuntimeError(f'{label}: read-back parse of live file failed: {e}')

        for key in required_keys:
            if key not in live:
                raise RuntimeError(f'{label}: required key "{key}" missing in live file after replace')

        # Success — remove backup
        if backup.exists():
            backup.unlink()

        size_kb = path.stat().st_size // 1024
        print(f'  ✓ {label} written ({size_kb} KB)', flush=True)

    except Exception as exc:
        # Restore backup on any failure
        if backup.exists():
            shutil.copy2(backup, path)
            print(f'  ✗ {label}: {exc}', flush=True)
            print(f'  ↩ Restored backup ({path.stat().st_size//1024} KB)', flush=True)
        else:
            print(f'  ✗ {label}: {exc} (no backup to restore)', flush=True)
        # Clean up tmp
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        raise RuntimeError(str(exc)) from exc


# ── SQLite upsert with read-back ──────────────────────────────────────────────

def db_upsert(conn: sqlite3.Connection, table: str, row: dict, pk_col: str):
    """
    INSERT OR REPLACE a row into `table`, then read it back and verify
    the primary key value matches.

    Args:
      conn    open sqlite3 connection
      table   table name
      row     dict of column→value
      pk_col  name of the primary key column to verify on read-back
    """
    if not row:
        raise ValueError('db_upsert: empty row dict')

    cols    = list(row.keys())
    values  = [row[c] for c in cols]
    placeholders = ','.join('?' * len(cols))
    col_list     = ','.join(cols)

    conn.execute(
        f'INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})',
        values,
    )
    conn.commit()

    # Read-back verify
    pk_val = row[pk_col]
    readback = conn.execute(
        f'SELECT {pk_col} FROM {table} WHERE {pk_col} = ?', (pk_val,)
    ).fetchone()

    if readback is None:
        raise RuntimeError(
            f'db_upsert: read-back failed for {table}.{pk_col}={pk_val!r} — row not found after INSERT'
        )

    if readback[0] != pk_val:
        raise RuntimeError(
            f'db_upsert: read-back mismatch for {table}.{pk_col}: '
            f'wrote {pk_val!r}, got {readback[0]!r}'
        )


# ── Pre-scrape sample check ───────────────────────────────────────────────────

def pre_scrape_check(source, sample_size=5, validator=None, label='data'):
    """
    Before a scrape run, validate a random sample of existing data.

    Args:
      source      pathlib.Path to existing JSON file, OR list/dict of records
      sample_size how many records to check
      validator   callable(record) → None, raises on failure
                  defaults to checking record is a non-empty dict
      label       name for log messages

    Returns:
      int  number of records checked

    Raises:
      RuntimeError if any sample record fails validation
    """
    # Load records
    if isinstance(source, (str, Path)):
        p = Path(source)
        if not p.exists():
            print(f'  [pre-check] {label}: no existing file, skipping sample check', flush=True)
            return 0
        raw = json.loads(p.read_text(encoding='utf-8'))
        # Support top-level dict of records OR list
        if isinstance(raw, dict):
            # Try common wrapper keys
            for key in ('riders', 'races', 'stages', 'items'):
                if key in raw and isinstance(raw[key], (dict, list)):
                    raw = raw[key]
                    break
        if isinstance(raw, dict):
            records = list(raw.values())
        else:
            records = list(raw)
    elif isinstance(source, dict):
        records = list(source.values())
    else:
        records = list(source)

    if not records:
        print(f'  [pre-check] {label}: no existing records to sample', flush=True)
        return 0

    n = min(sample_size, len(records))
    sample = random.sample(records, n)

    if validator is None:
        def validator(rec):
            if not isinstance(rec, dict) or not rec:
                raise ValueError(f'record is empty or not a dict: {rec!r}')

    failed = []
    for rec in sample:
        try:
            validator(rec)
        except Exception as e:
            slug = rec.get('slug', rec.get('name', '?')) if isinstance(rec, dict) else '?'
            failed.append(f'{slug}: {e}')

    if failed:
        msg = f'[pre-check] {label}: {len(failed)}/{n} sample records failed validation:\n'
        msg += '\n'.join(f'  • {f}' for f in failed)
        raise RuntimeError(msg)

    print(f'  [pre-check] {label}: {n} random records OK ✓', flush=True)
    return n


# ── Schema migration ──────────────────────────────────────────────────────────

def ensure_schema(conn: sqlite3.Connection):
    """
    Add any columns that scrapers need but may not exist yet.
    Safe to call on every run — uses ALTER TABLE IF NOT EXISTS pattern.
    """
    additions = {
        'riders': [
            ('wins_json',           'TEXT'),
            ('team_history_json',   'TEXT'),
            ('season_results_json', 'TEXT'),
            ('photo_url',           'TEXT'),  # already exists but just in case
        ],
        'stages': [
            ('map_img',      'TEXT'),
            ('profile_img',  'TEXT'),
            ('roadbook_json','TEXT'),
            ('start_time',   'TEXT'),
            ('description',  'TEXT'),
        ],
    }

    existing = {}
    for table in additions:
        cols = conn.execute(f'PRAGMA table_info({table})').fetchall()
        existing[table] = {c[1] for c in cols}

    for table, cols in additions.items():
        for col_name, col_type in cols:
            if col_name not in existing[table]:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {col_name} {col_type}')
                print(f'  [schema] Added {table}.{col_name} ({col_type})', flush=True)

    conn.commit()
