# tagging.py

import os
from typing import List, Any, Tuple

import pandas as pd


def load_study_data(study_name: str, data_root: str = "data") -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load sessions and responses CSVs for a study."""
    base = os.path.join(data_root, study_name)
    sessions = pd.read_csv(os.path.join(base, "sessions.csv"))
    sessions["started_at_utc"] = pd.to_datetime(sessions["started_at_utc"], format="ISO8601", utc=True)
    sessions["ended_at_utc"] = pd.to_datetime(sessions["ended_at_utc"], format="ISO8601", utc=True)
    responses = pd.read_csv(os.path.join(base, "responses.csv"))
    responses["opened_at"] = pd.to_datetime(responses["opened_at"], format="ISO8601", utc=True)
    responses["responded_at"] = pd.to_datetime(responses["responded_at"], format="ISO8601", utc=True)
    return sessions, responses


def load_workflow_definitions(study_name: str, config_root: str = "config/tagging") -> dict:
    """Load workflows, groups, conditions, m2m, and tags as DataFrames."""
    base = os.path.join(config_root, study_name)
    return {
        "workflows": pd.read_csv(os.path.join(base, "workflows.csv"), dtype=str),
        "groups": pd.read_csv(os.path.join(base, "condition_groups.csv"), dtype=str),
        "conditions": pd.read_csv(os.path.join(base, "conditions.csv"), dtype=str),
        "cond_questions": pd.read_csv(os.path.join(base, "condition_questions.csv"), dtype=str),
        "tags": pd.read_csv(os.path.join(base, "tags.csv"), dtype=str),
    }


def str2float(x: Any) -> Any:
    try:
        return float(x)
    except:
        return x


def evaluate_condition_logic(value: Any, operator: str, target: Any) -> bool:
    """
    Given a value, operator, and target, evaluate the condition and return True or False.
    :param value:
    :param operator:
    :param target:
    :return:
    """
    ops = {
        '==': lambda a, b: a == b,
        '!=': lambda a, b: a != b,
        '<': lambda a, b: a < b,
        '<=': lambda a, b: a <= b,
        '>': lambda a, b: a > b,
        '>=': lambda a, b: a >= b,
        'contains': lambda a, b: (b in a) if isinstance(a, str) else False,
        'not_contains': lambda a, b: (b not in a) if isinstance(a, str) else False,
        'empty': lambda a, b: pd.isna(a) or a == '',
        'not_empty': lambda a, b: not (pd.isna(a) or a == ''),
        'between': lambda val, tgt: handle_between(val, tgt),
    }
    func = ops.get(operator)
    if not func:
        return False
    try:
        return func(value, target)
    except:
        return False


def handle_between(value: float, target: str) -> bool:
    """Handle the 'between' operator for numeric values.

    The target is a string that looks like '[1.0,10.0)' or '(0,5]'
    and follows the conventions for inclusive/exclusive bounds.
    """
    lower_inc = target[0] == '['
    upper_inc = target[-1] == ']'
    lo, hi = target[1:-1].split(',')
    lo, hi = float(lo), float(hi)
    if lower_inc:
        ok_lo = value >= lo
    else:
        ok_lo = value > lo
    if upper_inc:
        ok_hi = value <= hi
    else:
        ok_hi = value < hi
    return ok_lo and ok_hi


def eval_single_condition(cond: pd.Series,
                          sess_responses: pd.DataFrame,
                          cond_qs: List[str]) -> bool:
    """
    cond: one row from conditions DF
    sess_responses: responses for this session
    cond_qs: question_name strings that are checked for this condition
    """
    op = cond.operator
    target = cond.value
    # The config specifies whether skipped responses should be treated as true or false
    skip_true = cond.skip_behavior == '1'
    # filter responses to only these questions:
    sub = sess_responses[sess_responses['question_name'].isin(cond_qs)]
    if op == 'empty' and sub.empty:
        return True
    # Return True if any responses to the relevant questions match the condition
    for _, response in sub.iterrows():
        if response.get("skipped", False):
            if skip_true:
                return True
            else:
                continue
        if response.get("not_seen", False):
            continue
        val = response.content
        # try numeric
        val_conv = str2float(val)
        if op != 'between' and isinstance(val_conv, float):
            target = str2float(target)
        if evaluate_condition_logic(val_conv, op, target):
            return True
    return False


def eval_condition_group(group: pd.Series,
                         conditions: pd.DataFrame,
                         cond_questions: pd.DataFrame,
                         sess_responses: pd.DataFrame) -> bool:
    """Evaluate all conditions in a group with AND/OR."""
    grp_id = group.id
    subset = conditions[conditions.group_id == grp_id]
    results = []
    for _, cond in subset.iterrows():
        qs = cond_questions[cond_questions.condition_id == cond.id]['question_name'].tolist()
        results.append(eval_single_condition(cond, sess_responses, qs))
    if group.logical_operator == 'AND':
        return all(results)
    else:
        return any(results)


def eval_workflow(
        workflow_row: pd.Series,
        all_groups: pd.DataFrame,
        all_conditions: pd.DataFrame,
        all_cond_questions: pd.DataFrame,
        session_responses: pd.DataFrame
) -> bool:
    """
    Evaluate one workflow (workflow_row) against the set of responses
    for a single session (session_responses).
    """
    # find all groups belonging to this workflow
    wf_groups = all_groups[all_groups.workflow_id == workflow_row.id]
    if wf_groups.empty:
        return False

    group_results = []
    for _, group_row in wf_groups.iterrows():
        result = eval_condition_group(group_row,
                                      all_conditions,
                                      all_cond_questions,
                                      session_responses)
        group_results.append(result)

    if workflow_row.logical_operator == 'AND':
        return all(group_results)
    else:
        return any(group_results)


def run_tagging(study_name: str, base_dir: str = ".") -> None:
    """
    1) Loads sessions & responses
    2) Loads workflow defs
    3) For each session, for each TAG_SESSION workflow, evaluates that session's responses
    4) Attaches Tag.title to session_tags list
    5) Overwrites sessions.csv with a new column 'session_tags'
    """
    data_root = os.path.join(base_dir, "data")
    config_root = os.path.join(base_dir, "config", "tagging")
    sessions_df, responses_df = load_study_data(study_name, data_root)
    defs = load_workflow_definitions(study_name, config_root)

    workflows_df = defs['workflows'][defs['workflows'].workflow_type == '1']
    groups_df = defs['groups']
    conditions_df = defs['conditions']
    cond_qs_df = defs['cond_questions']
    tags_df = defs['tags'].set_index('id')

    # Prepare a place to accumulate tags
    session_to_tags = {str(sid): [] for sid in sessions_df.session_id.astype(str)}

    # For each session …
    for _, session_row in sessions_df.iterrows():
        sid = str(session_row.session_id)
        # get just this session’s responses
        sess_resps = responses_df[responses_df.session_id == sid]

        # check every TAG_SESSION workflow
        for _, wf_row in workflows_df.iterrows():
            if eval_workflow(wf_row,
                             groups_df,
                             conditions_df,
                             cond_qs_df,
                             sess_resps):
                tag_title = tags_df.loc[wf_row.tag_id, 'title']
                session_to_tags[sid].append(tag_title)

    # write tags back to sessions_df
    sessions_df['session_tags'] = sessions_df.session_id.astype(str).map(
        lambda x: ";".join(session_to_tags[x])
    )

    out_path = os.path.join(data_root, study_name, "tagged_sessions.csv")
    sessions_df.to_csv(out_path, index=False)
