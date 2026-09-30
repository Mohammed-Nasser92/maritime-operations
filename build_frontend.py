"""Build a standalone index.html using local source and vendored Leaflet 1.9.4."""
from pathlib import Path
import re
root=Path(__file__).resolve().parent
html=(root/'web/shell.html').read_text(encoding='utf-8')
for marker,path in [('LEAFLET_CSS','vendor/leaflet.css'),('APP_CSS','web/styles.css'),('LEAFLET_JS','vendor/leaflet.js'),('APP_JS','web/app.js')]:
    source=(root/path).read_text(encoding='utf-8')
    source=re.sub(r'//# sourceMappingURL=.*','',source)
    html=html.replace('/*'+marker+'*/',source)
(root/'index.html').write_text(html,encoding='utf-8')
print('Built index.html')
