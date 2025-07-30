import datetime
import json
import logging
import time
from pathlib import Path

import pandas as pd
import requests

LOGGER = logging.getLogger(__name__)


def timestamp_to_utc(timestamp):
    """
    Convert a given Unix timestamp in milliseconds to a UTC datetime object.

    This function takes a Unix timestamp representing the number of
    milliseconds since the epoch (January 1, 1970) and converts it into
    a timezone-aware UTC datetime object.

    :param timestamp: The Unix timestamp in milliseconds to be converted.
    :type timestamp: int
    :return: A timezone-aware UTC datetime object representing the given timestamp.
    :rtype: datetime.datetime
    """
    time_in_s = timestamp / 1000
    dt = datetime.datetime.utcfromtimestamp(time_in_s).replace(
        tzinfo=datetime.timezone.utc)
    return dt


def patient_request(importer, url, headers, url_name, method="GET", study=None, data=None):
    """
    Sends an HTTP request to the specified URL using the provided method, headers,
    and optional data for POST requests. Handles retries with exponential backoff
    for failed attempts and refreshes headers upon receiving a 401 Unauthorized
    response.

    This function ensures compliance with rate limits for requests and provides
    detailed logging for request attempts, failures, and retries. It raises an
    exception if all retry attempts fail or returns the successful response.

    :param importer: The object that manages rate limiting and provides updated
        headers for requests in case of an authorization error.
    :type importer: any
    :param url: The endpoint to which the HTTP request is sent.
    :type url: str
    :param headers: The headers to include in the HTTP request.
    :type headers: dict
    :param url_name: A descriptive name of the URL or endpoint for logging purposes.
    :type url_name: str
    :param method: The HTTP method to use for the request, such as "GET" or "POST".
        Defaults to "GET".
    :type method: str
    :param study: Optional study object or identifier necessary to refresh headers.
        Defaults to None.
    :type study: any, optional
    :param data: Optional data payload for POST requests. Defaults to None.
    :type data: dict, optional
    :return: A tuple containing the HTTP response object and the updated headers.
    :rtype: tuple
    :raises ConnectionError: If the request fails after the maximum number of retries.
    """
    max_attempts = 3
    backoff_factor = 5  # seconds to wait between retries
    resp = None
    for attempt in range(1, max_attempts + 1):
        try:
            importer.rate_limit()  # Ensure we're within the rate limit
            if method == "GET":
                resp = requests.get(url, headers=headers)
            else:
                resp = requests.post(url, data=data, headers=headers)

            # If the response is OK, return it
            if resp.ok:
                return resp, headers
            else:
                LOGGER.warning(
                    "Invalid response from the data source when attempting to reach the %s endpoint. Status code was: %s.",
                    url_name, resp.status_code)
                if resp.status_code == 401:
                    # Handle 401 Unauthorized: Refresh headers if possible
                    headers = importer.get_headers(study=study)
                    LOGGER.info("Refreshed headers after 401 Unauthorized. Retrying request.")
        except requests.exceptions.RequestException as e:
            LOGGER.warning(f"Request to {url_name} failed with exception: {e}")
            resp = None  # Ensure resp is defined if an exception occurs

        # If we've reached the maximum number of retries, raise an exception
        if attempt == max_attempts:
            LOGGER.error(f"Url: {url}")
            LOGGER.error(f"Failed to fetch data from {url_name} after {max_attempts} attempts.")
            raise ConnectionError(f"Failed to fetch data from MetricWire (endpoint: {url_name}) after {max_attempts} attempts.")

        # Wait before retrying (exponential backoff)
        sleep_time = backoff_factor * attempt
        LOGGER.info(f"Retrying {url_name} in {sleep_time} seconds (Attempt {attempt} of {max_attempts})")
        time.sleep(sleep_time)
    # If we exit the loop without returning or raising, raise an exception
    raise ConnectionError(f"Failed to fetch data from {url_name} after {max_attempts} attempts. Received response: {resp.status_code if resp else 'None'}.")


class MetricWireImporter:
    """
    Represents a class for importing data from MetricWire, handling study configurations,
    data fetching, and processing tasks. Provides methods to interact with the MetricWire
    API while managing rate limits, token retrieval, and output file generation.

    The class primarily operates as a utility for automating the retrieval of survey data
    from MetricWire, organizing it into usable formats, like CSVs, and optionally dumping
    JSON responses for debugging or auditing purposes. It supports multiple studies and
    provides customization for study-specific configurations.

    :ivar api_version: Specifies the API version used for MetricWire.
    :type api_version: str
    :ivar base_url: The base URL for the MetricWire API service.
    :type base_url: str
    :ivar last_request_times: Keeps a record of API request timestamps for rate-limiting.
    :type last_request_times: list[float]
    :ivar question_filter: An optional filter used to specify questions to import;
        None means skipping all questions by default.
    :type question_filter: list[str] | None
    """
    api_version = "2.0.0"
    base_url = "https://consumer-api.metricwire.com/"
    last_request_times = []
    # default filter (None = skip all)
    question_filter = None

    @classmethod
    def start(cls,
              study_name: str,
              credentials: dict,
              question_filter: list[str] = None,
              output_dir: str = ".",
              progress_callback: callable = None,
              dump_json: bool = False,  # set to True to run in debug mode
              config_path: str = None,  # optional path to config file
              ):
        """
        Start fetching and processing study data, including surveys,
        questions, sessions, and responses, based on the given inputs.

        :param study_name: The name of the study to process.
        :param credentials: A dictionary containing authentication credentials.
        :param question_filter: A list of questions to filter processing, default is None.
        :param output_dir: Path to the directory where output will be saved. Defaults to ".".
        :param progress_callback: A callable used to track progress, default is None.
        :param dump_json: Indicates whether to save intermediate JSON responses for debugging.
                          Defaults to True.
        :param config_path: Optional path to config file. Defaults to project config/settings.csv
        :type dump_json: Bool
        :return: None
        :rtype: None
        :raises ValueError: If `study_name` or `credentials` are not provided.
        """
        if not study_name or not credentials:
            raise ValueError("Must supply study_name & credentials")

        # Build study config
        cls.study = cls.get_study_params(study_name, credentials, config_path)

        # set up JSON‐dumping if requested
        cls.dump_json = bool(dump_json)
        if cls.dump_json:
            cls.json_dir = Path(output_dir) / study_name / "raw_json"
            cls.json_dir.mkdir(parents=True, exist_ok=True)

        # Set up class variables
        cls.question_filter = list(set(question_filter or []))
        cls.progress_cb = progress_callback
        cls.output_dir = Path(output_dir)
        cls.study_dir = cls.output_dir / study_name
        cls.study_dir.mkdir(parents=True, exist_ok=True)

        # reset accumulators
        cls._questions = []
        cls._sessions = []
        cls._responses = []

        # fetch study details, count surveys, then import
        study_resp, _ = patient_request(
            cls, cls.get_url("study"), headers=cls.get_headers(),
            study=cls.study, url_name="study"
        )

        # save a copy of the study details response
        if cls.dump_json:
            (cls.json_dir / "study_details.json").write_text(study_resp.text)

        surveys = study_resp.json()["surveys"]
        total_surveys = len(surveys)

        # call import_data with the pre-fetched surveys
        cls.import_data(surveys, total_surveys, dump_json=cls.dump_json)

        # Dump out CSVs
        pd.DataFrame(cls._questions).to_csv(
            cls.study_dir / "questions.csv", index=False
        )
        pd.DataFrame(cls._sessions).to_csv(
            cls.study_dir / "sessions.csv", index=False
        )
        pd.DataFrame(cls._responses).to_csv(
            cls.study_dir / "responses.csv", index=False
        )

    @classmethod
    def get_study_params(cls, name, creds, config_path=None):
        """
        Fetch the mw_workspace_id and mw_study_id from the settings.csv based on the provided name.

        :param name: The study name to look up
        :param creds: The credentials dictionary
        :param config_path: Optional path to config file. Defaults to project config/settings.csv
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "settings.csv"
        else:
            config_path = Path(config_path)

        df = pd.read_csv(config_path)
        # Check if the DataFrame is empty or does not contain the required columns
        if df.empty or not all([col in df.columns for col in ["study_name", "mw_workspace_id", "mw_study_id"]]):
            raise ValueError("Settings config is either missing or misconfigured: ")
        study_settings = df.loc[df["study_name"] == name]
        if study_settings.empty:
            raise ValueError(f"Cannot find settings for {name}")

        # They're trying to download using the example config, which is fake
        if study_settings.mw_study_id.iloc[0] == "621920605978cd435ce7cf72":
            raise ValueError(
                "You cannot use the example study settings to download data. "
            )

        return {
            "name": name,
            "mw_workspace_id": study_settings.mw_workspace_id.iloc[0],
            "mw_study_id": study_settings.mw_study_id.iloc[0],
            "credentials": creds,
        }

    @classmethod
    def get_url(cls, url, s_id=None, skip=None):
        base = cls.base_url
        workspace_id = cls.study["mw_workspace_id"]
        study_id = cls.study["mw_study_id"]
        if url == "token":
            return base + "oauth/token"
        if url == "study":
            return f"{base}studies/{workspace_id}/{study_id}"
        if url == "size":
            return f"{base}submissions/size/{workspace_id}/{study_id}/{s_id}"
        if url == "survey_details":
            return f"{base}surveys/{workspace_id}/{study_id}/{s_id}"
        if url == "session":
            return f"{base}submissions/{workspace_id}/{study_id}/{s_id}/{skip}"
        raise ValueError(f"Unknown URL url {url}")

    @classmethod
    def rate_limit(cls):
        # Create a rate limit of 55 requests per minute (capped by MW) unless being used in a test
        LIMIT = 55 if "test" not in str(Path(__file__)) else 1000
        now = time.time()
        cls.last_request_times = [t for t in cls.last_request_times if now - t < 60]
        if len(cls.last_request_times) >= LIMIT:
            wait = 60 - (now - min(cls.last_request_times)) + 0.1
            LOGGER.info(f"Rate limit hit: sleeping {wait:.1f}s")
            time.sleep(wait)
            now = time.time()
            cls.last_request_times = [t for t in cls.last_request_times if now - t < 60]
        cls.last_request_times.append(now)

    @classmethod
    def get_headers(cls):
        url = cls.get_url("token")
        creds = cls.study["credentials"]
        payload = {
            "grant_type": "client_credentials",
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        }
        cls.rate_limit()
        resp = requests.post(url, json=payload)
        if resp.status_code != 200:
            raise ValueError("Token fetch failed")
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    @classmethod
    def date_time_tz_to_dt(cls, date, time_str, tz):
        # Normalize tz "-5:00" → "-05:00" -- handling weird MW format
        tzf = tz[0] + tz[1:].zfill(5) if len(tz) < 6 else tz
        ts = f"{date} {time_str} {tzf}"
        return datetime.datetime.strptime(ts, "%d/%m/%Y %H:%M:%S %z")

    @classmethod
    def import_data(cls,
                    surveys: list[dict],
                    total_surveys: int,
                    dump_json: bool = False,
                    ):
        """
        Now receives the pre-fetched `surveys` list and its length.
        """
        headers = cls.get_headers()
        form_data = {'omitPII': "true"}

        processed = 0
        for survey_meta in surveys:
            sid = survey_meta["id"]

            # if dump_json, save the survey meta
            if cls.dump_json:
                (cls.json_dir / f"survey_meta_{sid}.json").write_text(json.dumps(survey_meta))

            # 1) record questions
            sd_resp, _ = patient_request(
                cls, cls.get_url("survey_details", s_id=sid),
                headers=headers, study=cls.study, url_name="survey_details"
            )

            # if dump_json, save the survey details
            if cls.dump_json:
                (cls.json_dir / f"survey_details_{sid}.json").write_text(json.dumps(sd_resp.text))

            survey = {
                "external_id": sid,
                "participant_name": survey_meta["name"],
                "internal_name": survey_meta.get("internalName", survey_meta["name"]),
            }

            questions = sd_resp.json()["questions"]
            cls.handle_questions(questions, survey)

            # 2) process sessions -- paginated by 500 submissions
            size_resp, _ = patient_request(
                cls, cls.get_url("size", s_id=sid),
                headers=headers, study=cls.study, url_name="submissions size"
            )
            num = size_resp.json()["count"]
            pages = (num // 500) + 1
            for p in range(pages):
                sess_resp, _ = patient_request(
                    cls, cls.get_url("session", s_id=sid, skip=p),
                    headers=headers, study=cls.study,
                    method="POST", data=form_data,
                    url_name="session"
                )

                # if dump_json, save the session details
                if cls.dump_json:
                    (cls.json_dir / f"survey_sessions_{sid}_{p}.json").write_text(json.dumps(sess_resp.text))

                cls.handle_sessions(sess_resp.json()["submissions"], survey)

            # increment and report progress for bar UI
            processed += 1
            if cls.progress_cb:
                cls.progress_cb(processed, total_surveys)

    @classmethod
    def handle_questions(cls, data, survey, parent_id=None):
        """
        Flatten nested question definitions → cls._questions,
        also record a mapping question_id → (variableName, text).
        """
        # If no question filter, skip all questions; otherwise record info for all questions just in case
        if cls.question_filter:
            for q in data:
                row = {
                    "survey_id": survey["external_id"],
                    "survey_name": survey["internal_name"],
                    "question_id": q["id"],
                    "question_name": q.get("variableName"),
                    # this is the text shown to the participant
                    "text": q.get("question"),
                    "type": q.get("type"),
                    # if present, the question is a sub‐question of another
                    "parent_question_id": parent_id,
                }
                cls._questions.append(row)

                # Recurse into any sub‐questions
                if q.get("questions"):
                    cls.handle_questions(q["questions"], survey, parent_id=q["id"])

    @classmethod
    def handle_sessions(cls, submissions, survey):
        """
        For each submission:
          • Append one row to cls._sessions
          • Append N rows to cls._responses (filtering by question_filter on name/text)
        """
        for sub in submissions:
            # Build session‐row
            created = datetime.datetime.fromtimestamp(sub["timestamp"]["created"] / 1000, datetime.timezone.utc)
            updated = datetime.datetime.fromtimestamp(sub["timestamp"]["updated"] / 1000, datetime.timezone.utc)
            sess = {
                "survey_id": survey["external_id"],
                "survey_name": survey["internal_name"],
                "session_id": sub["responseId"],
                "mw_participant_alias": sub["userId"],
                "trigger_type": sub.get("trigger", {}).get("type"),
                "started_at_utc": created,
                "ended_at_utc": updated,
            }
            cls._sessions.append(sess)

            # if no questions specified, skip responses
            if not cls.question_filter:
                continue

            # Build responses
            for qid, ans in sub["questionValues"].items():
                # Lookup this qid in the questions table to get name/text
                qrows = [q for q in cls._questions if q["question_id"] == qid]
                if not qrows:
                    continue
                qinfo = qrows[0]
                if cls.question_filter and not qinfo["question_name"] in cls.question_filter:
                    continue

                # timestamps if present
                opened = responded = None
                if ans.get("timestamp"):
                    created = ans["timestamp"]["created"]
                    updated = ans["timestamp"]["updated"]
                    opened = cls.date_time_tz_to_dt(created["date"], created["time"], sub["timeZoneReadable"])
                    responded = cls.date_time_tz_to_dt(updated["date"], updated["time"], sub["timeZoneReadable"])

                resp = {
                    "session_id": sub["responseId"],
                    "question_id": qid,
                    "question_name": qinfo["question_name"],
                    "question_text": qinfo["text"],
                    "content": ans.get("response"),
                    "skipped": ans.get("response") in ("SKIPPED", "NO_ANSWER"),
                    "not_seen": ans.get("response") in ('CONDITION_SKIPPED', 'DYNAMIC_CONDITION_SKIPPED'),
                    "opened_at": opened,
                    "responded_at": responded,
                    "duration_seconds": (responded - opened).total_seconds()
                    if opened and responded else None,
                }
                cls._responses.append(resp)
