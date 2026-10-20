"""Inline sample/manifest.json and sample/memories.json into deck.html."""
import json
from pathlib import Path

HERE = Path(__file__).parent
template = (HERE / "deck.template.html").read_text()
for name in ("manifest", "memories"):
    data = json.loads((HERE / "sample" / f"{name}.json").read_text())
    # "</" can't appear raw inside a <script> block.
    template = template.replace(f"/*{name.upper()}*/", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
(HERE / "deck.html").write_text(template)
print("wrote deck.html")
