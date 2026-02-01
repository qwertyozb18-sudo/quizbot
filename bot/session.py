# Holds the active quizzes state
# Structure:
# {
#   chat_id: {
#       "active": bool,
#       "session_id": int,
#       "current_question": int,
#       "questions": list,
#       "poll_ids": {poll_id: {"question_num": int, "correct": int}},
#       "seconds": int
#   }
# }
active_quizzes: dict = {}
