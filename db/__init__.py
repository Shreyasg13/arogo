"""
db/ — Database layer for Arogo.

Each module owns one domain. Import from here for convenience:
    from db import execute, insert_medicine, log_food, ...
"""
from .core        import (execute, executemany, commit, init_db, jdump, jload,
                          now_iso, today_iso, new_id, current_user_id, user_context,
                          to_num, to_int, valid_date)
from .reports     import insert_report, list_reports, get_report, delete_report, report_stats
from .medicines   import (insert_medicine, list_medicines, get_medicine, toggle_medicine, delete_medicine,
                          log_dose, get_today_doses, get_adherence_stats, get_dose_calendar,
                          get_medication_card, get_pill_planner, get_adherence_breakdown,
                          log_medicine_event, get_medicine_events,
                          timing_label, TIMING_LABELS,
                          update_medicine_stock, decrement_pill_count, get_low_stock_medicines,
                          get_refill_list, get_monthly_med_cost,
                          mark_refill_ordered, set_pharmacy_note,
                          snooze_dose, get_due_snoozes, mark_snooze_notified,
                          log_prn_dose)
from .fitness     import (insert_activity, list_activities, delete_activity, fitness_stats,
                          save_token, get_token, list_tokens, delete_token, update_last_sync,
                          log_sync, get_sync_history)
from .food        import (get_profile, update_profile, calc_tdee, get_user_language,
                          log_food, update_food_log, get_food_logs, delete_food_log,
                          get_nutrition_summary, get_weekly_nutrition, get_recomp_signal,
                          usual_portions,
                          save_custom_food, list_custom_foods, get_custom_food_by_barcode)
from .wellness    import (get_thoughts, save_thought, update_thought, delete_thought,
                          get_thoughts_range, count_thoughts_today, MAX_THOUGHTS_PER_DAY,
                          list_todos, create_todo, update_todo, toggle_todo, delete_todo,
                          get_due_reminders, mark_reminder_sent,
                          log_hydration, get_hydration_day, delete_hydration_log, get_hydration_week,
                          log_sleep, get_sleep_logs, delete_sleep_log,
                          log_body_metric, get_body_metrics)
from .health      import (list_habits, create_habit, delete_habit, toggle_habit_log, get_habit_stats,
                          log_symptom, get_symptoms, delete_symptom, get_symptom_med_timeline,
                          log_vital, get_vitals, delete_vital,
                          get_emergency_info, save_emergency_info,
                          create_appointment, list_appointments, delete_appointment,
                          get_next_appointment,
                          add_doctor_question, list_doctor_questions,
                          toggle_doctor_question, delete_doctor_question,
                          add_measurement_reminder, list_measurement_reminders,
                          toggle_measurement_reminder, delete_measurement_reminder)
from .insights    import (add_notification, get_notifications, mark_notification_read,
                          mark_all_notifications_read, unread_notification_count,
                          generate_weekly_report, global_search, get_goal_progress)
from .cycle       import (log_period_start, log_period_end, delete_cycle, get_cycle_summary,
                          log_symptoms, get_symptom_day, get_symptom_summary)

__all__ = [
    "execute", "executemany", "commit", "init_db", "jdump", "jload", "now_iso", "today_iso", "new_id",
    "current_user_id", "user_context", "to_num", "to_int", "valid_date",
    "insert_report", "list_reports", "get_report", "delete_report", "report_stats",
    "insert_medicine", "list_medicines", "get_medicine", "toggle_medicine", "delete_medicine",
    "log_dose", "get_today_doses", "get_adherence_stats", "get_dose_calendar",
    "get_medication_card", "get_pill_planner", "get_adherence_breakdown",
    "log_medicine_event", "get_medicine_events",
    "timing_label", "TIMING_LABELS",
    "update_medicine_stock", "decrement_pill_count", "get_low_stock_medicines", "get_refill_list",
    "get_monthly_med_cost",
    "mark_refill_ordered", "set_pharmacy_note",
    "snooze_dose", "get_due_snoozes", "mark_snooze_notified", "log_prn_dose",
    "insert_activity", "list_activities", "delete_activity", "fitness_stats",
    "save_token", "get_token", "list_tokens", "delete_token", "update_last_sync",
    "log_sync", "get_sync_history",
    "get_profile", "update_profile", "calc_tdee", "get_user_language", "log_food", "update_food_log",
    "get_food_logs", "delete_food_log",
    "usual_portions",
    "get_nutrition_summary", "get_weekly_nutrition", "get_recomp_signal", "save_custom_food", "list_custom_foods",
    "get_custom_food_by_barcode",
    "get_thoughts", "save_thought", "update_thought", "delete_thought",
    "get_thoughts_range", "count_thoughts_today", "MAX_THOUGHTS_PER_DAY",
    "list_todos", "create_todo", "update_todo", "toggle_todo", "delete_todo",
    "get_due_reminders", "mark_reminder_sent",
    "log_hydration", "get_hydration_day", "delete_hydration_log", "get_hydration_week",
    "log_sleep", "get_sleep_logs", "delete_sleep_log",
    "log_body_metric", "get_body_metrics",
    "list_habits", "create_habit", "delete_habit", "toggle_habit_log", "get_habit_stats",
    "log_symptom", "get_symptoms", "delete_symptom", "get_symptom_med_timeline",
    "log_vital", "get_vitals", "delete_vital",
    "get_emergency_info", "save_emergency_info",
    "create_appointment", "list_appointments", "delete_appointment", "get_next_appointment",
    "add_doctor_question", "list_doctor_questions",
    "toggle_doctor_question", "delete_doctor_question",
    "add_measurement_reminder", "list_measurement_reminders",
    "toggle_measurement_reminder", "delete_measurement_reminder",
    "add_notification", "get_notifications", "mark_notification_read",
    "mark_all_notifications_read", "unread_notification_count",
    "generate_weekly_report", "global_search", "get_goal_progress",
    "log_period_start", "log_period_end", "delete_cycle", "get_cycle_summary",
    "log_symptoms", "get_symptom_day", "get_symptom_summary",
]
