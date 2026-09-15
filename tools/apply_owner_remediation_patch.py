from __future__ import annotations

from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"patch pattern missing in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def patch_store() -> None:
    path = "server/app/platform_store.py"
    replace(
        path,
        """    def list_run_events_by_types(\n        self,\n        run_id: str,\n        event_types: tuple[str, ...],\n""",
        """    def iter_run_events_frozen(\n        self,\n        run_id: str,\n        organization_id: str | None = None,\n        *,\n        batch_size: int = 1_000,\n    ) -> Iterator[tuple[int, list[dict[str, Any]]]]:\n        \"\"\"Yield events bounded by one MAX(sequence) read on the same connection.\n\n        The connection stays open for the complete iteration. Events appended by\n        concurrent writers after the cutoff are excluded from this evidence snapshot.\n        \"\"\"\n        normalized_batch_size = max(100, min(int(batch_size or 1_000), 10_000))\n        with self._connect() as db:\n            if organization_id:\n                run_row = db.execute(\n                    \"SELECT organization_id FROM runs WHERE id=? AND organization_id=?\",\n                    (run_id, organization_id),\n                ).fetchone()\n            else:\n                run_row = db.execute(\n                    \"SELECT organization_id FROM runs WHERE id=?\",\n                    (run_id,),\n                ).fetchone()\n            if not run_row:\n                return\n            run_organization_id = str(run_row[\"organization_id\"] or \"org_jianghu\")\n            cutoff_row = db.execute(\n                \"SELECT COALESCE(MAX(sequence),0) AS value FROM events \"\n                \"WHERE run_id=? AND organization_id=?\",\n                (run_id, run_organization_id),\n            ).fetchone()\n            frozen_cutoff = int(_row_value(cutoff_row, \"value\") or 0)\n            cursor = db.execute(\n                \"SELECT * FROM events WHERE run_id=? AND organization_id=? \"\n                \"AND sequence<=? ORDER BY sequence\",\n                (run_id, run_organization_id, frozen_cutoff),\n            )\n            emitted = False\n            while True:\n                rows = cursor.fetchmany(normalized_batch_size)\n                if not rows:\n                    break\n                emitted = True\n                yield frozen_cutoff, [self._event_json(row) for row in rows]\n            if not emitted:\n                yield frozen_cutoff, []\n\n    def list_run_events_by_types(\n        self,\n        run_id: str,\n        event_types: tuple[str, ...],\n""",
    )
    replace(
        path,
        """    def append_run_event(self, run_id: str, type_: str, category: str, title: str, summary: str, payload: dict[str, Any] | None = None) -> None:\n        with self._connect() as db:\n            self._event(db, run_id, type_, category, title, summary, payload or {})\n""",
        """    def append_run_event(self, run_id: str, type_: str, category: str, title: str, summary: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:\n        with self._connect() as db:\n            return self._event(db, run_id, type_, category, title, summary, payload or {})\n""",
    )
    replace(
        path,
        """    def _event(self, db: sqlite3.Connection, run_id: str, type_: str, category: str, title: str, summary: str, payload: dict[str, Any] | None = None) -> None:\n        sequence_row = db.execute(\"SELECT COALESCE(MAX(sequence),0)+1 AS value FROM events WHERE run_id=?\", (run_id,)).fetchone()\n        sequence = int(_row_value(sequence_row, \"value\"))\n        run_row = db.execute(\"SELECT organization_id FROM runs WHERE id=?\", (run_id,)).fetchone()\n        organization_id = str(_row_value(run_row, \"organization_id\") or \"org_jianghu\")\n        now = utc_now()\n        db.execute(\"INSERT INTO events(id,run_id,organization_id,sequence,type,category,title,summary,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)\", (new_id(\"evt\"), run_id, organization_id, sequence, type_, category, title, summary, json.dumps(payload or {}), now))\n        db.execute(\"UPDATE runs SET updated_at=? WHERE id=?\", (now, run_id))\n""",
        """    def _event(self, db: _DatabaseConnection, run_id: str, type_: str, category: str, title: str, summary: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:\n        sequence_row = db.execute(\"SELECT COALESCE(MAX(sequence),0)+1 AS value FROM events WHERE run_id=?\", (run_id,)).fetchone()\n        sequence = int(_row_value(sequence_row, \"value\"))\n        run_row = db.execute(\"SELECT organization_id FROM runs WHERE id=?\", (run_id,)).fetchone()\n        organization_id = str(_row_value(run_row, \"organization_id\") or \"org_jianghu\")\n        now = utc_now()\n        event_id = new_id(\"evt\")\n        db.execute(\"INSERT INTO events(id,run_id,organization_id,sequence,type,category,title,summary,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)\", (event_id, run_id, organization_id, sequence, type_, category, title, summary, json.dumps(payload or {}), now))\n        db.execute(\"UPDATE runs SET updated_at=? WHERE id=?\", (now, run_id))\n        inserted = db.execute(\"SELECT * FROM events WHERE id=?\", (event_id,)).fetchone()\n        if inserted is None:\n            raise RuntimeError(\"event_insert_readback_failed\")\n        return self._event_json(inserted)\n""",
    )
    replace(
        path,
        """            if task_id is None:\n                version_row = db.execute(\"SELECT COALESCE(MAX(version),0)+1 AS value FROM artifacts WHERE run_id=? AND task_id IS NULL\", (run_id,)).fetchone()\n            else:\n                version_row = db.execute(\"SELECT COALESCE(MAX(version),0)+1 AS value FROM artifacts WHERE run_id=? AND task_id=?\", (run_id, task_id)).fetchone()\n""",
        """            if task_id is None:\n                version_row = db.execute(\n                    \"SELECT COALESCE(MAX(version),0)+1 AS value FROM artifacts \"\n                    \"WHERE run_id=? AND task_id IS NULL AND kind=?\",\n                    (run_id, kind),\n                ).fetchone()\n            else:\n                version_row = db.execute(\n                    \"SELECT COALESCE(MAX(version),0)+1 AS value FROM artifacts \"\n                    \"WHERE run_id=? AND task_id=? AND kind=?\",\n                    (run_id, task_id, kind),\n                ).fetchone()\n""",
    )
    replace(
        path,
        """            if supersede_candidates:\n                if task_id is None:\n                    db.execute(\"UPDATE artifacts SET status='superseded' WHERE run_id=? AND task_id IS NULL AND status='candidate'\", (run_id,))\n                else:\n                    db.execute(\"UPDATE artifacts SET status='superseded' WHERE run_id=? AND task_id=? AND status='candidate'\", (run_id, task_id))\n""",
        """            if supersede_candidates:\n                if task_id is None:\n                    db.execute(\n                        \"UPDATE artifacts SET status='superseded' \"\n                        \"WHERE run_id=? AND task_id IS NULL AND kind=? AND status='candidate'\",\n                        (run_id, kind),\n                    )\n                else:\n                    db.execute(\n                        \"UPDATE artifacts SET status='superseded' \"\n                        \"WHERE run_id=? AND task_id=? AND kind=? AND status='candidate'\",\n                        (run_id, task_id, kind),\n                    )\n""",
    )


def patch_executor() -> None:
    path = "server/app/platform_executor.py"
    replace(
        path,
        """    source_event_count = 0\n    cutoff_sequence = 0\n    runtime_binding_projections: list[dict[str, Any]] = []\n""",
        """    source_event_count = 0\n    first_event_sequence = 0\n    cutoff_sequence = 0\n    runtime_binding_projections: list[dict[str, Any]] = []\n""",
    )
    replace(
        path,
        """            for batch in store.iter_run_events(run_id, batch_size=1_000):\n                for event in batch:\n                    source_event_count += 1\n                    cutoff_sequence = max(cutoff_sequence, int(event.get(\"sequence\") or 0))\n""",
        """            for frozen_cutoff, batch in store.iter_run_events_frozen(run_id, batch_size=1_000):\n                cutoff_sequence = frozen_cutoff\n                for event in batch:\n                    source_event_count += 1\n                    sequence = int(event.get(\"sequence\") or 0)\n                    if first_event_sequence == 0 or sequence < first_event_sequence:\n                        first_event_sequence = sequence\n""",
    )
    replace(
        path,
        """        \"source_event_count\": source_event_count,\n        \"cutoff_sequence\": cutoff_sequence,\n        \"runtime_binding_projections\": runtime_binding_projections,\n""",
        """        \"source_event_count\": source_event_count,\n        \"first_event_sequence\": first_event_sequence,\n        \"cutoff_sequence\": cutoff_sequence,\n        \"event_snapshot_coherent\": (\n            source_event_count == projection_count + omission_count\n            and (source_event_count == 0 or (first_event_sequence > 0 and cutoff_sequence >= first_event_sequence))\n        ),\n        \"event_snapshot_boundary_rule\": \"same_connection_max_sequence_then_sequence_lte_frozen_cutoff\",\n        \"runtime_binding_projections\": runtime_binding_projections,\n""",
    )
    replace(
        path,
        "def _event_snapshot_metadata(event_snapshot: dict[str, Any]) -> dict[str, int]:\n",
        "def _event_snapshot_metadata(event_snapshot: dict[str, Any]) -> dict[str, Any]:\n",
    )
    replace(
        path,
        """        \"omitted_event_count\": omitted_event_count,\n        \"cutoff_sequence\": int(event_snapshot.get(\"cutoff_sequence\") or 0),\n    }\n""",
        """        \"omitted_event_count\": omitted_event_count,\n        \"first_event_sequence\": int(event_snapshot.get(\"first_event_sequence\") or 0),\n        \"cutoff_sequence\": int(event_snapshot.get(\"cutoff_sequence\") or 0),\n        \"event_snapshot_coherent\": bool(event_snapshot.get(\"event_snapshot_coherent\")),\n        \"event_snapshot_boundary_rule\": str(event_snapshot.get(\"event_snapshot_boundary_rule\") or \"\"),\n    }\n""",
    )
    replace(
        path,
        """                                artifact_item for artifact_item in latest_snapshot.get(\"artifacts\", [])\n                                if str(artifact_item.get(\"task_id\") or \"\") == str(task[\"id\"])\n""",
        """                                artifact_item for artifact_item in latest_snapshot.get(\"artifacts\", [])\n                                if str(artifact_item.get(\"task_id\") or \"\") == str(task[\"id\"])\n                                and str(artifact_item.get(\"kind\") or \"\") == \"workflow_output\"\n""",
    )
    replace(
        path,
        """                if verdict == \"pass\":\n                    async with event_lock:\n                        store.append_run_event(\n                            run_id, \"gate.passed\", \"gate\", f\"“{task_by_key[gate_key]['node_name']}”裁决通过\",\n                            str(decision.get(\"summary\") or \"独立裁判确认本轮产物满足验收要求。\"),\n                            {\"task_id\": task_by_key[gate_key][\"id\"], \"node_key\": gate_key, \"decision\": decision},\n                        )\n                    continue\n                gate_definition = node_def_by_key.get(gate_key, {})\n""",
        """                if verdict == \"pass\":\n                    async with event_lock:\n                        accepted_event = store.append_run_event(\n                            run_id,\n                            \"judge.verdict.accepted\",\n                            \"gate\",\n                            f\"“{task_by_key[gate_key]['node_name']}”提交通过裁决\",\n                            str(decision.get(\"summary\") or \"独立裁判确认本轮产物满足验收要求。\"),\n                            {\"task_id\": task_by_key[gate_key][\"id\"], \"node_key\": gate_key, \"decision\": decision},\n                        )\n                        store.append_run_event(\n                            run_id, \"gate.passed\", \"gate\", f\"“{task_by_key[gate_key]['node_name']}”裁决通过\",\n                            str(decision.get(\"summary\") or \"独立裁判确认本轮产物满足验收要求。\"),\n                            {\n                                \"task_id\": task_by_key[gate_key][\"id\"],\n                                \"node_key\": gate_key,\n                                \"decision\": decision,\n                                \"causation_event_id\": accepted_event[\"id\"],\n                                \"causation_sequence\": accepted_event[\"sequence\"],\n                            },\n                        )\n                    continue\n                async with event_lock:\n                    store.append_run_event(\n                        run_id,\n                        \"judge.verdict.revised\",\n                        \"gate\",\n                        f\"“{task_by_key[gate_key]['node_name']}”提交退回裁决\",\n                        str(decision.get(\"feedback\") or decision.get(\"summary\") or \"独立裁判要求返工。\"),\n                        {\"task_id\": task_by_key[gate_key][\"id\"], \"node_key\": gate_key, \"decision\": decision},\n                    )\n                gate_definition = node_def_by_key.get(gate_key, {})\n""",
    )


if __name__ == "__main__":
    patch_store()
    patch_executor()
    print("owner remediation patch applied")
