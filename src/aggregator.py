from collections import defaultdict


def aggregate_by_owner(detections: list) -> dict:
    """Groups results: owner -> file -> list of detections"""
    owners = defaultdict(lambda: defaultdict(list))

    for d in detections:
        owner = d.get("owner", "unknown")
        file_path = d.get("file_path", "unknown")
        owners[owner][file_path].append({
            "pattern": d.get("pattern_name"),
            "match": d.get("matched_value"),
            "line": d.get("match_line_number"),
            "is_credentials": d.get("is_credentials"),
            "status": d.get("status"),
            "confidence": round(d.get("confidence", 0), 2),
            "reasoning": d.get("reasoning"),
            "evidence": d.get("evidence", d.get("indicators", [])),
            "indicators": d.get("indicators", d.get("evidence", [])),
            "agent_trace": d.get("agent_trace", {}),
            "json_valid": d.get("json_valid", True),
        })

    return build_report(owners)


def build_report(owners: dict) -> dict:
    report = {}
    for owner, files in owners.items():
        total = sum(len(v) for v in files.values())
        real = sum(1 for v in files.values() for d in v if d["status"] == "REAL")
        review = sum(1 for v in files.values() for d in v if d["status"] == "REVIEW")
        credentials = sum(1 for v in files.values() for d in v if d.get("is_credentials") == 1)
        json_invalid = sum(1 for v in files.values() for d in v if not d.get("json_valid", True))

        report[owner] = {
            "summary": {
                "total_detections": total,
                "credentials": credentials,
                "non_credentials": total - credentials,
                "real": real,
                "review": review,
                "false_positive": total - real - review,
                "json_invalid": json_invalid,
            },
            "files": dict(files),
        }
    return report
