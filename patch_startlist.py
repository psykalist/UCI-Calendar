"""
patch_startlist.py — fixes scrape_startlist() to match actual PCS page structure.
Run once from the project folder: python patch_startlist.py
"""
import os, sys, tempfile

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraper.py")

OLD = '''def scrape_startlist(cf_slug, year):
    """
    Fetch the PCS startlist for a race. Returns list of {name, slug, nat, team} dicts.
    Returns [] if not available.
    """
    pcs_slug = _pcs_slug(cf_slug)
    url = f"{PCS_BASE}/race/{pcs_slug}/{year}/startlist"
    html = fetch(url)
    if not html:
        return []

    entries = []
    seen = set()

    # Team blocks: <b>Team Name</b> ... <ul class="riders">...</ul>
    team_blocks = re.findall(
        r\'<b>([^<]{3,60})</b>.*?<ul[^>]*class="[^"]*riders[^"]*"[^>]*>(.*?)</ul>\',
        html, re.DOTALL
    )

    if not team_blocks:
        # Fallback: grab all rider profile links
        for slug_r, name in re.findall(r\'href="/rider/([a-z0-9-]+)"[^>]*>\\s*<span[^>]*>([^<]+)</span>\', html):
            name = name.strip()
            if name and name not in seen:
                seen.add(name)
                entries.append({\'name\': name, \'slug\': slug_r, \'nat\': \'\', \'team\': \'\'})
        return entries

    for team_name, riders_html in team_blocks:
        team_name = re.sub(r\'\\s+\', \' \', team_name).strip()
        for item in re.findall(r\'href="/rider/([a-z0-9-]+)"[^>]*>\\s*<span[^>]*>([^<]+)</span>\', riders_html):
            slug_r, name = item[0].strip(), item[1].strip()
            # Try to find nat flag nearby
            nat_m = re.search(rf\'/svg/flags/(\\w+)\\.svg\', riders_html)
            nat = nat_m.group(1).lower() if nat_m else \'\'
            if name and name not in seen:
                seen.add(name)
                entries.append({\'name\': name, \'slug\': slug_r, \'nat\': nat, \'team\': team_name})

    return entries'''

NEW = '''def scrape_startlist(cf_slug, year):
    """
    Fetch the PCS startlist for a race. Returns list of {name, slug, nat, team} dicts.
    Returns [] if not available.

    PCS startlist page structure (2025+):
      <div class="ridersCont">
        <div>...<a class="team" href="team/SLUG">TEAM NAME</a>...</div>
        <ul>
          <li><span class="bib">1</span><span class="flag si"></span>
              <a href="rider/tadej-pogacar">POGAČAR Tadej</a></li>
          ...
        </ul>
      </div>
    """
    pcs_slug = _pcs_slug(cf_slug)
    url = f"{PCS_BASE}/race/{pcs_slug}/{year}/startlist"
    html = fetch(url)
    if not html:
        return []

    entries = []
    seen = set()

    # Split on each ridersCont block (one per team)
    blocks = re.split(r\'<div[^>]+class="ridersCont"\', html)

    for block in blocks[1:]:
        # Team name from <a class="team" ...>TEAM NAME</a>
        team_m = re.search(r\'class="team"[^>]*>([^<]+)</a>\', block)
        team_name = re.sub(r\'\\s+\', \' \', team_m.group(1)).strip() if team_m else \'\'

        # Each rider: <span class="flag XX"></span><a href="rider/SLUG">NAME</a>
        for nat, slug_r, name in re.findall(
            r\'class="flag (\\w+)"></span>\\s*<a href="rider/([^"]+)">([^<]+)</a>\',
            block
        ):
            name = name.strip()
            if name and name not in seen:
                seen.add(name)
                entries.append({
                    \'name\': name,
                    \'slug\': slug_r,
                    \'nat\':  nat.lower(),
                    \'team\': team_name,
                })

    if not entries:
        # Fallback: any rider link on the page (no nat info)
        for slug_r, name in re.findall(r\'href="rider/([a-z0-9-]+)">([^<]+)</a>\', html):
            name = name.strip()
            if name and name not in seen and len(name) > 3:
                seen.add(name)
                entries.append({\'name\': name, \'slug\': slug_r, \'nat\': \'\', \'team\': \'\'})

    return entries'''

print(f"Reading {TARGET} ...", flush=True)
with open(TARGET, encoding="utf-8") as f:
    src = f.read()

if OLD not in src:
    print("ERROR: old function not found — already patched or file differs", flush=True)
    sys.exit(1)

patched = src.replace(OLD, NEW, 1)

# Write via temp file to avoid SMB truncation
fd, tmp = tempfile.mkstemp(suffix=".py", dir=os.path.dirname(TARGET))
os.close(fd)
with open(tmp, "w", encoding="utf-8") as f:
    f.write(patched)
os.replace(tmp, TARGET)

print("scraper.py patched successfully!", flush=True)
print("Now run: python scraper.py", flush=True)
