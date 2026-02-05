from aiogram.fsm.state import State, StatesGroup

class AddQuestionStates(StatesGroup):
    waiting_for_subject = State()
    waiting_for_question = State()
    waiting_for_options = State()
    waiting_for_correct = State()

class AddProjectStates(StatesGroup):
    waiting_for_subject_key = State()
    waiting_for_command = State()

class AddQuestionsStates(StatesGroup):
    waiting_for_subject = State()
    waiting_for_questions = State()

class DeleteQuestionStates(StatesGroup):
    waiting_for_question_text = State()
    confirm_delete = State()

class DeleteProjectStates(StatesGroup):
    waiting_for_project_name = State()
    confirm_delete = State()

class AdminAuthStates(StatesGroup):
    waiting_for_password = State()
