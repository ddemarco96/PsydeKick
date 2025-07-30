import json

MW_RESPS = {}
with open("tests/mocks/study_details.json") as f:
    MW_RESPS['study_details'] = json.load(f)

short_names = {
    "621920605978cd435ce7cef5": "NIS", # 22 questions; 6 sessions; 90 responses
    "621920605978cd435ce7cf30": "FU", # 1 question; 2 sessions; 2 responses
    "621920605978cd435ce7cf38": "DSC", # 4 questions; 1 sessions; 4 responses
    "623b7c4dfecd6efa17f39822": "FBR", # 1 question; 0 sessions; 0 responses
    "6219657648ff3b5bb084eb39": "ACT_1" # 1 question; 5 sessions; 5 responses
}
MW_RESPS['surveys'] = {}
for survey in MW_RESPS['study_details']['surveys']:

    new_row = {
        'name': survey['name'],
        'short_name': short_names[survey['id']],
        'id': survey['id'],
    }
    with open(f"tests/mocks/survey_{survey['id']}_details.json") as f:
        new_row['survey_details'] = json.load(f)
    with open(f"tests/mocks/survey_{survey['id']}_sessions.json") as f:
        new_row['sessions'] = json.load(f)
    MW_RESPS['surveys'][short_names[survey['id']]] = new_row
