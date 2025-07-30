import datetime
import unittest
import tempfile
import os
import shutil
from unittest.mock import patch

import pandas as pd
import pytz
import responses

from tests.mocks.constants import MW_RESPS
from workflows.download import MetricWireImporter as MWI


class TestDownloadWorkflow(unittest.TestCase):
    def setUp(self):
        # save CWD
        self._orig_cwd = os.getcwd()
        # Create study settings csv
        self.temp_root = tempfile.mkdtemp()
        self.config_root = os.path.join(self.temp_root, "config")
        os.makedirs(self.config_root)
        config_df = pd.DataFrame([{
            "study_name": "Test study",
            'mw_workspace_id': '5fb5c34fae9a634696d746746d1',
            'mw_study_id': '621920605978cd435ce7cf73',
        }])
        config_df.to_csv(os.path.join(self.config_root, "settings.csv"), index=False)


        # Prevent any to_csv calls in MWI from actually writing files
        self._tc_patcher = patch.object(pd.DataFrame, "to_csv", lambda self, *args, **kwargs: None)
        self._tc_patcher.start()

        # credentials & minimal study config
        self.credentials = {
            'client_id': 'test_user',
            'client_secret': 'test_password'
        }
        self.study_name = 'Test study'

        self.study = {
            'name': self.study_name,
            # ID values from the Catalyst API test
            'mw_workspace_id': '5fb5c34fae9a634696d746746d1',
            'mw_study_id': '621920605978cd435ce7cf73',
            'credentials': self.credentials
        }
        MWI.study = self.study
        MWI.progress_cb = None

        # Store the config path for use in tests
        self.config_csv_path = os.path.join(self.config_root, "settings.csv")

        # Mock HTTP
        token_url = MWI.get_url('token')
        responses.start()
        responses.add(responses.POST, token_url,
                      status=200, json={"access_token": "test_token"})
        study_url = MWI.get_url('study')
        responses.add(responses.GET, study_url,
                      status=200, json=MW_RESPS['study_details'])

        for info in MW_RESPS['surveys'].values():
            sid = info['survey_details']['id']
            responses.add(responses.GET,
                          MWI.get_url('survey_details', s_id=sid),
                          status=200,
                          json=info['survey_details'])
            cnt = len(info['sessions']['submissions'])
            responses.add(responses.GET,
                          MWI.get_url('size', s_id=sid),
                          status=200,
                          json={"count": cnt})
            responses.add(responses.POST,
                          MWI.get_url('session', s_id=sid, skip=0),
                          status=200,
                          json=info['sessions'])

        # Change to the temporary directory
        os.chdir(self.temp_root)

    def tearDown(self):
        # restore CWD before cleanup
        os.chdir(self._orig_cwd)
        # stop both responses and to_csv patch
        responses.stop()
        self._tc_patcher.stop()
        shutil.rmtree(self.temp_root)

    def test_study_name_and_credentials_required(self):
        base_kwargs = {
            "question_filter": None,
            "output_dir": "./data/",
        }

        with self.assertRaises(ValueError):
            MWI.start(study_name=None, credentials=self.credentials, **base_kwargs)

        with self.assertRaises(ValueError):
            MWI.start(study_name=self.study_name, credentials=None, **base_kwargs)

    def test_get_url(self):
        w, s = self.study['mw_workspace_id'], self.study['mw_study_id']
        skip, sid = "123", "XYZ"
        expected = {
            "token": MWI.base_url + "oauth/token",
            "study": f"{MWI.base_url}studies/{w}/{s}",
            "size": f"{MWI.base_url}submissions/size/{w}/{s}/{sid}",
            "survey_details": f"{MWI.base_url}surveys/{w}/{s}/{sid}",
            "session": f"{MWI.base_url}submissions/{w}/{s}/{sid}/{skip}",
        }
        for part, url in expected.items():
            self.assertEqual(MWI.get_url(part, s_id=sid, skip=skip), url)

    def test_date_time_tz_to_dt(self):
        date, tm = "01/01/2024", "12:00:00"
        dt1 = MWI.date_time_tz_to_dt(date, tm, "-04:00")
        want = datetime.datetime(2024, 1, 1, 12, 0,
                                 tzinfo=pytz.FixedOffset(-240))
        self.assertEqual(dt1, want)
        dt2 = MWI.date_time_tz_to_dt(date, tm, "-4:00")
        self.assertEqual(dt2, want)

    @responses.activate
    def test_get_headers(self):
        h = MWI.get_headers()
        self.assertEqual(h, {"Authorization": "Bearer test_token"})
        self.assertEqual(len(responses.calls), 1)

    @responses.activate
    def test_import_data_defaults(self):
        # clear in-memory tables
        MWI._questions = []
        MWI._sessions = []
        MWI._responses = []

        # invoke the importer
        all_question_names = set()
        for info in MW_RESPS["surveys"].values():
            all_question_names.update(
                q["variableName"] for q in info["survey_details"]["questions"]
            )
        MWI.start(
            study_name=self.study_name,
            credentials=self.credentials,
            question_filter=list(all_question_names),
            output_dir="data/",
            config_path=self.config_csv_path
        )

        # HTTP calls: 2x token (one in start and one import) + 1 study + 5*(details+size+session)
        expected_calls = 2 + 1 + 5 * 3
        self.assertEqual(len(responses.calls), expected_calls)

        # expected counts from MW_RESPS
        total_q = sum(len(info["survey_details"]["questions"])
                      for info in MW_RESPS["surveys"].values())
        total_s = sum(len(info["sessions"]["submissions"])
                      for info in MW_RESPS["surveys"].values())
        total_r = sum(
            len(sub["questionValues"])
            for info in MW_RESPS["surveys"].values()
            for sub in info["sessions"]["submissions"]
        )

        self.assertEqual(len(MWI._questions), total_q)
        self.assertEqual(len(MWI._sessions), total_s)

        self.assertEqual(len(MWI._responses), total_r)

    @responses.activate
    def test_question_filter_only_by_variableName(self):
        # pick one variableName
        first = next(iter(MW_RESPS["surveys"].values()))
        var0 = first["survey_details"]["questions"][0]["variableName"]

        MWI._questions = []
        MWI._sessions = []
        MWI._responses = []

        # run with filter
        MWI.start(
            study_name=self.study_name,
            credentials=self.credentials,
            question_filter=[var0],
            output_dir="data/",
            config_path=self.config_csv_path
        )

        rdf = pd.DataFrame(MWI._responses)
        self.assertTrue((rdf["question_name"] == var0).all())
        unfiltered = sum(
            len(sub["questionValues"])
            for info in MW_RESPS["surveys"].values()
            for sub in info["sessions"]["submissions"]
        )
        self.assertLess(len(rdf), unfiltered)


class TestTaggingWorkflow(unittest.TestCase):
    def setUp(self):
        # Prevent any to_csv calls from actually writing files
        self._tc_patcher = patch.object(pd.DataFrame, "to_csv", lambda self, *args, **kwargs: None)
        self._tc_patcher.start()
        self.study_name = 'Test study'

    def tearDown(self):
        self._tc_patcher.stop()


if __name__ == "__main__":
    unittest.main()
