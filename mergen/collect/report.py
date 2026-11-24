"""Sistem raporu dışa aktarımı: TXT / HTML / JSON. strip=True (varsayılan) kişisel bilgileri çıkarır."""
import copy
import datetime
import html
import json

from .. import __version__
from . import fmt


def _strip(data, only_hidden=False):
    """Kişisel satırları "(çıkarıldı)" yapar. only_hidden: yalnızca ekranda gizli olanlar (Kopyala için)."""
    d = copy.deepcopy(data)
    for s in d.get("sections", []):
        for rows in [s.get("rows", [])] + [g.get("rows", []) for g in s.get("groups", [])]:
            for r in rows:
                if (r.get("s") is True) if only_hidden else r.get("s"):
                    r["v"] = fmt.K("removed") if r.get("v") not in (None, "") else None
    return d


def _items(data, t):
    """(bölüm başlığı, [(grup başlığı | None, rozet, [(etiket, metin)])])"""
    for s in data.get("sections", []):
        blocks = []
        rows = [(fmt.label(r, t), fmt.text(r.get("v"), t)) for r in s.get("rows", [])]
        if rows:
            blocks.append((None, None, rows))
        for g in s.get("groups", []):
            blocks.append((fmt.text(g.get("title"), t), fmt.text(g["badge"], t) if g.get("badge") else None,
                           [(fmt.label(r, t), fmt.text(r.get("v"), t)) for r in g.get("rows", [])]))
        yield t("sec_" + s["id"]), blocks


def to_text(data, t, strip=True):
    if strip:
        data = _strip(data)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"{t('report_title')} — mergen {__version__}", f"{t('report_generated')}: {now}", ""]
    for title, blocks in _items(data, t):
        up = title.replace("i", "İ").upper() if t("yes") == "Evet" else title.upper()   # Türkçe büyük harf
        out += [up, "=" * len(up)]
        for gtitle, badge, rows in blocks:
            indent = ""
            if gtitle is not None:
                out.append(f"  {gtitle}" + (f"  [{badge}]" if badge else ""))
                indent = "  "
            width = max((len(k) for k, _ in rows), default=0)
            for k, v in rows:
                out.append(f"{indent}  {k.ljust(width)}  {v}")
        out.append("")
    return "\n".join(out)


def section_text(section, t):
    """Tek kart için "Kopyala" metni (kişisel bilgiler gizli değilse olduğu gibi)."""
    return to_text({"sections": [section]}, t, strip=False).split("\n", 3)[3].strip()


def to_html(data, t, strip=True):
    if strip:
        data = _strip(data)
    e = html.escape
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [f"""<!doctype html><html lang="{'tr' if t('yes') == 'Evet' else 'en'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(t('report_title'))}</title>
<style>
:root {{ --bg:#fff; --card:#f6f6f6; --text:#0f0f0f; --muted:#606060; --line:rgba(0,0,0,.08); }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#000; --card:#141414; --text:#f1f1f1; --muted:#aaa; --line:rgba(255,255,255,.1); }} }}
body {{ background:var(--bg); color:var(--text); font:14px/1.45 "Segoe UI",system-ui,sans-serif; margin:0; padding:24px 16px; }}
main {{ max-width:980px; margin:0 auto; }}
h1 {{ font-size:24px; margin:0 0 4px; }} .muted {{ color:var(--muted); }}
section {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 18px; margin:16px 0; }}
h2 {{ font-size:17px; margin:0 0 8px; }} h3 {{ font-size:14px; margin:14px 0 4px; }}
.badge {{ font-size:11px; font-weight:600; border:1px solid var(--line); border-radius:8px; padding:1px 7px; margin-left:6px; color:var(--muted); }}
table {{ border-collapse:collapse; width:100%; }} td {{ padding:3px 0; vertical-align:top; border-top:1px solid var(--line); }}
td:first-child {{ color:var(--muted); width:38%; padding-right:12px; }}
</style></head><body><main>
<h1>{e(t('report_title'))}</h1><div class="muted">mergen {e(__version__)} · {e(t('report_generated'))}: {e(now)}</div>"""]
    for title, blocks in _items(data, t):
        parts.append(f"<section><h2>{e(title)}</h2>")
        for gtitle, badge, rows in blocks:
            if gtitle is not None:
                parts.append(f"<h3>{e(gtitle)}" + (f'<span class="badge">{e(badge)}</span>' if badge else "") + "</h3>")
            if rows:
                parts.append("<table>" + "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in rows)
                             + "</table>")
        parts.append("</section>")
    parts.append("</main></body></html>")
    return "\n".join(parts)


def to_json(data, t, strip=True):
    """Hem ham değerler hem de okunur metin (makine + insan için)."""
    if strip:
        data = _strip(data)
    out = {"app": "mergen", "version": __version__, "generated": datetime.datetime.now().isoformat(timespec="seconds"),
           "collected": data.get("collected"), "sections": []}
    for s in data.get("sections", []):
        def conv(rows):
            return [{"key": r.get("l") or r["k"], "label": fmt.label(r, t), "text": fmt.text(r.get("v"), t),
                     "value": r.get("v"), **({"personal": True} if r.get("s") else {})} for r in rows]
        out["sections"].append({
            "id": s["id"], "title": t("sec_" + s["id"]), "rows": conv(s.get("rows", [])),
            "groups": [{"title": fmt.text(g.get("title"), t), "rows": conv(g.get("rows", []))}
                       for g in s.get("groups", [])]})
    return json.dumps(out, ensure_ascii=False, indent=2)


WRITERS = {"txt": to_text, "html": to_html, "json": to_json}


def write(path, kind, data, t, strip=True):
    text = WRITERS[kind](data, t, strip)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path
