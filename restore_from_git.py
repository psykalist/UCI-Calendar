"""
restore_from_git.py — restores SMB-truncated files from last git commit.
Run on Windows: python restore_from_git.py
"""
import os, sys, subprocess, tempfile

BASE = os.path.dirname(os.path.abspath(__file__))

RESTORE = ["index.html", "data.json"]

def safe_write(dest, content_bytes):
    suffix = os.path.splitext(dest)[1]
    fd, tmp = tempfile.mkstemp(suffix=suffix, dir=os.path.dirname(dest))
    os.close(fd)
    with open(tmp, "wb") as f:
        f.write(content_bytes)
    os.replace(tmp, dest)
    print(f"  ✓ Wrote {os.path.basename(dest)} ({len(content_bytes):,} bytes)", flush=True)

errors = 0
for fname in RESTORE:
    dest = os.path.join(BASE, fname)
    print(f"\nRestoring {fname} from git HEAD...", flush=True)
    r = subprocess.run(
        ["git", "show", f"HEAD:{fname}"],
        capture_output=True,
        cwd=BASE
    )
    if r.returncode != 0:
        print(f"  ✗ git show failed: {r.stderr.decode()[:200]}", flush=True)
        errors += 1
        continue
    # Normalise to LF so Windows CRLF doesn't double-expand
    content = r.stdout
    before = len(content)
    safe_write(dest, content)

    # Verify
    on_disk = os.path.getsize(dest)
    if on_disk < before * 0.95:
        print(f"  ✗ Size mismatch after write: wrote {before} but disk shows {on_disk}", flush=True)
        errors += 1
    else:
        print(f"  ✓ Size OK ({on_disk:,} bytes on disk)", flush=True)

print(flush=True)
if errors:
    print(f"✗ {errors} file(s) failed — check git status", flush=True)
    sys.exit(1)
else:
    print("✓ All files restored. Run pre_push_check.py to verify, then push.", flush=True)
