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
from datetime import datetime, timezone
from pathlib import Path

from judgeguard.scorers.foundry import coverage

POLL_SECONDS = 5

# Describes the rows `judgeguard emit-dataset` writes. Both payload shapes are
# declared because both are on every row: the string fields feed the RAG evaluators
# and the *_messages arrays feed the agent evaluators.
ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "item_id": {"type": "string"},
        "query": {"type": "string"},
        "response": {"type": "string"},
        "context": {"type": "string"},
        "ground_truth": {"type": "string"},
        "query_messages": {"type": "array"},
        "response_messages": {"type": "array"},
        "tool_calls": {"type": "array"},
        "tool_definitions": {"type": "array"},
        "retrieved_documents": {"type": "array"},
        "retrieval_ground_truth": {"type": "array"},
        "gate_verdict": {"type": "string"},
        "gate_pass": {"type": "boolean"},
        "evidence_level": {"type": "string"},
    },
    "required": [],
}


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
        from openai.types.eval_create_params import DataSourceConfigCustom
        from openai.types.evals.create_eval_jsonl_run_data_source_param import (
            CreateEvalJSONLRunDataSourceParam,
            SourceFileID,
        )
    except ImportError as exc:
        raise SystemExit(
            "needs the project SDK: pip install azure-ai-projects azure-identity openai"
        ) from exc

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"rows:   {len(rows)}")
    print(f"judge:  {judge}")

    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=endpoint, credential=credential) as project,
        project.get_openai_client() as openai_client,
    ):
        print("\nuploading dataset...")
        uploaded = project.datasets.upload_file(
            name=f"{arguments.name}-data-{stamp}",
            version="1",
            file_path=str(arguments.dataset),
        )
        print(f"  dataset id: {uploaded.id}")

        print("creating evaluation...")
        evaluation = openai_client.evals.create(
            name=f"{arguments.name}-eval",
            data_source_config=DataSourceConfigCustom(
                {
                    "type": "custom",
                    "item_schema": ITEM_SCHEMA,
                    "include_sample_schema": True,
                }
            ),
            testing_criteria=criteria,
        )
        print(f"  eval id: {evaluation.id}")

        print("starting run...")
        run = openai_client.evals.runs.create(
            eval_id=evaluation.id,
            name=f"{arguments.name}-{stamp}",
            data_source=CreateEvalJSONLRunDataSourceParam(
                type="jsonl", source=SourceFileID(type="file_id", id=uploaded.id)
            ),
        )
        print(f"  run id: {run.id}")

        while run.status not in ("completed", "failed"):
            time.sleep(POLL_SECONDS)
            run = openai_client.evals.runs.retrieve(
                run_id=run.id, eval_id=evaluation.id
            )
            print(f"  status: {run.status}")

        print(f"\nstatus:     {run.status}")
        print(f"report URL: {getattr(run, 'report_url', '(none returned)')}")
        if run.status != "completed":
            return 1

    print("\nScores land in the advisory lane. They cannot change what the")
    print("deterministic gate already decided, which rides on every row.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
