"""
repair_index.py — fixes truncated index.html by appending the missing tail.
Run once from the project folder: python repair_index.py
"""
import os, sys, tempfile, urllib.request

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

# The tail that's always been cut off by SMB truncation.
# Picks up from where the file ends: +'<butto  (inside fModal)
TAIL = r"""n id="fModalOk" style="flex:1;padding:10px;background:var(--upcoming);border:none;border-radius:8px;color:#fff;font-weight:700;cursor:pointer">'+(confirmLabel||'OK')+'</button>'
    :'<button onclick="this.closest(\'[data-modal]\').remove()" style="width:100%;padding:10px;background:var(--upcoming);border:none;border-radius:8px;color:#fff;font-weight:700;cursor:pointer">'+(confirmLabel||'Close')+'</button>';
  box.innerHTML=
    '<div style="font-weight:700;font-size:1rem;margin-bottom:12px">'+title+'</div>'
   +'<div style="font-size:.88rem;line-height:1.5;color:var(--muted);margin-bottom:16px">'+body+'</div>'
   +'<div style="display:flex;gap:8px">'+btns+'</div>';
  box.setAttribute('data-modal','1');
  const overlay=document.createElement('div');
  overlay.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9998';
  document.body.append(overlay,box);
  const close=()=>{overlay.remove();box.remove();};
  overlay.addEventListener('click',close);
  const cancelBtn=box.querySelector('#fModalCancel');
  if(cancelBtn) cancelBtn.addEventListener('click',close);
  const okBtn=box.querySelector('#fModalOk');
  if(okBtn) okBtn.addEventListener('click',()=>{if(onConfirm)onConfirm();close();});
  return box;
}

// ── Service Worker ─────────────────────────────────────────────────────────
if('serviceWorker' in navigator){
  navigator.serviceWorker.register('./sw.js').catch(e=>console.warn('SW:',e));
}
</script>
</body>
</html>
"""

print(f"Reading {TARGET} ...", flush=True)
with open(TARGET, encoding="utf-8", errors="replace") as f:
    src = f.read()

print(f"  Current size: {len(src):,} bytes", flush=True)

# Find the truncation point
CUT = "+'<butto"
idx = src.rfind(CUT)
if idx == -1:
    print("ERROR: truncation marker not found — file may already be complete or differently truncated.")
    sys.exit(1)

print(f"  Truncation found at byte {idx:,}", flush=True)
fixed = src[:idx] + TAIL
print(f"  Fixed size: {len(fixed):,} bytes", flush=True)

# Write safely via temp file
fd, tmp = tempfile.mkstemp(suffix=".html", dir=os.path.dirname(TARGET))
os.close(fd)
with open(tmp, "w", encoding="utf-8") as f:
    f.write(fixed)
os.replace(tmp, TARGET)

print("index.html repaired!", flush=True)
print("Now run: bash git-push.sh \"fix: repair truncated index.html (v20)\"", flush=True)
