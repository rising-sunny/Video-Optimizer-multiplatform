import hashlib
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path[:0] = ["/tmp/video-recuperacion-shorts-v44", "/opt/video-agent-mcp"]
import shorts_handoff as parser

class Pairs(list):
    pass

# Preserve every occurrence for inspection; no recovered plan is saved or used.
parser._pairs = Pairs
batch = "fa402b8286c149e698875a48b471977c"
root = Path("/home/videoagent/video-automation/runtime/deepseek-ledger/catarsis") / batch

def clean(value):
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[oculto]", value)
    text = re.sub(r"(?i)Bearer\s+\S+", "Bearer [oculto]", text)
    return re.sub(r'https?://[^\s"<>]+', "[URL]", text)

def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def inspect(value, path, duplicates):
    if isinstance(value, Pairs):
        result = {}
        for key, item in value:
            location = path + "/" + key.replace("~", "~0").replace("/", "~1")
            item = inspect(item, location, duplicates)
            if key in result:
                old, new = encoded(result[key]), encoded(item)
                position = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
                duplicates.append({
                    "path": location, "identical_values": old == new,
                    "earlier_characters": len(old), "later_characters": len(new),
                    "earlier_sha256": hashlib.sha256(old.encode()).hexdigest(),
                    "later_sha256": hashlib.sha256(new.encode()).hexdigest(),
                    "earlier_context": clean(old[max(0, position-120):position+380]),
                    "later_context": clean(new[max(0, position-120):position+380])
                })
            result[key] = item
        return result
    if isinstance(value, list):
        return [inspect(item, path + "/" + str(i), duplicates) for i, item in enumerate(value)]
    return value

for channel, output in (
    ("stunning-facts-of-history", "editorial-plan-autonomy-2.json"),
    ("stunning-revelations", "editorial-plan.json")
):
    folder = root / channel
    for path in sorted(folder.glob("invalid-handoff-*.json")):
        if path.is_symlink():
            continue
        saved = json.loads(path.read_text())
        if saved.get("output") != output:
            continue
        report = {"channel": channel, "output": output, "read_only": True, "ai_requests": 0}
        try:
            value, changes = parser.parse(saved["provider_content"])
            duplicates = []
            inspect(value, "", duplicates)
            report.update(syntax_repairs=changes, duplicate_count=len(duplicates), duplicates=duplicates[:40])
        except Exception as exc:
            report.update(parse_error=clean(str(exc))[:250])
        budget = folder / "budget.json"
        if budget.is_file() and not budget.is_symlink():
            report["counts"] = json.loads(budget.read_text()).get("counts")
        print(json.dumps(report, indent=2, ensure_ascii=False))
