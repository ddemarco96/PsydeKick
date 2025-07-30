"""
Unit-tests for the summary / explanation logic in
workflows.config_explorer  (identify_config_type & describe_config_file).

Run with:
    python -m unittest tests/test_config_explorer.py
"""

import unittest
import csv
from pathlib import Path
from tempfile import TemporaryDirectory

from workflows import config_explorer as ce


class ConfigExplorerTests(unittest.TestCase):
    """Tests cover detection + markdown description generation."""

    def _tmp_csv(self, header, row):
        """
        Create a one-row CSV in a temp folder and return its Path.
        `header` – list[str]; `row` – list[any]
        """
        path = Path(self.tmpdir) / "sample.csv"
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerow(row)
        return path

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmpdir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_identify_alias_config(self):
        cols = ["within_study_id", "metricwire_alias"]
        cfg_type = ce.identify_config_type(cols)
        self.assertEqual(cfg_type, "alias_config")

    def test_identify_rate_config(self):
        cols = ["id", "rate", "reason"]
        cfg_type = ce.identify_config_type(cols)
        self.assertEqual(cfg_type, "rate_config")

    def test_unknown_columns(self):
        cfg_type = ce.identify_config_type(["foo", "bar"])
        self.assertIsNone(cfg_type)

    def test_describe_alias_contains_values(self):
        path = self._tmp_csv(
            header=["within_study_id", "metricwire_alias"],
            row=["ABC123", "XYZ789"],
        )
        md = ce.describe_config_file(path)
        # sanity: correct template chosen
        self.assertIn("alias mapping", md)
        # dynamic example built from first row
        self.assertIn("ABC123", md)
        self.assertIn("XYZ789", md)

    def test_describe_rate_contains_reason(self):
        path = self._tmp_csv(
            header=["id", "rate", "reason"],
            row=["9", "$12.00", "Baseline Visit"],
        )
        md = ce.describe_config_file(path)
        self.assertIn("payment table", md)
        self.assertIn("Baseline Visit", md)
        self.assertIn("$12.00", md)

    def test_describe_unrecognized(self):
        path = self._tmp_csv(
            header=["foo", "bar"],
            row=["1", "2"],
        )
        md = ce.describe_config_file(path)
        self.assertIn("Unrecognized configuration file", md)

    def test_extra_column_is_ignored(self):
        """
        A file that has all the alias columns *plus* an extra 'notes' column
        should still be identified as 'alias_config'.
        """
        header = ["within_study_id", "metricwire_alias", "notes"]
        row = ["P001", "MW999", "some comment"]
        path = self._tmp_csv(header, row)

        # identification still works
        self.assertEqual(ce.identify_config_type(header), "alias_config")

        # description still includes the dynamic values from first row
        md = ce.describe_config_file(path)
        self.assertIn("P001", md)
        self.assertIn("MW999", md)


if __name__ == "__main__":
    unittest.main()
