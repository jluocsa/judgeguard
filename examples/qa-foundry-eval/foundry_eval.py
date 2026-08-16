"""Upload a judgeguard dataset to the Foundry Evaluations service and score it.

The pattern here follows `scripts/foundry_eval.py` in CSA Workbench, which is the
only version of this known to work end to end against a real project. What differs
is where the criteria come from: judgeguard's coverage map builds them, so each
evaluator is pointed at the row field it actually reads rather than at a hand-kept
mapping that drifts.

Nothing this script produces can change an exit code. `judgeguard gate` has already
decided that, and its verdict is carried on every row so the two gradings can be read
side by side.

    judgeguard emit-dataset --corpus corpus/qa-pod --out .foundry
    python foundry_eval.py --dry-run
    python foundry_eval.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from judgeguard.scorers.foundry import coverage


def resolve_judge() -> str:
    """Return the judge deployment, refusing to let it grade its own transcripts.

    A judge scoring output from the deployment that produced it is not an independent
    second opinion, so this is a hard stop rather than a warning. judgeguard enforces
    the same rule for its in-process scorer; it has to hold on the upload path too, or
    the guarantee is only as good as which route you happened to take.
    """
    candidate = os.environ.get("JUDGEGUARD_CANDIDATE_DEPLOYMENT", "").strip()
    judge = os.environ.get("FOUNDRY_JUDGE_DEPLOYMENT", "").strip()
    if not judge:
        raise SystemExit(
            "FOUNDRY_JUDGE_DEPLOYMENT is required: name a judge deployment that is "
            "not the deployment under test."
        )
    if candidate and judge == candidate:
        raise SystemExit(
            f"FOUNDRY_JUDGE_DEPLOYMENT '{judge}' is the deployment under test; "
            "the advisory judge must be a different deployment."
        )
    return judge


def load_rows(dataset: Path) -> list[dict]:
    if not dataset.exists():
        raise SystemExit(
            f"no dataset at {dataset}. Run:\n"
            "  judgeguard emit-dataset --corpus corpus/qa-pod --out .foundry"
        )
    return [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=".foundry/dataset.jsonl")
    parser.add_argument("--name", default="ida-qa-eval")
    parser.add_argument("--stable-only", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be sent and contact nothing",
    )
    arguments = parser.parse_args()

    rows = load_rows(Path(arguments.dataset))
    criteria = coverage.testing_criteria(
        os.environ.get("FOUNDRY_JUDGE_DEPLOYMENT", "<judge>"),
        stable_only=arguments.stable_only,
    )

    if arguments.dry_run:
        print(f"{len(rows)} rows, {len(criteria)} evaluators\n")
        print(f"  {'dimension':<26}{'service evaluator':<32}reads")
        for item in criteria:
            reads = ", ".join(
                source.strip("{} ").replace("item.", "")
                for source in item["data_mapping"].values()
            )
            print(f"  {item['name']:<26}{item['evaluator_name']:<32}{reads}")
        gated = sum(1 for r in rows if r.get("gate_pass"))
        print(f"\ngate verdict, already decided: {gated}/{len(rows)} passed")
        print("Uploading cannot change it. The scores land in the advisory lane.")
        return 0

    judge = resolve_judge()
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        raise SystemExit("FOUNDRY_PROJECT_ENDPOINT is required")

    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise SystemExit(
            "needs the project SDK: pip install azure-ai-projects azure-identity"
        ) from exc

    client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    print(f"rows:   {len(rows)}")
    print(f"judge:  {judge}")

    uploaded = client.datasets.upload_file(
        name=arguments.name, version=str(int(time.time())), file_path=arguments.dataset
    )
    evaluation = client.evaluations.create(
        name=arguments.name,
        data_source={"type": "dataset", "id": uploaded.id},
        testing_criteria=criteria,
    )
    print(f"run:    {evaluation.id}")
    print("\nScores land in the advisory lane. They cannot change what the")
    print("deterministic gate already decided, which rides on every row.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
