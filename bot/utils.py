from database import get_custom_subjects_list

async def get_all_subjects():
    subjects = set(["english", "russian", "math", "physics"]) 
    custom = await get_custom_subjects_list()
    for s in custom:
        subjects.add(s)
    return sorted(subjects)
