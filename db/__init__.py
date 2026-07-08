"""
db/ — Database layer for MedEasy Health OS.

Each module owns one domain. Import from here for convenience:
    from db import execute, insert_medicine, log_food, ...
"""
from .core        import (execute, executemany, commit, init_db, jdump, jload,
                          now_iso, today_iso, new_id, current_user_id, user_context)
from .reports     import insert_report, list_reports, get_report, delete_report, report_stats
from .medicines   import (insert_medicine, list_medicines, get_medicine, toggle_medicine, delete_medicine,
                          log_dose, get_today_doses, get_adherence_stats,
                          update_medicine_stock, decrement_pill_count, get_low_stock_medicines)
from .fitness     import (insert_activity, list_activities, delete_activity, fitness_stats,
                          save_token, get_token, list_tokens, delete_token, update_last_sync,
                          log_sync, get_sync_history)
from .food        import (get_profile, update_profile, calc_tdee,
                          log_food, get_food_logs, delete_food_log, get_nutrition_summary, get_weekly_nutrition,
                          save_custom_food, list_custom_foods)
from .wellness    import (get_thoughts, save_thought, update_thought, delete_thought,
                          get_thoughts_range, count_thoughts_today, MAX_THOUGHTS_PER_DAY,
                          list_todos, create_todo, update_todo, toggle_todo, delete_todo,
                          get_due_reminders, mark_reminder_sent,
                          log_hydration, get_hydration_day, delete_hydration_log, get_hydration_week,
                          log_sleep, get_sleep_logs, delete_sleep_log,
                          log_body_metric, get_body_metrics)
from .health      import (list_habits, create_habit, delete_habit, toggle_habit_log, get_habit_stats,
                          log_symptom, get_symptoms, delete_symptom,
                          log_vital, get_vitals, delete_vital,
                          get_emergency_info, save_emergency_info)
from .insights    import (add_notification, get_notifications, mark_notification_read,
                          mark_all_notifications_read, unread_notification_count,
                          generate_weekly_report, global_search, get_goal_progress)

__all__ = [
    "execute", "executemany", "commit", "init_db", "jdump", "jload", "now_iso", "today_iso", "new_id",
    "current_user_id", "user_context",
    "insert_report", "list_reports", "get_report", "delete_report", "report_stats",
    "insert_medicine", "list_medicines", "get_medicine", "toggle_medicine", "delete_medicine",
    "log_dose", "get_today_doses", "get_adherence_stats",
    "update_medicine_stock", "decrement_pill_count", "get_low_stock_medicines",
    "insert_activity", "list_activities", "delete_activity", "fitness_stats",
    "save_token", "get_token", "list_tokens", "delete_token", "update_last_sync",
    "log_sync", "get_sync_history",
    "get_profile", "update_profile", "calc_tdee", "log_food", "get_food_logs", "delete_food_log",
    "get_nutrition_summary", "get_weekly_nutrition", "save_custom_food", "list_custom_foods",
    "get_thoughts", "save_thought", "update_thought", "delete_thought",
    "get_thoughts_range", "count_thoughts_today", "MAX_THOUGHTS_PER_DAY",
    "list_todos", "create_todo", "update_todo", "toggle_todo", "delete_todo",
    "get_due_reminders", "mark_reminder_sent",
    "log_hydration", "get_hydration_day", "delete_hydration_log", "get_hydration_week",
    "log_sleep", "get_sleep_logs", "delete_sleep_log",
    "log_body_metric", "get_body_metrics",
    "list_habits", "create_habit", "delete_habit", "toggle_habit_log", "get_habit_stats",
    "log_symptom", "get_symptoms", "delete_symptom",
    "log_vital", "get_vitals", "delete_vital",
    "get_emergency_info", "save_emergency_info",
    "add_notification", "get_notifications", "mark_notification_read",
    "mark_all_notifications_read", "unread_notification_count",
    "generate_weekly_report", "global_search", "get_goal_progress",
]
