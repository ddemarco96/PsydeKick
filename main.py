# main.py
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import pytz
import streamlit as st
from streamlit_option_menu import option_menu

from workflows import payments, tagging, config_explorer
from utils import background_monitor
from workflows.download import MetricWireImporter

# -----------------------------------------------------------------------------
# Page config + CSS
# -----------------------------------------------------------------------------
st.set_page_config(page_title="PsydeKick", layout="wide")
with open(".streamlit/style.css") as css:
    st.markdown(f"<style>{css.read()}</style>", unsafe_allow_html=True)
# -----------------------------------------------------------------------------
# Sidebar: Study selector, page nav, delete fxns, and versioning
# -----------------------------------------------------------------------------
st.sidebar.markdown("# 🔬 PsydeKick", unsafe_allow_html=True)

# Study selector
settings_config = Path("config") / "settings.csv"
studies = []
settings_df, study_settings = None, None
if settings_config.exists():
    settings_df = pd.read_csv(settings_config, dtype=str)
    if "study_name" in settings_df.columns:
        studies = settings_df["study_name"].dropna().unique().tolist()
else:
    st.error("No settings.csv found. Please create one in the config folder with a 'study_name' column.")
study_name = st.sidebar.selectbox("Select study", studies)
if study_name and settings_df is not None:
    study_settings = settings_df[settings_df["study_name"] == study_name].iloc[0]



# Page nav as a vertical icon menu
with st.sidebar:
    page = option_menu(
        menu_title=None,
        options=[
            "Download",
            "Tag and visualize",
            "Payments",
            "Config explorer",
            "Settings",
            "FAQs"
        ],
        icons=[
            "cloud-download",
            "tag",
            "cash",
            "gear",
            "sliders",
            "question-circle"
        ],
        menu_icon="cast",
        default_index=0,
        orientation="vertical",
        key="page_nav"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Auto-delete and auto quit utils
# ─────────────────────────────────────────────────────────────────────────────

# Initialize background monitoring
background_monitor.init_background_monitor()
DATA_ROOT = Path("data")
# Check for background signals
background_monitor.check_and_handle_signals()

# Manage auto-delete timer setup
background_monitor.manage_auto_delete_timer(DATA_ROOT)

st.sidebar.markdown("---")
background_monitor.render_auto_delete_status()
background_monitor.render_auto_delete_buttons(DATA_ROOT)
background_monitor.render_auto_quit_status()
background_monitor.render_auto_quit_buttons(DATA_ROOT)
st.sidebar.markdown("---")


def get_app_version() -> str:
    version_file = Path(__file__).parent / "VERSION"
    try:
        return version_file.read_text().strip()
    except FileNotFoundError:
        return "?.?.?"


APP_VERSION = get_app_version()

st.sidebar.markdown(
    f"""
    <div class="sidebar-footer">
      Version: <strong>{APP_VERSION}</strong>
    </div>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Data paths
# -----------------------------------------------------------------------------

data_dir = Path("data") / study_name
sessions_csv = data_dir / "sessions.csv"
questions_csv = data_dir / "questions.csv"
responses_csv = data_dir / "responses.csv"
tagged_csv = data_dir / "tagged_sessions.csv"
config_dir_base = Path("config")
# Tagging config files
tag_meta_csv = config_dir_base / "tagging" / study_name / "tags.csv"

# -----------------------------------------------------------------------------
# PAGE 1: Data & Download & Match IDs & Raw Tables
# -----------------------------------------------------------------------------
if page == "Download":
    st.title("1. Download")
    st.markdown(
        "This page is for downloading the data from MetricWire needed for tagging and payments."
    )
    # Download form
    st.header("API download form")
    # show last update
    if sessions_csv.exists():
        try:
            df_old = pd.read_csv(sessions_csv, parse_dates=["started_at_utc"])
            df_old["started_at_utc"] = pd.to_datetime(df_old["started_at_utc"], format="ISO8601")
            # check for any NA values in the started_at_utc column
            last = df_old["started_at_utc"].max().strftime("%Y-%m-%d %H:%M:%S")
            st.info(f"Latest session started: **{last} (UTC)**")
        except Exception as e:
            st.warning(f"Could not parse existing sessions.csv: {e}")

    data_root = Path("data")
    config_dir = Path("config/download") / study_name
    cfg_files = sorted(f.name for f in config_dir.glob("*.csv"))
    if not cfg_files:
        st.error("No config files found. You can create them in the Config explorer.")
        st.stop()
    with st.form("download_form"):
        st.info(
            "You can find your credentials [here](https://catalyst.metricwire.com/profile/edit) once you've requested them from MetricWire.")
        api_key = st.text_input("Client ID", type="password")
        api_secret = st.text_input("Client secret", type="password")

        if cfg_files:
            question_csvs = filter(lambda x: "question" in x, cfg_files)
            question_cfg = st.selectbox("Question-filter config (CSV)",
                                        options=question_csvs if question_csvs else cfg_files,
                                        help="Which questions should the download save responses to?")

            alias_csvs = filter(lambda x: "alias" in x, cfg_files)

            alias_cfg = st.selectbox("Alias CSV",
                                     options=alias_csvs if alias_csvs else cfg_files,
                                        help="Which alias config should be used to match participant IDs?")
            st.expander("What's an alias?", expanded=False).markdown(
                "The alias is what the participant is called in the data source (MetricWire). For example, the participant you call "
                "*participant-1001* might have a hard to read UserId in MetricWire like *a1b2c3d4e5f6g7h8i9j0* that we call an alias.\n\n"
                "In this step, we add the within_study_id to the sessions.csv file, so you can use it in the tagging and payments steps.\n\n"
            )

        submit = st.form_submit_button("Download data")

    if submit:
        if not api_key or not api_secret:
            st.error("Provide both Client ID & Secret.")
        else:
            # build filter
            if question_cfg:
                try:
                    qf = pd.read_csv(config_dir / question_cfg).iloc[:, 0].astype(str).tolist()
                except:
                    st.warning("Could not read question config; saving all by default.")
                    qf = []
            else:
                qf = []
            status = st.empty()
            prog = st.progress(0)

            def report(done, total):
                prog.progress(int(done / total * 100))

            try:
                status.info("Downloading…")
                MetricWireImporter.start(
                    study_name=study_name,
                    credentials={"client_id": api_key, "client_secret": api_secret},
                    question_filter=qf,
                    output_dir=str(data_root),
                    progress_callback=report
                )
                prog.progress(100)
                status.success("Download complete!", icon="✅")

                alias_df = pd.read_csv(config_dir / alias_cfg, dtype=str)
                alias_map = alias_df.set_index("metricwire_alias")["within_study_id"].to_dict()
                if not sessions_csv.exists():
                    st.error("No sessions.csv found.")
                else:
                    sess_df = pd.read_csv(sessions_csv, parse_dates=["started_at_utc", "ended_at_utc"])
                    sess_df["within_study_id"] = sess_df["mw_participant_alias"].map(alias_map)
                    sess_df.to_csv(sessions_csv, index=False)
                    st.success("IDs matched & sessions.csv updated!")
                    time.sleep(1)
                    # Reset/Start the auto-delete timer after a successful download
                    st.session_state.delete_deadline = datetime.now(pytz.utc) + timedelta(
                        minutes=st.session_state.auto_delete_minutes
                    )
                    st.rerun()  # Rerun to reflect the new/reset timer in the sidebar

            except Exception as e:
                status.error(f"Error: {e}", icon="🚨")

    # Raw tables
    st.header("Raw CSVs")
    tabs = st.tabs(["Sessions", "Questions", "Responses"])
    with tabs[0]:
        if sessions_csv.exists():
            df = pd.read_csv(sessions_csv, parse_dates=["started_at_utc", "ended_at_utc"])
            st.dataframe(df)
        else:
            st.info("No sessions downloaded.")
    with tabs[1]:
        if questions_csv.exists() and list(filter(lambda x: "question" in x, cfg_files)):
            st.dataframe(pd.read_csv(questions_csv))
        else:
            st.info("No questions downloaded. Make sure you have a question config selected.")
    with tabs[2]:
        if responses_csv.exists() and list(filter(lambda x: "question" in x, cfg_files)):
            st.dataframe(pd.read_csv(responses_csv, parse_dates=["opened_at", "responded_at"]))
        else:
            st.info("No responses downloaded. Make sure you have a question config selected.")

elif page == "Tag and visualize":
    st.title("2. Tag sessions and visualize")
    st.markdown(
        "This page is for tagging sessions based on configured workflows and visualizing the results."
    )

    # ensure they have all required configs
    config_dir = Path("config/tagging") / study_name
    files = ['workflows.csv', 'condition_groups.csv', 'conditions.csv', 'condition_questions.csv', 'tags.csv']
    missing_files = [f for f in files if not (config_dir / f).exists()]
    if missing_files:
        st.error(f"Missing required config files for tagging: {', '.join(missing_files)}")
        st.stop()

    # ─────────────────────────────────────────────────────────────────────────
    # 1) Run Tagging Workflow
    # ─────────────────────────────────────────────────────────────────────────
    if st.button("Run tagging workflow"):
        with st.spinner("Tagging…"):
            tagging.run_tagging(study_name, base_dir="tmp")
        st.success("Tagging complete!")

    tagged_csv = data_dir / "tagged_sessions.csv"
    if not tagged_csv.exists():
        st.warning("No tagged_sessions.csv found. Please run the tagging workflow to continue.", icon="ℹ️")
        st.stop()

    # ─────────────────────────────────────────────────────────────────────────
    # 2) Controls: timezone, date range, tag selection, participant filter
    # ─────────────────────────────────────────────────────────────────────────

    # a) timezone
    common_zones = ["America/New_York", "UTC"]
    user_tz = st.selectbox("Timezone", common_zones, index=0)

    # b) date range
    date_range = st.selectbox("Date range", ["Past week", "Past month", "All time"])
    now_user = datetime.now(pytz.UTC).astimezone(pytz.timezone(user_tz))
    if date_range == "Past week":
        cutoff = now_user - timedelta(days=7)
    elif date_range == "Past month":
        cutoff = now_user - timedelta(days=30)
    else:
        cutoff = None  # will set later

    # c) participant filter
    pid_pattern = st.text_input(
        "Participant filter (partial matches allowed)",
        value="",
        help="e.g. '100' to only include participants whose ID includes '100' (Matches: ppt-1001, ppt-1002, etc. Ignores ppt-2001, ppt-3001, etc.)"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 3) Load & explode tagged_sessions.csv
    # ─────────────────────────────────────────────────────────────────────────
    tagged = pd.read_csv(tagged_csv, parse_dates=["started_at_utc"])
    tagged["session_tags"] = tagged["session_tags"].fillna("")
    df = (
        tagged.assign(
            local_ts=lambda d: d["started_at_utc"]
            .dt.tz_convert(user_tz),
            tag=lambda d: d["session_tags"].str.split(";")
        )
        .explode("tag")
        .query("tag != ''")
    )
    df["local_day"] = df["local_ts"].dt.date.astype(str)

    # apply “All time” fallback
    if cutoff is None:
        cutoff = df["local_ts"].min()

    # ─────────────────────────────────────────────────────────────────────────
    # 4) Tag & participant filtering
    # ─────────────────────────────────────────────────────────────────────────
    # tags multiselect
    all_tags = sorted(df["tag"].unique())
    def_tags = study_settings.default_tags.split("|") if study_settings else []
    tags_sel = st.multiselect("Tags to show", all_tags, default=def_tags)

    # apply filters: date, tag, participant substring
    mask = (
            (df.local_ts >= cutoff) &
            (df.tag.isin(tags_sel))
    )
    if pid_pattern:
        mask &= df["within_study_id"].str.contains(pid_pattern, case=False, na=False)

    dfv = df[mask].copy()
    if dfv.empty:
        st.warning("No data matches these filters.", icon="⚠️")
        st.stop()

    # ─────────────────────────────────────────────────────────────────────────
    # 5) Load tag colors
    # ─────────────────────────────────────────────────────────────────────────
    color_map = {}
    if tag_meta_csv.exists():
        tags_meta = pd.read_csv(tag_meta_csv, dtype=str)
        color_map = dict(zip(tags_meta.title, tags_meta.color))

    # ─────────────────────────────────────────────────────────────────────────
    # 6) Build grouped bar chart (day × tag)
    # ─────────────────────────────────────────────────────────────────────────
    bars = (
        alt.Chart(dfv)
        .mark_bar()
        .encode(
            x=alt.X("local_day:O", title="Day", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("count():Q", title="Sessions"),
            color=alt.Color(
                "tag:N",
                scale=alt.Scale(domain=list(color_map.keys()),
                                range=list(color_map.values())),
                legend=alt.Legend(title="Tag")
            ),
            xOffset="tag:N"
        )
        .properties(width=600, height=300)
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 7) Display chart
    # ─────────────────────────────────────────────────────────────────────────
    st.subheader("Tagged sessions by day")
    st.altair_chart(bars, use_container_width=True)

    # ─────────────────────────────────────────────────────────────────────────
    # 8) Tabs: session & response detail filtered by click or manual input
    # ─────────────────────────────────────────────────────────────────────────
    st.subheader("Explore tagged sessions and responses")
    tab_sess, tab_resp = st.tabs(["Sessions", "Responses"])

    # a) shared filters for both
    with tab_sess:
        st.markdown("**Filter sessions**")
        date_input = st.date_input(
            "Session date (local)",
            value=None,
            key="sess_date"
        )
        pid_input = st.text_input("Participant ID", "")
        df_sess = tagged.copy()
        # convert and apply
        df_sess["local_ts"] = (
            df_sess["started_at_utc"]
            .dt.tz_convert(user_tz)
        )
        df_sess["local_day"] = df_sess["local_ts"].dt.date.astype(str)

        if date_input:
            df_sess = df_sess[df_sess["local_day"] == str(date_input)]
        if pid_input:
            df_sess = df_sess[df_sess["within_study_id"].astype(str).str.contains(pid_input)]
        st.dataframe(df_sess, use_container_width=True)

    with tab_resp:
        st.markdown("**Filter responses**")
        resp_date = st.date_input(
            "Session date (local)",
            value=None,
            key="resp_date"
        )
        resp_pid = st.text_input("Participant ID", key="rpid")
        # load raw responses
        resp = pd.read_csv(responses_csv, parse_dates=["opened_at", "responded_at"])
        # join with sessions to get local_day & participant
        sess = pd.read_csv(sessions_csv, parse_dates=["started_at_utc"])
        sess["local_day"] = (
            sess["started_at_utc"]
            .dt.tz_convert(user_tz)
            .dt.date.astype(str)
        )
        merged = resp.merge(
            sess[["session_id", "within_study_id", "local_day"]],
            left_on="session_id", right_on="session_id", how="left",
            suffixes=("", "_sess")
        )
        df_resp = merged
        if resp_date:
            df_resp = df_resp[df_resp["local_day"] == str(resp_date)]
        if resp_pid:
            df_resp = df_resp[df_resp["within_study_id"].astype(str).str.contains(resp_pid)]
        st.dataframe(df_resp, use_container_width=True)
# ──────────────────────────────────────────────────────────────────────────────
# PAGE 3: Calculate Payments & Compliance (one participant at a time)
# ──────────────────────────────────────────────────────────────────────────────
elif page == "Payments":
    st.title("3. Calculate payments and compliance")
    st.markdown(
        "This page is for calculating payments and compliance for a single participant."
    )

    # --- Initialize session state ---
    if "payments_selected_participant_id" not in st.session_state:
        st.session_state.payments_selected_participant_id = None
    if "payments_start_date" not in st.session_state:
        st.session_state.payments_start_date = date.today()
    if "payments_tz_name" not in st.session_state:
        st.session_state.payments_tz_name = "America/New_York"
    if "payments_calcs_done" not in st.session_state:
        st.session_state.payments_calcs_done = False
    if "payments_df_part" not in st.session_state:
        st.session_state.payments_df_part = pd.DataFrame()
    if "payments_auto_counts" not in st.session_state:
        st.session_state.payments_auto_counts = {}

    cfg_payments_dir = config_dir_base / "payments" / study_name
    sessions_csv_path = data_dir / "sessions.csv"

    rate_file, schema_file = payments.render_config_selection_ui(study_name, cfg_payments_dir)

    rates_df, schema_df = None, None
    if rate_file and schema_file:
        rates_df = payments.load_rates(rate_file)
        schema_df = payments.load_schema(schema_file)
        if rates_df.empty or schema_df.empty:
            st.warning("Failed to load valid data from configuration files.")
            st.stop()
    else:
        st.info("Please select both rate and schema configuration files.")
        st.stop()

    payments.render_schema_preview_ui(schema_df)
    st.markdown("---")

    if not sessions_csv.exists():
        st.warning("No sessions.csv found. Please download data to continue.")
        st.stop()

    prev_participant = st.session_state.payments_selected_participant_id
    selected_pid, all_sessions, new_start_date, new_user_tz = payments.render_participant_and_settings_ui(
        study_name, sessions_csv_path,
        st.session_state.payments_selected_participant_id,
        st.session_state.payments_start_date,
        st.session_state.payments_tz_name
    )
    st.session_state.payments_selected_participant_id = selected_pid
    st.session_state.payments_start_date = new_start_date
    if new_user_tz: st.session_state.payments_tz_name = new_user_tz.zone

    if prev_participant != selected_pid and selected_pid is not None:
        st.session_state.payments_calcs_done = False
        st.session_state.payments_df_part = pd.DataFrame()
        st.session_state.payments_auto_counts = {}
        st.info(f"Participant changed to {selected_pid}. Please click 'Calculate'.")

    st.markdown("---")

    if st.session_state.payments_selected_participant_id and rates_df is not None and not rates_df.empty and schema_df is not None and not schema_df.empty:
        if st.button(f"Calculate Payments & Compliance for {st.session_state.payments_selected_participant_id}",
                     key=f"calc_pay_{study_name}_{st.session_state.payments_selected_participant_id}"):
            with st.spinner("Performing calculations..."):
                df_part_result, auto_counts_result = payments.perform_payment_calculations(
                    all_sessions,
                    st.session_state.payments_selected_participant_id,
                    rates_df,
                    pytz.timezone(st.session_state.payments_tz_name)
                )
            st.session_state.payments_df_part = df_part_result
            st.session_state.payments_auto_counts = auto_counts_result
            st.session_state.payments_calcs_done = True
            st.success("Calculations complete!")
            st.rerun()
    elif not st.session_state.payments_selected_participant_id:
        st.info("Please select a participant to enable calculations.")

    st.markdown("---")

    if st.session_state.get('payments_calcs_done',
                            False) and st.session_state.payments_selected_participant_id and schema_df is not None and rates_df is not None:
        payments.render_compliance_charts_ui(
            st.session_state.payments_df_part,
            st.session_state.payments_selected_participant_id,
            schema_df, rates_df,
            st.session_state.payments_start_date,
            pytz.timezone(st.session_state.payments_tz_name)
        )
    elif st.session_state.payments_selected_participant_id:
        st.caption("Compliance details will appear here after clicking 'Calculate'.")

    st.markdown("---")

    if st.session_state.payments_selected_participant_id and rates_df is not None and not rates_df.empty:
        payments.render_compensation_calculator_ui(
            study_name,
            st.session_state.payments_selected_participant_id,
            rates_df,
            st.session_state.get('payments_auto_counts', {})
        )
    else:
        st.caption("Calculator will appear here once a participant and rate configurations are selected.")

# ─────────────────────────────────────────────────────────────────────────────
# PAGE 4: Config explorer
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Config explorer":
    config_explorer.render_page(study_name)
# ─────────────────────────────────────────────────────────────────────────────
# PAGE 5: Settings
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Settings":
    st.title("Settings")

    background_monitor.render_settings()

elif page == "FAQs":
    st.title("FAQs and gotchas")
    st.markdown(
        "This page is for frequently asked questions, gotchas, and troubleshooting."
    )
    st.markdown(
        """
        ### Is data being stored locally?
        Yes, limited data is downloaded and stored locally temporarily for tagging and payments. 
        It is deleted automatically after a set period of time or any time you click the delete button on the side nav.
        """
    )
    st.expander("More details", expanded=False).markdown(
        """
        The application downloads data from MetricWire and stores it in the *data/[study name]* folder. 
        This data is used for tagging and payments. The data is deleted automatically after a set period of time (default: 30 minutes) 
        or any time you click the delete button on the side nav.
        """
    )
    st.markdown(
        """
        ### Will deleting the data delete it from MetricWire?
        No, deleting the data will not delete it from MetricWire or affect anyone else on the team.
        """
    )
    st.expander("More details", expanded=False).markdown(
        """
        The application downloads a copy of the data from MetricWire and stores it locally. The data on your device is 
        not linked to the data on MetricWire or shared in any way.
        """
    )
    st.markdown(
        """
        ### What if I need to keep the data longer?
        You can change the auto-delete timer in the settings page.
        """
    )
    st.markdown(
        """
        ### Can I download the data again?
        Yes, you can download the data again at any time. The application will overwrite the existing data.
        """
    )
    st.markdown(
        """
        ### How much space do I need for the data?
        It varies based on which study and question filters you have set up but for what we've seen so far, it's been 
        less than 5MG per study as of May 2025.
        """
    )
    st.markdown(
        """
        ### Why are there test accounts in the data?
        The download pulls all data in the chosen study on MetricWire. It does not filter out test accounts, but you 
        can filter them out in both the tagging and payments workflows.
        """
    )
    st.markdown(
        """
        ### I can't find data for a participant I know exists in MetricWire. What should I do?
        Things to check:
        1. Confirm the participant is in the study you selected in the sidebar.
        2. Confirm the participant ID doesn't have any typos or extra spaces.
        3. Confirm the participant has completed at least one session in the study.
        4. Confirm the participant ID you're searching for is present in the alias config file you selected in the download step. (You can download a copy in the config explorer.)
        5. Confirm the participant's MetricWire ID is present in the sessions data.
        """
    )
    st.markdown(
        """
        ### Why is there a space in my participant IDs?
        The participant ID in MetricWire may be split across the first and last name fields in your study and combined into a single name 
        column on export. The alias accepts anything in the within_study_id column, so it is up to the team to decide whether to keep the space or not. 
        """
    )

