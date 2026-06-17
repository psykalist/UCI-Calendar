"""diagnose_js.py — finds and fixes the JS syntax error in index.html"""
import os, re, subprocess, tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(BASE, "index.html")

with open(HTML, encoding="utf-8", errors="replace") as f:
    html = f.read()

m = re.search(r'<script>(.*?)</script>', html, re.DOTALL)
if not m:
    print("ERROR: no <script>...</script> block found")
    exit(1)

js = m.group(1)
lines = js.split('\n')
print(f"JS block: {len(lines)} lines, {len(js):,} chars")

# Write to temp and get node error
fd, tmp = tempfile.mkstemp(suffix='.js')
os.close(fd)
with open(tmp, 'w', encoding='utf-8') as f:
    f.write(js)
r = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
print("Node output:", r.stderr.strip() if r.stderr else "OK")

# Find the error line
err_match = re.search(r':(\d+)', r.stderr or '')
if err_match:
    err_line = int(err_match.group(1))
    print(f"\nContext around line {err_line}:")
    for i in range(max(0, err_line-4), min(len(lines), err_line+3)):
        marker = " >>>" if i == err_line-1 else "    "
        print(f"{marker} {i+1:4d}: {repr(lines[i])}")

os.unlink(tmp)
