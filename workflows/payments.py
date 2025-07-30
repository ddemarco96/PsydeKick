# workflows/payments.py
import pandas as pd
from pathlib import Path
from datetime import datetime, date, time, timedelta
import pytz
from typing import List, Optional, Tuple, Dict

import streamlit as st
import altair as alt


def load_rates(path: Path) -> pd.DataFrame:
    """
    Load rates CSV. Expects columns: id, rate, reason.
    Returns DataFrame with columns [id(str), rate_amount(float), reason(str)].
    """
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        if "rate" not in df.columns or "id" not in df.columns or "reason" not in df.columns:
            st.error(f"Rates file '{path.name}' is missing required columns (id, rate, reason).")
            return pd.DataFrame(columns=["id", "reason", "rate_amount"])
        df["rate_amount"] = df["rate"].str.replace(r"[$,]", "", regex=True).astype(float)
        df["id"] = df["id"].astype(str)
        df["reason"] = df["reason"].astype(str).str.strip()
        return df[["id", "reason", "rate_amount"]]
    except Exception as e:
        st.error(f"Error loading rates from '{path.name}': {e}")
        return pd.DataFrame(columns=["id", "reason", "rate_amount"])


def load_schema(path: Path) -> pd.DataFrame:
    """
    Load schema CSV. Expects columns: name, rate_id, num_possible_per_day, num_days, bonus_threshold.
    Returns DF with these columns and bonus_rate_id if present.
    """
    try:
        raw = pd.read_csv(path, dtype=str, keep_default_na=False)
        expected_cols = ["name", "rate_id", "num_possible_per_day", "num_days", "bonus_threshold"]
        for col in expected_cols:
            if col not in raw.columns:
                st.error(f"Schema file '{path.name}' is missing required column: '{col}'.")
                return pd.DataFrame(columns=expected_cols + ["bonus_rate_id"])

        raw["num_days"] = raw["num_days"].astype(int)
        raw["num_possible_per_day"] = raw["num_possible_per_day"].astype(int)
        raw["bonus_threshold"] = raw["bonus_threshold"].replace("", "0").astype(int)
        raw["rate_id"] = raw["rate_id"].astype(str)
        raw["bonus_rate_id"] = raw.get("bonus_rate_id", pd.Series(dtype=str)).fillna("").astype(str)
        raw["name"] = raw["name"].astype(str)
        return raw[["name", "rate_id", "num_possible_per_day", "num_days", "bonus_rate_id", "bonus_threshold"]]
    except Exception as e:
        st.error(f"Error loading schema from '{path.name}': {e}")
        return pd.DataFrame(
            columns=["name", "rate_id", "num_possible_per_day", "num_days", "bonus_rate_id", "bonus_threshold"])


def get_valid_participants(sessions: pd.DataFrame) -> List[str]:
    """
    Get unique participant IDs from sessions DataFrame. Used for searching in the within_study_id input field.
    :param sessions:
    :return:
    """
    if "within_study_id" not in sessions.columns or sessions["within_study_id"].empty:
        return []
    return sorted(sessions["within_study_id"].astype(str).dropna().unique())


def filter_sessions_by_participant(
        sessions: pd.DataFrame, participant_id: str, tz: pytz.BaseTzInfo
) -> pd.DataFrame:
    if participant_id is None or "within_study_id" not in sessions.columns: return pd.DataFrame()
    df = sessions[sessions["within_study_id"] == participant_id].copy()
    if "started_at_utc" not in df.columns: return pd.DataFrame()
    df["started_at_utc"] = pd.to_datetime(df["started_at_utc"], format="ISO8601")
    df["local_ts"] = df["started_at_utc"].dt.tz_convert(tz)
    df["local_day"] = df["local_ts"].dt.date
    return df


def has_sessions_after_end(
        sessions: pd.DataFrame, start_date: date, days: int, tz: pytz.BaseTzInfo
) -> bool:
    """
    Check if there are any sessions after the end of a given schema period.
    """
    if "local_ts" not in sessions.columns or sessions.empty: return False
    end_dt_inclusive = datetime.combine(start_date + timedelta(days=int(days) - 1), time.max).astimezone(tz)
    return (sessions["local_ts"] > end_dt_inclusive).any()


def get_rate_reason(rates: pd.DataFrame, rate_id: str) -> str:
    """Get the reason for a given rate ID from the rates DataFrame."""
    if "id" not in rates.columns or "reason" not in rates.columns or rates.empty or not rate_id: return ""
    sub = rates[rates["id"] == rate_id]
    return sub["reason"].iloc[0] if not sub.empty else ""


def get_rate_amount(rates_df: pd.DataFrame, rate_id: str) -> float:
    """Get the rate amount in a math-friendly format for a given rate ID from the rates DataFrame."""
    if rates_df.empty or "id" not in rates_df.columns or "rate_amount" not in rates_df.columns or not rate_id:
        return 0.0
    rate_row = rates_df[rates_df["id"] == rate_id]
    if not rate_row.empty:
        return float(rate_row["rate_amount"].iloc[0])
    return 0.0


def compute_daily_counts(
        sessions: pd.DataFrame, start_date: date, days: int, tz: pytz.BaseTzInfo, reason_filter: Optional[str] = None
) -> pd.DataFrame:
    """
    Computes how many survey sessions took place each day over a specific date range.

    Data can be further filtered by a compensation reason string (e.g., a type of survey).

    :param sessions: Input DataFrame containing session data. Expected columns
        include "local_ts" for timestamps and "survey_name" for filtering.
    :param start_date: The starting date of the range for daily counts.
    :param days: Number of days to calculate daily counts from the start_date.
    :param tz: Time zone of the provided timestamps in the sessions DataFrame.
    :param reason_filter: Optional filter string; used to match survey names
        that contain the substring specified.
    :return: DataFrame with daily counts containing columns `date` and `count`.
    """
    idx_end_date = start_date + timedelta(days=int(days) - 1)
    idx = pd.date_range(start=start_date, end=idx_end_date, freq="D")
    daily_df = pd.DataFrame({"date": idx})

    if "local_ts" not in sessions.columns or "survey_name" not in sessions.columns or sessions.empty:
        daily_df["count"] = 0
        return daily_df

    win_start = datetime.combine(start_date, time.min).astimezone(tz)
    win_end = datetime.combine(idx_end_date, time.max).astimezone(tz)
    df_windowed = sessions[(sessions["local_ts"] >= win_start) & (sessions["local_ts"] <= win_end)].copy()

    if reason_filter:
        df_windowed = df_windowed[
            df_windowed["survey_name"].astype(str).str.contains(str(reason_filter), case=False, na=False)]

    if not df_windowed.empty:
        observed_counts_df = df_windowed.assign(
            date=lambda d: d["local_ts"].dt.normalize().dt.tz_localize(None)
        ).groupby("date").size().rename("count").reset_index()
        daily_df = daily_df.merge(observed_counts_df, on="date", how="left")
        daily_df["count"] = daily_df["count"].fillna(0).astype(int)
    else:
        daily_df["count"] = 0
    return daily_df


def compute_bonus_days(daily_counts: pd.DataFrame, threshold: int) -> int:
    """Given a DataFrame of daily counts, compute the number of days where the count met or exceeded the threshold."""
    if threshold <= 0 or "count" not in daily_counts.columns or daily_counts.empty: return 0
    return int((daily_counts["count"] >= threshold).sum())


def compute_base_rate_counts(sessions: pd.DataFrame, rates: pd.DataFrame) -> pd.DataFrame:
    """Count the number of sessions for each rate reason. I.e., auto-detected/non-manual counts."""
    rows = []
    if "survey_name" not in sessions.columns or rates.empty or "reason" not in rates.columns or "rate_amount" not in rates.columns:
        return pd.DataFrame(columns=["rate_reason", "rate_amount", "count"])

    sess_copy = sessions.copy()
    sess_copy["survey_name_lc"] = sess_copy["survey_name"].astype(str).str.lower().fillna("")

    for _, r_row in rates.iterrows():
        reason = str(r_row["reason"])
        amt = float(r_row["rate_amount"])
        cnt = 0
        if reason:
            cnt = int(sess_copy["survey_name_lc"].str.contains(reason.lower(), na=False, regex=False).sum())
        rows.append({"rate_reason": reason, "rate_amount": amt, "count": cnt})
    return pd.DataFrame(rows)


def compute_stats(
        start_date: date, tz: pytz.BaseTzInfo, schema_row: dict, daily: pd.DataFrame
) -> Tuple[int, int]:
    """
    Compute the number of possible and completed sessions based on the schema row and daily counts.
    """
    today_local = datetime.now(tz).date()
    days_from_start_to_today = (today_local - start_date).days + 1
    num_days_elapsed_in_schema = min(days_from_start_to_today, int(schema_row["num_days"]))
    if num_days_elapsed_in_schema < 0: num_days_elapsed_in_schema = 0

    num_possible = num_days_elapsed_in_schema * int(schema_row["num_possible_per_day"])
    num_completed = 0
    if "count" in daily.columns and not daily.empty:
        relevant_daily_counts = daily.head(num_days_elapsed_in_schema)
        num_completed = relevant_daily_counts['count'].sum()
    return int(num_possible), int(num_completed)


# --- UI Rendering Functions ---

def render_config_selection_ui(study_name: str, cfg_payments_dir: Path) -> Tuple[Optional[Path], Optional[Path]]:
    st.markdown("#### 1. Select Configuration Files")
    rate_file_path, schema_file_path = None, None
    # Populate the selects with any config starting with "rates" or "schema" to allow for versioning in the filename.
    rate_files = sorted(f.name for f in cfg_payments_dir.glob("rates*.csv"))
    schema_files = sorted(f.name for f in cfg_payments_dir.glob("schema*.csv"))

    if not rate_files: st.error(f"No rate configuration files (rates*.csv) found in `{cfg_payments_dir}`.")
    if not schema_files: st.error(f"No schema configuration files (schema*.csv) found in `{cfg_payments_dir}`.")
    if not rate_files or not schema_files: return None, None

    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        rate_sel_file = st.selectbox("Rates CSV", rate_files, key=f"payments_rate_sel_{study_name}")
        if rate_sel_file: rate_file_path = cfg_payments_dir / rate_sel_file
    with col_cfg2:
        schema_sel_file = st.selectbox("Schema CSV", schema_files, key=f"payments_schema_sel_{study_name}")
        if schema_sel_file: schema_file_path = cfg_payments_dir / schema_sel_file
    return rate_file_path, schema_file_path


def render_schema_preview_ui(schema_df: Optional[pd.DataFrame]):
    if schema_df is not None and not schema_df.empty:
        with st.expander("View Schema Configuration Details", expanded=False):
            st.dataframe(schema_df, use_container_width=True)
    elif schema_df is not None:
        st.info("Schema data is empty. Cannot display preview.")


def render_participant_and_settings_ui(
        study_name: str, sessions_csv_path: Path, current_participant_id: Optional[str],
        current_start_date: date, current_tz_name: str
) -> Tuple[Optional[str], Optional[pd.DataFrame], Optional[date], Optional[pytz.BaseTzInfo]]:
    st.markdown("#### 2. Select Participant and Define Period")
    selected_participant_id, all_sessions_df = None, None
    start_date_val, user_tz_val = current_start_date, pytz.timezone(current_tz_name)

    if not sessions_csv_path.exists():
        st.error(f"Required `sessions.csv` not found at `{sessions_csv_path}`.")
        return None, None, start_date_val, user_tz_val
    try:
        all_sessions_df = pd.read_csv(sessions_csv_path, parse_dates=["started_at_utc", "ended_at_utc"])
        if "within_study_id" not in all_sessions_df.columns:
            st.error("`sessions.csv` is missing `within_study_id` column.")
            return None, all_sessions_df, start_date_val, user_tz_val
    except Exception as e:
        st.error(f"Error loading `sessions.csv`: {e}")
        return None, None, start_date_val, user_tz_val

    valid_ids = get_valid_participants(all_sessions_df)
    if not valid_ids: st.warning("No participant IDs found in `sessions.csv`.")

    pid_key_suffix = current_participant_id or 'none'
    participant_input_val = st.text_input(
        "Enter a participant ID (partial matches allowed)",
        value=current_participant_id if current_participant_id and current_participant_id in valid_ids else "",
        key=f"payments_participant_input_{study_name}_{pid_key_suffix}"
    )
    if participant_input_val:
        matched_ids = [pid for pid in valid_ids if participant_input_val.lower() in pid.lower()]
        if len(matched_ids) == 1:
            selected_participant_id = matched_ids[0]
        elif len(matched_ids) > 1:
            st.warning(f"Multiple matches for '{participant_input_val}'. Be more specific.")
        elif valid_ids:
            st.warning(f"No participant ID matching '{participant_input_val}'.")

    col_date, col_tz = st.columns(2)
    with col_date:
        start_date_val = st.date_input("Compliance start date", value=current_start_date,
                                       key=f"payments_start_date_{study_name}_{selected_participant_id or 'none'}")
    with col_tz:
        tz_options = ["America/New_York", "UTC"]
        try:
            default_tz_index = tz_options.index(current_tz_name)
        except ValueError:
            default_tz_index = 0

        tz_name_val = st.selectbox("Timezone", options=tz_options, index=default_tz_index,
                                   key=f"payments_tz_name_{study_name}_{selected_participant_id or 'none'}")
        user_tz_val = pytz.timezone(tz_name_val)
    return selected_participant_id, all_sessions_df, start_date_val, user_tz_val


def perform_payment_calculations(
        all_sessions_df: Optional[pd.DataFrame],
        participant_id: str,
        rates_df: pd.DataFrame,
        user_tz: pytz.BaseTzInfo
) -> Tuple[Optional[pd.DataFrame], Dict[str, int]]:  # Reverted: float for total_bonus_amount removed
    """
    Performs calculations and returns participant's session data and auto counts for base rates.
    Auto counts are the counts for reasons detected in MW.
    Bonus payments are NOT automatically calculated here.
    """
    if all_sessions_df is None or rates_df.empty or participant_id is None:
        return pd.DataFrame(), {}

    df_part = filter_sessions_by_participant(all_sessions_df, participant_id, user_tz)

    auto_counts_dict = {str(reason): 0 for reason in rates_df["reason"].unique()}
    if not df_part.empty:
        auto_counts_table = compute_base_rate_counts(df_part, rates_df)
        if not auto_counts_table.empty:
            auto_counts_dict = pd.Series(
                auto_counts_table["count"].values,
                index=auto_counts_table["rate_reason"]
            ).fillna(0).astype(int).to_dict()

    return df_part, auto_counts_dict


def render_compliance_charts_ui(
        df_part: pd.DataFrame, participant_id: str, schema_df: pd.DataFrame,
        rates_df: pd.DataFrame, start_date: date, user_tz: pytz.BaseTzInfo
):
    st.markdown("#### 3. Compliance Details & Bonus Calculations")
    if schema_df.empty:
        st.warning("Schema data is empty. Cannot display compliance charts.")
        return

    if df_part.empty and participant_id:
        st.info(f"No session data processed for {participant_id} to calculate detailed compliance.")

    if not df_part.empty:
        start_dt_local = datetime.combine(start_date, time.min).astimezone(user_tz)
        if "local_ts" in df_part and (df_part["local_ts"] < start_dt_local).any():
            st.warning(f"Participant has sessions before compliance start date {start_date.strftime('%b %d, %Y')}.")
        max_sch_days = schema_df["num_days"].max() if "num_days" in schema_df.columns and not schema_df.empty else 0
        if max_sch_days > 0 and has_sessions_after_end(df_part, start_date, max_sch_days, user_tz):
            st.warning(f"Participant has sessions beyond the max duration of defined schemas.")

    sch_tabs_list = schema_df["name"].tolist()
    if not sch_tabs_list:
        st.info("No payment schemas defined in the selected schema file.")
        return

    sch_tabs = st.tabs(sch_tabs_list)
    for i, schema_row_tuple in enumerate(schema_df.iterrows()):
        _, schema_row = schema_row_tuple
        schema_row_dict = schema_row.to_dict()
        with sch_tabs[i]: # given the selected schema, render the compliance chart and bonus details
            name = schema_row_dict["name"]
            days = int(schema_row_dict["num_days"])
            threshold = int(schema_row_dict["bonus_threshold"])  # This is for qualifying for bonus days
            rate_id_for_reason = str(schema_row_dict["rate_id"])
            reason = get_rate_reason(rates_df, rate_id_for_reason)

            daily = compute_daily_counts(df_part, start_date, days, user_tz, reason if reason else None)
            bonus_days_achieved = compute_bonus_days(daily, threshold)  # Number of days the bonus threshold was met

            num_possible, num_completed = compute_stats(start_date, user_tz, schema_row_dict, daily)
            percent_complete = round(num_completed / num_possible * 100, 1) if num_possible > 0 else 0.0

            st.markdown(
                f"##### Schema: {name}\n"
                f"*   **Period**: {start_date.strftime('%b %d, %Y')} → {(start_date + timedelta(days=days - 1)).strftime('%b %d, %Y')} ({days} days)\n"
                f"*   **Activity Target**: Surveys related to '{reason}' (Rate ID: {rate_id_for_reason})\n"
                f"*   **Bonus Days Achieved**: Days meeting ≥ {threshold} '{reason}' survey(s) = **{bonus_days_achieved} day(s)**\n"  # Highlight this
                f"*   **Overall Compliance**: {num_completed} completed / {num_possible} possible (**{percent_complete}%**)\n"
            )
            # (Rest of chart rendering logic remains the same)
            chart_daily_df = daily[daily['count'] > 0].copy()
            if not chart_daily_df.empty:
                bars = alt.Chart(chart_daily_df).mark_bar().encode(
                    x=alt.X("date:T", title="Date", axis=alt.Axis(format="%b %d")),
                    y=alt.Y("count:Q", title=f"'{reason}' Surveys"),
                    tooltip=[alt.Tooltip("date:T", title="Date"), alt.Tooltip("count:Q", title="Count")]
                ).properties(title=f"Daily '{reason}' Surveys")
                final_chart = bars
                if threshold > 0:  # Only add rule if there's a bonus threshold
                    rule = alt.Chart(pd.DataFrame({'threshold': [threshold]})).mark_rule(color="red", strokeDash=[4, 4],
                                                                                         size=2).encode(y='threshold:Q')
                    final_chart = (bars + rule)
                st.altair_chart(final_chart.properties(height=200), use_container_width=True)
            elif reason:
                st.caption(f"No '{reason}' surveys found for this schema period.")


def render_compensation_calculator_ui(
        study_name: str,
        participant_id: str,
        rates_df: pd.DataFrame,
        auto_detected_counts: Dict[str, int]
):
    st.markdown("#### 4. Compensation Calculator")
    if rates_df.empty:
        st.warning("Rates data is not available for the calculator.")
        return

    total_base_auto_payment = 0.0
    total_manual_add_payment = 0.0

    # Define a consistent minimum height for rows, similar to input fields
    min_row_height = "38px"  # Approximate height of st.number_input

    # Header
    header_cols = st.columns([3, 1.5, 1.5, 1.5, 2])
    headers_text = ["Rate reason", "Rate value", "Auto count", "Manual add", "Subtotal"]
    # CSS justify-content values corresponding to alignments
    css_horizontal_alignments = ["flex-start", "flex-end", "center", "center", "flex-end"]

    for i, header in enumerate(headers_text):
        justify_content = css_horizontal_alignments[i]
        with header_cols[i]:
            st.markdown(
                f"""<div style="display: flex; align-items: center; justify-content: {justify_content}; height: {min_row_height};">
                        <strong>{header}</strong>
                     </div>""",
                unsafe_allow_html=True
            )
    st.markdown("---")

    # Item rows
    for _, rate_row in rates_df.iterrows():
        reason, rate_value, rate_id = str(rate_row["reason"]), float(rate_row["rate_amount"]), str(rate_row["id"])
        auto_count = auto_detected_counts.get(reason, 0)

        total_base_auto_payment += (auto_count * rate_value)

        manual_add_key = f"payments_manual_add_{rate_id}_{study_name}_{participant_id}"
        item_cols = st.columns([3, 1.5, 1.5, 1.5, 2])

        # Column 0: Rate Reason (Left-aligned, vertically centered)
        with item_cols[0]:
            st.markdown(
                f"""<div style="display: flex; align-items: center; justify-content: flex-start; height: 100%; min-height: {min_row_height};">
                        {reason}
                     </div>""",
                unsafe_allow_html=True
            )
        # Column 1: Rate Value (Right-aligned, vertically centered)
        with item_cols[1]:
            st.markdown(
                f"""<div style="display: flex; align-items: center; justify-content: flex-end; height: 100%; min-height: {min_row_height};">
                        ${rate_value:,.2f}
                     </div>""",
                unsafe_allow_html=True
            )
        # Column 2: Auto Count (Center-aligned, vertically centered)
        with item_cols[2]:
            st.markdown(
                f"""<div style="display: flex; align-items: center; justify-content: center; height: 100%; min-height: {min_row_height};">
                        {auto_count}
                     </div>""",
                unsafe_allow_html=True
            )
        # Column 3: Manual Add (Streamlit number_input - will dictate its own alignment within its space)
        # The goal is for other cells to align with this one.
        with item_cols[3]:
            manual_add = st.number_input(
                label=f"manual_for_{rate_id}",
                min_value=0, step=1,
                key=manual_add_key,
                label_visibility="collapsed"
            )

        current_subtotal_for_rate = rate_value * (auto_count + manual_add)
        total_manual_add_payment += (manual_add * rate_value)

        # Column 4: Subtotal (Right-aligned, vertically centered)
        with item_cols[4]:
            st.markdown(
                f"""<div style="display: flex; align-items: center; justify-content: flex-end; height: 100%; min-height: {min_row_height};">
                        ${current_subtotal_for_rate:,.2f}
                     </div>""",
                unsafe_allow_html=True
            )
    st.markdown("---")

    # Payment Summary Section
    st.markdown("**Payment Summary**")
    # Using a single markdown for better control over spacing and alignment for this section
    summary_html = f"""
    <div style="line-height: 1.8;">
        <table style="width: 100%; border-collapse: collapse;">
            <tr>
                <td style="padding-right: 10px;">Total auto-detected activity:</td>
                <td style="text-align: right;">${total_base_auto_payment:,.2f}</td>
            </tr>
            <tr>
                <td style="padding-right: 10px;">Total manual payments:</td>
                <td style="text-align: right;">${total_manual_add_payment:,.2f}</td>
            </tr>
            <tr>
                <td style="padding-right: 10px;"><strong>Grand total earned:</strong></td>
                <td style="text-align: right;"><strong>${(total_base_auto_payment + total_manual_add_payment):,.2f}</strong></td>
            </tr>
        </table>
    </div>
    """
    st.markdown(summary_html, unsafe_allow_html=True)
