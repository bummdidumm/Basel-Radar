import json
from pathlib import Path

def main():
    root = Path("bummdidumm_os_v5_final_release/20_index/published")
    records_file = root / "01_record_index.jsonl"
    entities_file = root / "02_entity_index.jsonl"

    out_dir = root / "14_embed_ready"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / "records_for_embedding.jsonl"
    schema_file = out_dir / "embed_schema.json"

    schema = {
        "schema_version": "1.0",
        "templates": {
            "record": "{date}: {title}. Category: {record_type}.",
            "entity": "{entity_type}: {name}. {attributes}"
        }
    }
    with open(schema_file, "w") as f:
        json.dump(schema, f, indent=2)

    lines_out = []

    if records_file.exists():
        for line in records_file.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            rec = json.loads(line)
            if rec.get("exclude_from_context"): continue

            text = schema["templates"]["record"].format(
                date=rec.get("event_date", "Unknown Date"),
                title=rec.get("title", "Unknown"),
                record_type=rec.get("record_type", "unknown")
            )
            lines_out.append(json.dumps({
                "id": rec["record_id"],
                "text": text,
                "metadata": {"date": rec.get("event_date"), "record_type": rec.get("record_type"), "tier": rec.get("knowledge_tier"), "source_id": rec.get("source_id")}
            }))

    if entities_file.exists():
        for line in entities_file.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            ent = json.loads(line)
            if ent.get("exclude_from_context") or ent.get("is_stale"): continue

            text = schema["templates"]["entity"].format(
                entity_type=ent.get("entity_type", "unknown").capitalize(),
                name=ent.get("display_name", "Unknown"),
                attributes=json.dumps(ent.get("attributes", {}))
            )
            lines_out.append(json.dumps({
                "id": ent["entity_id"],
                "text": text,
                "metadata": {"entity_type": ent.get("entity_type"), "tier": ent.get("knowledge_tier"), "canonical_entity_id": ent.get("canonical_entity_id")}
            }))

    with open(out_file, "w") as f:
        f.write("\n".join(lines_out) + "\n")

if __name__ == "__main__":
    main()
