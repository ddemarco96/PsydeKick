import os
import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from workflows import tagging


class Workflow2TaggingTests(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory structure: tmp/data/Example/
        self.temp_root = tempfile.mkdtemp()
        self.data_root = os.path.join(self.temp_root, "data")
        # copy the config/Example directory to the temp directory
        self.config_root = os.path.join(self.temp_root, "config")
        self.config_dir = os.path.join(self.config_root, "tagging", "Example")
        os.makedirs(self.config_dir)
        self.study_name = "Example"
        self.study_dir = os.path.join(self.data_root, self.study_name)
        os.makedirs(self.study_dir)

        # 1) sessions.csv: one row per session_id
        session_ids = ["s1", "s2", "s3", "s4", "s5"]
        sessions_df = pd.DataFrame({
            "session_id": session_ids,
            "started_at_utc": pd.Timestamp("2025-01-01T00:00:00Z"),
            "ended_at_utc":   pd.Timestamp("2025-01-01T00:05:00Z"),
        })
        sessions_df.to_csv(os.path.join(self.study_dir, "sessions.csv"), index=False)

        # 2) responses.csv: two responses per session (intent and urge)
        # Define the intent and urge values for each session:
        #  - "s1": (intent=0, urge=0)       → No risk
        #  - "s2": (intent=1, urge=5)       → Some risk (group 1)
        #  - "s3": (intent=0, urge=1)       → Some risk (group 2)
        #  - "s4": (intent=8, urge=0)       → High risk (group 1)
        #  - "s5": (intent=1, urge=8)       → High risk (group 2)
        responses_rows = []
        session_response_map = {
            "s1": ("0", "0"),
            "s2": ("1", "5"),
            "s3": ("0", "1"),
            "s4": ("8", "0"),
            "s5": ("1", "8"),
        }
        for session_id, (intent_value, urge_value) in session_response_map.items():
            responses_rows.append({
                "session_id": session_id,
                "question_name": "q_intent",
                "content": intent_value,
                "skipped": False,
                "opened_at": "2025-01-01T00:00:00Z",
                "responded_at": "2025-01-01T00:00:05Z",
            })
            responses_rows.append({
                "session_id": session_id,
                "question_name": "q_urge",
                "content": urge_value,
                "skipped": False,
                "opened_at": "2025-01-01T00:00:00Z",
                "responded_at": "2025-01-01T00:00:05Z",
            })
        pd.DataFrame(responses_rows).to_csv(
            os.path.join(self.study_dir, "responses.csv"),
            index=False
        )

        # 3) tags.csv: mapping tag_id → tag title
        tags_df = pd.DataFrame([
            {"id": "tag_no",   "title": "No risk"},
            {"id": "tag_some", "title": "Some risk"},
            {"id": "tag_high", "title": "High risk"},
        ])
        tags_df.to_csv(os.path.join(self.config_dir, "tags.csv"), index=False)

        # 4) workflows.csv: one workflow per risk category
        workflows_df = pd.DataFrame([
            {
              "id":               "wf_no",
              "workflow_type":    "1",  # TAG_SESSION
              "logical_operator": "AND",
              "tag_id":           "tag_no",
              "name":             "No risk workflow"
            },
            {
              "id":               "wf_some",
              "workflow_type":    "1",
              "logical_operator": "OR",
              "tag_id":           "tag_some",
              "name":             "Some risk workflow"
            },
            {
              "id":               "wf_high",
              "workflow_type":    "1",
              "logical_operator": "OR",
              "tag_id":           "tag_high",
              "name":             "High risk workflow"
            },
        ])
        workflows_df.to_csv(
            os.path.join(self.config_dir, "workflows.csv"),
            index=False
        )

        # 5) condition_groups.csv: each workflow has one or two condition groups
        condition_groups_df = pd.DataFrame([
            {"id": "grp_no",  "workflow_id": "wf_no",   "logical_operator": "AND"},
            {"id": "grp_s1",  "workflow_id": "wf_some", "logical_operator": "AND"},
            {"id": "grp_s2",  "workflow_id": "wf_some", "logical_operator": "AND"},
            {"id": "grp_h1",  "workflow_id": "wf_high", "logical_operator": "AND"},
            {"id": "grp_h2",  "workflow_id": "wf_high", "logical_operator": "AND"},
        ])
        condition_groups_df.to_csv(
            os.path.join(self.config_dir, "condition_groups.csv"),
            index=False
        )

        # 6) conditions.csv: rules within each group
        conditions_list = [
            # No risk group: intent == 0 AND urge == 0
            {"id": "cond1",  "group_id": "grp_no", "operator": "==", "value": "0", "skip_behavior": "0"},
            {"id": "cond2",  "group_id": "grp_no", "operator": "==", "value": "0", "skip_behavior": "0"},

            # Some risk group1: intent > 0 AND intent < 8 AND urge < 8
            {"id": "cond3",  "group_id": "grp_s1", "operator": ">",  "value": "0", "skip_behavior": "0"},
            {"id": "cond4",  "group_id": "grp_s1", "operator": "<",  "value": "8", "skip_behavior": "0"},
            {"id": "cond5",  "group_id": "grp_s1", "operator": "<",  "value": "8", "skip_behavior": "0"},

            # Some risk group2: intent == 0 AND urge > 0
            {"id": "cond6",  "group_id": "grp_s2", "operator": "==", "value": "0", "skip_behavior": "0"},
            {"id": "cond7",  "group_id": "grp_s2", "operator": ">",  "value": "0", "skip_behavior": "0"},

            # High risk group1: intent >= 8
            {"id": "cond8",  "group_id": "grp_h1", "operator": ">=", "value": "8", "skip_behavior": "0"},

            # High risk group2: urge > 7 AND intent > 0
            {"id": "cond9",  "group_id": "grp_h2", "operator": ">",  "value": "7", "skip_behavior": "0"},
            {"id": "cond10", "group_id": "grp_h2", "operator": ">",  "value": "0", "skip_behavior": "0"},
        ]
        pd.DataFrame(conditions_list).to_csv(
            os.path.join(self.config_dir, "conditions.csv"),
            index=False
        )

        # 7) condition_questions.csv: map each condition to question_id
        condition_question_mappings = []
        # Conditions referencing the intent question:
        for cond_id in ["cond1", "cond3", "cond4", "cond6", "cond8", "cond10"]:
            condition_question_mappings.append({
                "condition_id": cond_id,
                "question_name":   "q_intent"
            })
        # Conditions referencing the urge question:
        for cond_id in ["cond2", "cond5", "cond7", "cond9"]:
            condition_question_mappings.append({
                "condition_id": cond_id,
                "question_name":   "q_urge"
            })
        pd.DataFrame(condition_question_mappings).to_csv(
            os.path.join(self.config_dir, "condition_questions.csv"),
            index=False
        )

    def tearDown(self):
        shutil.rmtree(self.temp_root)

    def test_run_tagging_assigns_expected_tags(self):
        # Execute the tagging routine
        tagging.run_tagging(self.study_name, base_dir=self.temp_root)

        # Read back the sessions.csv and build a mapping session_id → [tags]
        updated_sessions = pd.read_csv(Path(self.study_dir) / "tagged_sessions.csv")
        session_to_tags = {
            row["session_id"]: row["session_tags"].split(";") if pd.notna(row["session_tags"]) else []
            for _, row in updated_sessions.iterrows()
        }

        # Assert each session got the correct tag
        self.assertEqual(session_to_tags["s1"], ["No risk"])
        self.assertEqual(session_to_tags["s2"], ["Some risk"])
        self.assertEqual(session_to_tags["s3"], ["Some risk"])
        self.assertEqual(session_to_tags["s4"], ["High risk"])
        self.assertEqual(session_to_tags["s5"], ["High risk"])

    def test_handle_between_inclusive_exclusive_logic(self):
        between_fn = tagging.handle_between

        # Test inclusive both ends: [1,5]
        self.assertTrue(between_fn(1.0, "[1,5]"))
        self.assertTrue(between_fn(5.0, "[1,5]"))
        self.assertFalse(between_fn(0.9, "[1,5]"))
        self.assertFalse(between_fn(5.1, "[1,5]"))

        # Test inclusive lower, exclusive upper: [1,5)
        self.assertTrue(between_fn(1.0, "[1,5)"))
        self.assertFalse(between_fn(5.0, "[1,5)"))

        # Test exclusive both: (1,5)
        self.assertFalse(between_fn(1.0, "(1,5)"))
        self.assertFalse(between_fn(5.0, "(1,5)"))
        self.assertTrue(between_fn(2.5, "(1,5)"))


if __name__ == "__main__":
    unittest.main()
