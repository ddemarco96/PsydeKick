"""
workflows/config_explorer.py
───────────────────────────
Streamlit workflow that lets researchers:

1. Upload new CSV files into the correct *config/{workflow}/{study}* folder.
2. Browse any existing config file and see:
      • a short human-readable explanation of what the file does
      • an “example” sentence built from the first row of data

main.py only needs to call   config_explorer.render_page(study_name)
"""

from pathlib import Path
from typing import Dict, Callable

import pandas as pd
import streamlit as st

STUDY_ROOTS: Dict[str, Path] = {
    "Download": Path("config/download"),
    "Tagging": Path("config/tagging"),
    "Payments": Path("config/payments"),
}

def save_uploaded_file(uploaded_file, destination: Path) -> None:
    """Persist the in-memory *uploaded_file* to *destination*."""
    # ensure the destination folder exists
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as f:
        f.write(uploaded_file.getbuffer())


# Config-type templates  (editable single-source-of-truth) --------------------
"""
This is a dictionary of templates for different config file types.

Each template is a dict with:
    • cols        : set of column names that identify the template
    • name        : human-readable name
    • explanation : static description (markdown)
    • example     : λ(row) → str
The *cols* set is used to identify the template type based on the columns in the uploaded CSV file.
The *example* function is used to generate a human-readable example sentence from the first row of data.
"""

CONFIG_TEMPLATES: Dict[str, Dict[str, Callable]] = {
    "alias_config": {
        "cols": {"within_study_id", "metricwire_alias"},
        "name": "an alias mapping",
        "explanation": (
            "This file maps Metricwire IDs (aliases) to a study's preferred participant ID after download."
        ),
        "example": lambda row: (
            "Any sessions that come in with the MetricWire alias "
            f"`{row['metricwire_alias']}` will be assigned to the "
            f"participant ID `{row['within_study_id']}`."
        ),
    },
    "question_filter_config": {
        "cols": {"question_labels"},
        "name": "a list of question labels",
        "explanation": (
            "Question filter list – each row is a MetricWire `variableName` "
            "to keep when downloading."
        ),
        "example": lambda row: (
            "Only responses to the question labelled "
            f"`{row['question_labels']}` (and any other labels in the file) "
            "will be saved."
        ),
    },
    "rate_config": {
        "cols": {"id", "rate", "reason"},
        "name": "a payment table",
        "explanation": (
            "The payment ('rates' on StudyPay) table maps activity to a compensation amount and reason."
        ),
        "example": lambda row: (
            f"Metricwire activity tagged with the reason **“{row['reason']}”** in the survey name "
            f"will be associated with rate-ID **{row['id']}** which pays **{row['rate']}**."
        ),
    },
    "schema_config": {
        "cols": {"name", "rate_id", "num_days", "schema_type"},
        "name": "a list of engagement schemas",
        "explanation": (
            "An engagement schema defines how much activity of a given type is expected for compliance and whether or "
            "not it is eligible for a bonus if a threshold is crossed."
        ),
        "example": lambda row: (
            f"The schema **{row['name']}** spans **{row['num_days']} days** "
            f"and uses base-rate ID **{row['rate_id']}**. It "
            f"{'has no' if row['bonus_rate_id'] == '' else 'has an'} associated bonus"
            f"{' with a threshold of **' + str(int(row['bonus_threshold'])) + '** activities' if row['bonus_rate_id'] != '' else ''}."
        ),
    },
    "tag_config": {
        "cols": {"title", "color", "explanation"},
        "name": "a list of tags",
        "explanation": (
            "Tag definitions (label, color, explanation) control how tagged sessions are visualized."
        ),
        "example": lambda row: (
            f"Sessions given the tag “{row['title']}” "
            f"will be displayed with color `{row['color']}`."
        ),
    },
    "workflow_config": {
        "cols": {"workflow_type", "tag_id"},
        "name": "a list of workflows",
        "explanation": (
            "A top level list of defined workflows – each row links logical condition-groups to a tag."
        ),
        "example": lambda row: (
            f"Workflow **{row['id']}** applies tag-ID **{row['tag_id']}** "
            f"when {'any' if row['logical_operator'] == 'OR' else 'all'} of its condition groups evaluate to *True*."
        ),
    },
    "condition_config": {
        "cols": {"group_id", "operator", "value"},
        "name": "a list of conditions",
        "explanation": "Individual logical conditions that are grouped and evaluated in workflows. "
                       "Skips can either be treated as `True` (skip behavior = 1) or `False` (skip behavior = 0).",
        "example": lambda row: (
            f"Condition **{row['id']}** belongs to Group {row['group_id']} and checks if a response is "
            f"`{row['operator']} {row['value']}`."
        ),
    },
    "group_config": {
        "cols": {"workflow_id", "logical_operator", "name"},
        "name": "a list of condition groups",
        "explanation": "These are the logical groups of conditions that are evaluated together.",
        "example": lambda row: (
            f"Group **{row['id']}** belongs to Workflow {row['workflow_id']} and evaluates to true if "
            f"{'any' if row['logical_operator'] == 'OR' else 'all'} "
            f"conditions that point to it are True."
        ),
    },
    "cond_question_config": {
        "cols": {"condition_id", "question_name"},
        "name": "a mapping of conditions to questions",
        "explanation": "This shows which questions a condition checks against.",
        "example": lambda row: (
            f"Condition **{row['condition_id']}** uses question "
            f"`{row['question_name']}`."
        ),
    },
}


def identify_config_type(columns: list[str]) -> str | None:
    """
    Return template-name string whose *cols* are a subset of *columns*.
    If no template matches, return None.
    """
    col_set = set(columns)
    for name, tpl in CONFIG_TEMPLATES.items():
        if tpl["cols"].issubset(col_set):
            return name
    return None


def describe_config_file(path: Path) -> str:
    """
    Produce markdown with “explanation” + “example” derived from *path*.
    Falls back gracefully when the structure is unknown.
    """
    try:
        df = pd.read_csv(path, nrows=5)  # small read – fast & safe
    except Exception as exc:
        return f"Could not read CSV – {exc}"

    cfg_type = identify_config_type(df.columns.tolist())
    if cfg_type is None:
        return (
            "### Unrecognized configuration file – no info available.\n\n"
        )

    template = CONFIG_TEMPLATES[cfg_type]
    explanation = template["explanation"]

    if not df.empty:
        try:
            example_text = template["example"](df.iloc[0])
        except Exception as exc:  # guard against template bugs
            example_text = f"Could not generate example – {exc}"
    else:
        example_text = "N/A"

    return (
        f"#### This appears to be {template['name']}\n"
        f"{explanation}\n"
        f"#### Example:\n{example_text}"
    )


# Streamlit UI helpers
def section_ui(section_name: str, study_name: str) -> None:
    """
    Render one collapsible section for *section_name* (“Download”, “Tagging”,
    or “Payments”). Handles uploading & browsing config files.
    """
    folder = STUDY_ROOTS[section_name] / study_name
    folder.mkdir(parents=True, exist_ok=True)

    with st.expander(f"# {section_name} configs", expanded=False):
        st.markdown(f"📁 _{folder.relative_to(Path(''))}_")

        # Section 1: Upload
        st.markdown(f"##### Upload a new {section_name} config")
        instructions = {
            "download": (
                "Required files: \n- one for alias mapping\n- one for a list of questions to download responses for\n\n"
                "File names should contain `question` or `alias` respectively but versioning is allowed.\n"
            ),
            "tagging": (
                "Required files: \n"
                "- `workflows.csv`\n- `condition_groups.csv`\n- `conditions.csv`\n"
                "- `condition_questions.csv`\n- `tags.csv`\n\n"
                "File names must be exactly as above.\n"
            ),
            "payments": (
                "Required files: \n- `rates.csv`\n- `schema.csv`\n\n"
                "File names must begin with rates or schemas but versioning is allowed.\n"
            ),
        }
        st.markdown(instructions[section_name.lower()])
        uploaded = st.file_uploader(
            label=f"Upload s new {section_name} config",
            label_visibility='hidden',
            type="csv",
            key=f"uploader_{section_name.lower()}",
            help=(
                f"Select a CSV file to add to this study’s {section_name.lower()} "
                "configuration folder."
            ),
        )
        if uploaded is not None:
            destination = folder / uploaded.name
            if destination.exists():
                st.warning(f"{uploaded.name} already exists – overwriting.")
            try:
                save_uploaded_file(uploaded, destination)
                st.success(f"Saved to {destination}.")
            except Exception as exc:
                st.error(f"Could not save file – {exc}")

        # Section 2: Browse existing
        file_list = sorted(p.name for p in folder.glob("*.csv"))
        if file_list:
            st.markdown(f"##### Select an existing {section_name} config for more info")
            selected_name = st.selectbox(
                label=f"Select an existing {section_name} config for more info",
                label_visibility='hidden',
                options=file_list,
                key=f"select_{section_name.lower()}",
            )
            selected_path = folder / selected_name
            st.markdown(describe_config_file(selected_path))

            # optional preview
            if st.checkbox(
                    "Show first 5 rows",
                    key=f"preview_{section_name.lower()}",
                    value=False,
            ):
                try:
                    preview_df = pd.read_csv(selected_path, nrows=5)
                    st.dataframe(preview_df, use_container_width=True)
                except Exception as exc:
                    st.error(f"Could not preview – {exc}")

            # Section 3: Download
            try:
                file_bytes = selected_path.read_bytes()
                st.download_button(
                    label="📥 Download a copy",
                    data=file_bytes,
                    file_name=selected_name,
                    mime="text/csv",
                    key=f"dl_{section_name.lower()}",
                    help="Save a copy of the selected configuration file "
                         "to your computer.",
                )
            except Exception as exc:
                st.error(f"Could not prepare download – {exc}")
        else:
            st.info("No configuration files in this folder yet.")


def render_page(study_name: str) -> None:
    """The function called from main.py to render the Config-Explorer page given a study."""
    st.title("4. Config Explorer")
    st.markdown(
        "This page is for researchers to upload new configuration files and get more info about existing ones.\n\n"
    )
    st.warning("Be careful when uploading new files – they will overwrite existing ones with the same name.")
    for name in ["Download", "Tagging", "Payments"]:
        section_ui(name, study_name)
