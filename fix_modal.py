"""fix_modal.py — fixes the broken fModal string on line 1393 of index.html"""
import os, re, subprocess, tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(BASE, "index.html")

with open(HTML, encoding="utf-8", errors="replace") as f:
    src = f.read()

OLD = '     n id="fModalOk"'
NEW = '     +\'<button id="fModalOk"'

if OLD not in src:
    print("ERROR: pattern not found — already fixed?")
    exit(1)

fixed = src.replace(OLD, NEW, 1)
print(f"Fixed line 1393", flush=True)

# Validate JS after fix
m = re.search(r'<script>(.*?)</script>', fixed, re.DOTALL)
if m:
    fd, tmp = tempfile.mkstemp(suffix='.js')
    os.close(fd)
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(m.group(1))
    r = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
    os.unlink(tmp)
    if r.returncode == 0:
        print("JavaScript syntax OK", flush=True)
    else:
        print("Still broken:", r.stderr.strip()[:200], flush=True)
        exit(1)

fd, tmp = tempfile.mkstemp(suffix='.html', dir=BASE)
os.close(fd)
with open(tmp, 'w', encoding='utf-8') as f:
    f.write(fixed)
os.replace(tmp, HTML)
print(f"Saved ({len(fixed):,} bytes)", flush=True)
print('\nNow run: bash git-push.sh "fix: fModal syntax error (v20)"', flush=True)
