import tkinter as tk
from tkinter import scrolledtext, messagebox
import json
import random
import re
import requests
import threading
import queue
import webbrowser
import shutil
from pathlib import Path
from datetime import datetime, timedelta

DAY_ROLLOVER_HOUR = 2

# -----------------------------
# FILES / SETTINGS
# -----------------------------
# NEXT PATCH REMINDER: bring over the fixed browser-link reopen logic from autobot_fixed_reopen_links.py.
# Links matter for Start Routine, task buttons, and future work-mode automation.
HISTORY_FILE = Path("momentum_history.json")
QUOTES_FILE = Path("companion_quotes_sample.json")
USER_PROFILE_FILE = Path("user_profile.json")
WORKOUT_HISTORY_FILE = Path("workout_history.json")
BACKUP_DIR = Path("backups")

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"

# Keeps the last few exchanges so follow-up questions feel natural.
CONVERSATION_MEMORY_LIMIT = 10
conversation_history = []

# Voice is intentionally optional. The app should run even before pyttsx3 is installed.
VOICE_ENABLED = False
voice_queue = queue.Queue()
voice_worker_started = False
voice_engine = None
voice_lock = threading.Lock()

# Check Tickets is useful for work, but it should NOT be treated as a growth habit.
GROWTH_TASKS = [
    "Complete Workout",
    "Coding Core Task",
    "Networking / LinkedIn",
    "Spanish Review",
    "Reading",
]

TASK_CATEGORIES = {
    "Complete Workout": "Physical",
    "Coding Core Task": "Career",
    "Networking / LinkedIn": "Career",
    "Spanish Review": "Learning",
    "Reading": "Learning",
}

TIME_RULES = {
    "networking": "10 minutes minimum, 20 minutes maximum. One comment or one connection is enough.",
    "linkedin": "10 minutes minimum, 20 minutes maximum. One comment or one connection is enough.",
    "coding": "10 minutes minimum on low energy, 25 minutes if you feel stable.",
    "spanish": "10 minutes minimum. One short review session is enough to keep the chain alive.",
    "workout": "20 to 30 minutes, unless energy is low. Low energy minimum is 10 minutes of movement.",
    "exercise": "20 to 30 minutes, unless energy is low. Low energy minimum is 10 minutes of movement.",
    "reading": "10 minutes minimum. One chapter, one section, or one useful page counts.",
    "read": "10 minutes minimum. One chapter, one section, or one useful page counts.",
}


# -----------------------------
# LOADERS
# -----------------------------
def load_json_file(path, fallback):
    if not path.exists():
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return fallback


def load_history():
    return load_json_file(HISTORY_FILE, {})


def load_quotes():
    return load_json_file(QUOTES_FILE, [
        "Momentum is not purity. Momentum is recovery.",
        "The list does not care how you feel. It only asks whether you returned.",
        "A small action is still rebellion against decay."
    ])


# -----------------------------
# USER PROFILE
# -----------------------------
DEFAULT_USER_PROFILE = {
    "display_name": "Terrence",
    "current_phase": "Builder Branch v17 Bonus Round",
    "primary_goal": "Build a momentum companion that helps with work, fitness, Spanish, coding, and networking.",
    "tone_preferences": {
        "default": "direct, grounded, encouraging",
        "energetic_when": "checking in and no growth habit is lagging more than one day",
        "urgent_when": "a growth habit has been missed for 2 or more logged opportunities or there are 2+ inactive calendar days",
        "avoid": ["pet names", "generic hype", "overdramatic villain language", "long speeches"]
    },
    "core_growth_tasks": GROWTH_TASKS,
    "voice": {
        "enabled_by_default": False,
        "max_spoken_characters": 650,
        "speak_only_companion": True
    },
    "avatar": {
        "enabled": False,
        "default_animation": "focused_idle"
    }
}


def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


def create_backup_snapshot():
    """Create a simple timestamped backup of the app's local JSON brain files."""
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = BACKUP_DIR / f"backup_{stamp}"
    target_dir.mkdir(exist_ok=True)

    files_to_backup = [
        HISTORY_FILE,
        TODAY_TASKS_FILE if "TODAY_TASKS_FILE" in globals() else Path("today_tasks_state.json"),
        WORKOUT_HISTORY_FILE,
        USER_PROFILE_FILE,
        QUOTES_FILE,
    ]

    copied = []
    missing = []
    for path in files_to_backup:
        try:
            path = Path(path)
            if path.exists():
                shutil.copy2(path, target_dir / path.name)
                copied.append(path.name)
            else:
                missing.append(path.name)
        except Exception as error:
            missing.append(f"{path.name} ({error})")

    manifest = {
        "created_at": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
        "backup_folder": str(target_dir),
        "copied": copied,
        "missing_or_failed": missing,
    }
    save_json_file(target_dir / "backup_manifest.json", manifest)
    return manifest


def format_backup_answer(manifest):
    copied = manifest.get("copied", [])
    missing = manifest.get("missing_or_failed", [])
    lines = [
        "BACKUP CREATED",
        "",
        f"Folder: {manifest.get('backup_folder')}",
        "",
        "Saved:",
    ]
    lines.extend(f"• {name}" for name in copied) if copied else lines.append("• Nothing copied")
    if missing:
        lines.append("")
        lines.append("Missing / skipped:")
        lines.extend(f"• {name}" for name in missing)
    return "\n".join(lines).strip()


def is_backup_request(user_input):
    text = str(user_input or "").lower().strip()
    return any(phrase in text for phrase in [
        "backup", "back up", "export data", "save backup", "create backup", "backup data"
    ])


def backup_now(show_popup=True):
    try:
        manifest = create_backup_snapshot()
        response = format_backup_answer(manifest)
        if show_popup:
            messagebox.showinfo("Backup Created", response)
        return response
    except Exception as error:
        response = f"BACKUP FAILED\n\n{error}"
        if show_popup:
            messagebox.showerror("Backup Failed", response)
        return response


def load_user_profile():
    profile = load_json_file(USER_PROFILE_FILE, None)
    if not isinstance(profile, dict):
        profile = DEFAULT_USER_PROFILE.copy()
        save_json_file(USER_PROFILE_FILE, profile)
        return profile

    # Merge missing top-level keys so old profile files do not break new features.
    changed = False
    for key, value in DEFAULT_USER_PROFILE.items():
        if key not in profile:
            profile[key] = value
            changed = True
    if changed:
        save_json_file(USER_PROFILE_FILE, profile)
    return profile


def get_profile_tone_rules():
    profile = load_user_profile()
    tone = profile.get("tone_preferences", {})
    avoid = tone.get("avoid", [])
    avoid_text = ", ".join(avoid) if avoid else "None listed"
    return (
        f"Default Tone: {tone.get('default', 'direct and grounded')}\n"
        f"Energetic When: {tone.get('energetic_when', 'momentum is stable')}\n"
        f"Urgent When: {tone.get('urgent_when', 'a core habit is slipping')}\n"
        f"Avoid: {avoid_text}"
    )


# -----------------------------
# ANALYSIS
# -----------------------------
def normalize_task_name(text):
    key = str(text).strip().lower()
    aliases = {
        "networking": "Networking / LinkedIn",
        "linkedin": "Networking / LinkedIn",
        "linked in": "Networking / LinkedIn",
        "comment on one post": "Networking / LinkedIn",
        "networking / linkedin": "Networking / LinkedIn",
        "spanish review": "Spanish Review",
        "review spanish notes": "Spanish Review",
        "complete workout": "Complete Workout",
        "workout": "Complete Workout",
        "exercise": "Complete Workout",
        "exercised": "Complete Workout",
        "excercise": "Complete Workout",
        "excercised": "Complete Workout",
        "coding": "Coding Core Task",
        "coding task": "Coding Core Task",
        "coding core task": "Coding Core Task",
        "reading": "Reading",
        "read": "Reading",
        "check tickets": "Check Tickets",
    }
    return aliases.get(key, str(text).strip())


def get_completion_percent(record):
    total = int(record.get("total", 0) or 0)
    completed = int(record.get("completed", 0) or 0)
    return int((completed / total) * 100) if total else 0


def task_done(record, task_name):
    target = normalize_task_name(task_name).lower()
    for task in record.get("tasks", []):
        name = normalize_task_name(task.get("text", "")).lower()
        if name == target and task.get("done"):
            return True
    return False


def get_last_saved_day(history):
    valid = []
    for key in history.keys():
        try:
            datetime.strptime(key, "%Y-%m-%d")
            valid.append(key)
        except Exception:
            pass
    if not valid:
        return None, None
    latest_key = sorted(valid)[-1]
    return latest_key, history.get(latest_key, {})



def get_recent_logged_records(history, limit=7):
    """Return latest real saved sessions only. This ignores inactive calendar placeholders."""
    rows = []
    for key, record in history.items():
        try:
            datetime.strptime(key, "%Y-%m-%d")
        except Exception:
            continue
        if record.get("is_inactive"):
            continue
        rows.append((key, record, get_completion_percent(record)))

    rows.sort(key=lambda row: row[0], reverse=True)
    return rows[:limit]


def get_growth_task_stats(history, limit=7):
    """Calculate habit strength from logged sessions, not inactive calendar gaps."""
    recent_logged = get_recent_logged_records(history, limit=limit)

    stats = {
        task: {"done": 0, "missed": 0, "expected": 0, "rate": 0}
        for task in GROWTH_TASKS
    }

    for _, record, _ in recent_logged:
        task_names_in_record = {
            normalize_task_name(task.get("text", "")).lower()
            for task in record.get("tasks", [])
        }
        missed_names_in_record = {
            normalize_task_name(task).lower()
            for task in record.get("missed_tasks", [])
        }

        for task_name in GROWTH_TASKS:
            target = task_name.lower()

            # Count a task as expected only when the saved record actually mentions it.
            # This avoids punishing early prototype days that did not include every core task yet.
            was_expected = target in task_names_in_record or target in missed_names_in_record
            if not was_expected:
                continue

            stats[task_name]["expected"] += 1
            if task_done(record, task_name):
                stats[task_name]["done"] += 1
            else:
                stats[task_name]["missed"] += 1

    for task_name, row in stats.items():
        expected = row["expected"]
        row["rate"] = int((row["done"] / expected) * 100) if expected else 0

    usable = {task: row for task, row in stats.items() if row["expected"] > 0}

    if not usable:
        return stats, "Unknown", "Unknown"

    strongest = max(
        usable.items(),
        key=lambda item: (item[1]["rate"], item[1]["done"], -item[1]["missed"])
    )[0]

    weakest = min(
        usable.items(),
        key=lambda item: (item[1]["rate"], -item[1]["missed"], item[1]["done"])
    )[0]

    # If a tiny dataset still creates a tie, keep the strongest and pick the weakest by misses.
    if strongest == weakest and len(usable) > 1:
        weakest = max(
            {task: row for task, row in usable.items() if task != strongest}.items(),
            key=lambda item: (item[1]["missed"], -item[1]["rate"])
        )[0]

    return stats, strongest, weakest


def get_category_stats(growth_stats):
    """Roll growth task stats into category stats for the brain summary."""
    category_stats = {}
    for task_name, row in (growth_stats or {}).items():
        category = TASK_CATEGORIES.get(task_name)
        if not category:
            continue
        if category not in category_stats:
            category_stats[category] = {"done": 0, "expected": 0, "missed": 0, "rate": 0}
        category_stats[category]["done"] += int(row.get("done", 0) or 0)
        category_stats[category]["expected"] += int(row.get("expected", 0) or 0)
        category_stats[category]["missed"] += int(row.get("missed", 0) or 0)

    for category, row in category_stats.items():
        expected = row["expected"]
        row["rate"] = int((row["done"] / expected) * 100) if expected else 0

    return category_stats


def get_strongest_weakest_category(category_stats):
    usable = {category: row for category, row in (category_stats or {}).items() if row.get("expected", 0) > 0}
    if not usable:
        return "Unknown", "Unknown"

    strongest = max(usable.items(), key=lambda item: (item[1]["rate"], item[1]["done"], -item[1]["missed"]))[0]
    weakest = min(usable.items(), key=lambda item: (item[1]["rate"], -item[1]["missed"], item[1]["done"]))[0]

    if strongest == weakest and len(usable) > 1:
        weakest = max(
            {category: row for category, row in usable.items() if category != strongest}.items(),
            key=lambda item: (item[1]["missed"], -item[1]["rate"])
        )[0]

    return strongest, weakest


def build_timeline(history):
    if not history:
        return []

    dates = []
    for key in history.keys():
        try:
            dates.append(datetime.strptime(key, "%Y-%m-%d").date())
        except Exception:
            pass

    if not dates:
        return []

    start = min(dates)
    end = max(max(dates), get_momentum_now().date())
    timeline = []

    current = start
    while current <= end:
        key = current.strftime("%Y-%m-%d")
        if key in history:
            record = dict(history[key])
            record["is_inactive"] = False
        else:
            record = {
                "date": key,
                "is_inactive": True,
                "completed": 0,
                "total": 5,
                "finished_all": False,
                "missed_tasks": [],
                "tasks": [],
                "xp_earned": 0,
                "energy": "Inactive",
                "location": "Unknown",
            }
        timeline.append((key, record, get_completion_percent(record)))
        current += timedelta(days=1)

    return timeline


def classify_day(record):
    if record.get("is_inactive"):
        return "Inactive Day"

    completed = int(record.get("completed", 0) or 0)
    total = int(record.get("total", 0) or 0)
    percent = get_completion_percent(record)

    if total > 0 and completed == 0:
        return "Missed Day"
    if record.get("finished_all"):
        return "Clean Finish"
    if percent >= 75:
        return "Strong"
    if percent >= 50:
        return "Stable"
    if percent > 0:
        return "Recovery Day"
    return "Missed Day"


def get_direct_rule(user_input):
    text = user_input.lower()

    asks_time = any(phrase in text for phrase in [
        "how long", "how many minutes", "how much time", "time should", "stay on"
    ])

    if not asks_time:
        return ""

    for keyword, rule in TIME_RULES.items():
        if keyword in text:
            return f"Direct answer: {rule}"

    return "Direct answer: 10 minutes minimum. Stop after 20 minutes unless you are clearly building momentum."


def analyze_history():
    history = load_history()
    timeline = build_timeline(history)

    if not timeline:
        return {
            "current_state": "No Data Yet",
            "last_logged_day": "None",
            "last_result": "No saved momentum history found.",
            "strongest_habit": "Unknown",
            "weakest_habit": "Unknown",
            "growth_task_stats": {},
            "category_stats": {},
            "strongest_category": "Unknown",
            "weakest_category": "Unknown",
            "inactive_days_recent": 0,
            "missed_days_recent": 0,
            "recovery_days_recent": 0,
            "average_recent_completion": 0,
            "logged_session_average": 0,
            "recommended_move": "Start the app and complete one core growth task.",
            "reason": "No history exists yet.",
        }

    latest_key, latest_record = get_last_saved_day(history)
    latest_state = classify_day(latest_record)
    latest_percent = get_completion_percent(latest_record)

    # Calendar recent shows whether you have been away from the bot.
    recent_calendar = timeline[-7:]

    inactive_days = 0
    missed_days = 0
    recovery_days = 0

    for key, record, percent in recent_calendar:
        state = classify_day(record)

        if state == "Inactive Day":
            inactive_days += 1
        elif state == "Missed Day":
            missed_days += 1
        elif state == "Recovery Day":
            recovery_days += 1

    calendar_avg_percent = int(sum(percent for _, _, percent in recent_calendar) / len(recent_calendar)) if recent_calendar else 0

    # Habit strength should come from real saved sessions, not inactive placeholder days.
    recent_logged = get_recent_logged_records(history, limit=7)
    logged_avg_percent = int(sum(percent for _, _, percent in recent_logged) / len(recent_logged)) if recent_logged else 0
    growth_stats, strongest_habit, weakest_habit = get_growth_task_stats(history, limit=7)

    category_stats = get_category_stats(growth_stats)
    strongest_category, weakest_category = get_strongest_weakest_category(category_stats)

    if inactive_days >= 3:
        current_state = "Rebuild Mode"
    elif calendar_avg_percent >= 80:
        current_state = "Momentum Rising"
    elif calendar_avg_percent >= 50:
        current_state = "Momentum Stable"
    elif calendar_avg_percent > 0:
        current_state = "Recovery Mode"
    else:
        current_state = "Danger Zone"

    if inactive_days >= 2:
        recommended_move = "Open the main bot and complete one growth task to break the inactive chain."
        reason = f"{inactive_days} inactive day(s) detected recently."
    elif weakest_habit == "Networking / LinkedIn":
        recommended_move = "Do 10 minutes of LinkedIn: one comment or one connection."
        reason = "Networking is currently the weakest growth task across logged sessions."
    elif weakest_habit == "Coding Core Task":
        recommended_move = "Open the coding file and work for 10 minutes only."
        reason = "Coding is currently the weakest growth task across logged sessions."
    elif weakest_habit == "Spanish Review":
        recommended_move = "Do 10 minutes of Spanish review before entertainment."
        reason = "Spanish is currently the weakest growth task across logged sessions."
    elif weakest_habit == "Complete Workout":
        recommended_move = "Do one short workout block or light movement session."
        reason = "Physical momentum is currently slipping across logged sessions."
    else:
        recommended_move = "Complete one growth task first."
        reason = "The system needs more logged task data to rank habits cleanly."

    return {
        "current_state": current_state,
        "last_logged_day": latest_key,
        "last_result": f"{latest_state}: {latest_record.get('completed', 0)}/{latest_record.get('total', 0)} core tasks completed ({latest_percent}%).",
        "strongest_habit": strongest_habit,
        "weakest_habit": weakest_habit,
        "growth_task_stats": growth_stats,
        "category_stats": category_stats,
        "strongest_category": strongest_category,
        "weakest_category": weakest_category,
        "inactive_days_recent": inactive_days,
        "missed_days_recent": missed_days,
        "recovery_days_recent": recovery_days,
        "average_recent_completion": calendar_avg_percent,
        "logged_session_average": logged_avg_percent,
        "recommended_move": recommended_move,
        "reason": reason,
    }


def build_companion_state():
    """Convert momentum stats into voice/avatar-ready emotional state."""
    brain = analyze_history()
    stats = brain.get("growth_task_stats", {}) or {}

    max_missed = 0
    weakest_task = brain.get("weakest_habit", "Unknown")
    for task_name, row in stats.items():
        if int(row.get("missed", 0) or 0) > max_missed:
            max_missed = int(row.get("missed", 0) or 0)
            weakest_task = task_name

    inactive_days = int(brain.get("inactive_days_recent", 0) or 0)
    missed_days = int(brain.get("missed_days_recent", 0) or 0)
    logged_average = int(brain.get("logged_session_average", 0) or 0)

    if inactive_days >= 2 or max_missed >= 2 or missed_days >= 2:
        return {
            "mode": "Urgent Recovery",
            "mood": "serious",
            "urgency": "high",
            "animation": "alert_idle",
            "voice_style": "urgent_direct",
            "focus_task": weakest_task,
            "reason": "A growth habit or check-in pattern is lagging by 2+ opportunities."
        }

    if logged_average >= 70 and inactive_days == 0 and max_missed <= 1:
        return {
            "mode": "Momentum Push",
            "mood": "energetic",
            "urgency": "medium",
            "animation": "confident_idle",
            "voice_style": "energetic_direct",
            "focus_task": weakest_task,
            "reason": "You are checking in and no major growth habit is badly lagging."
        }

    return {
        "mode": "Steady Build",
        "mood": "calm",
        "urgency": "medium",
        "animation": "focused_idle",
        "voice_style": "calm_direct",
        "focus_task": weakest_task,
        "reason": "The system sees some movement, but not enough consistency for a hard push."
    }


def format_companion_state(state):
    return (
        f"Mode: {state.get('mode')}\n"
        f"Mood: {state.get('mood')}\n"
        f"Urgency: {state.get('urgency')}\n"
        f"Animation: {state.get('animation')}\n"
        f"Voice Style: {state.get('voice_style')}\n"
        f"Focus Task: {state.get('focus_task')}\n"
        f"Reason: {state.get('reason')}"
    )


def build_brain_summary(user_input=""):
    brain = analyze_history()
    companion_state = build_companion_state()
    profile_tone_rules = get_profile_tone_rules()
    direct_rule = get_direct_rule(user_input)

    direct_rule_text = f"- Direct Rule For This Question: {direct_rule}" if direct_rule else "- Direct Rule For This Question: None"

    return f"""
CURRENT MOMENTUM DATA:
- Current State: {brain.get("current_state")}
- Last Logged Day: {brain.get("last_logged_day")}
- Last Result: {brain.get("last_result")}
- Strongest Growth Habit: {brain.get("strongest_habit")}
- Weakest Growth Habit: {brain.get("weakest_habit")}
- Strongest Category: {brain.get("strongest_category")}
- Weakest Category: {brain.get("weakest_category")}
- Recent Inactive Days: {brain.get("inactive_days_recent")}
- Recent Missed Days: {brain.get("missed_days_recent")}
- Recent Recovery Days: {brain.get("recovery_days_recent")}
- Recent Average Completion: {brain.get("average_recent_completion", 0)}%
- Recommended Move: {brain.get("recommended_move")}
- Reason: {brain.get("reason")}
{direct_rule_text}

USER PROFILE TONE RULES:
{profile_tone_rules}

COMPANION STATE FOR VOICE / AVATAR:
{format_companion_state(companion_state)}

IMPORTANT ANALYSIS RULES:
- Never treat "Check Tickets" as strongest habit, weakest habit, or a growth focus.
- Growth habits are Workout, Coding, Networking/LinkedIn, Spanish, and Reading.
- If the user asks a direct question, answer it directly in the first sentence.
- If the user asks "how long", give an exact time range first.
- Then give brief coaching after the answer.

PERSONA / RESPONSE STYLE:
You are a supportive assistant and trainer built on top of this user's momentum app.
Tone: direct, grounded, encouraging, and lightly playful only when it fits.
No greetings. Do not start with "Hi", "Hey", "Hello", or "Hi there".
No pet names. Never use "my dear", "sweetie", "honey", "champ", or "buddy".
No generic hype. Tie coaching to the user's actual momentum data when useful.
Keep coaching responses compressed: ideal 3 sentences, maximum 4 sentences.
Give exactly one practical next action.
Do not list multiple choices unless the user asks for options.
Avoid overdramatic villain language.

RESPONSE FORMAT FOR COACHING:
Sentence 1: Acknowledge the user's state directly.
Sentence 2: Mention the relevant momentum data or constraint.
Sentence 3: Give one clear next action.
Optional sentence 4: Brief encouragement only if needed.
""".strip()


# -----------------------------
# CONVERSATION MEMORY
# -----------------------------
def add_to_conversation_history(sender, message):
    """Store recent chat context so the model can answer follow-up questions."""
    global conversation_history

    cleaned = str(message).strip()
    if not cleaned:
        return

    conversation_history.append(f"{sender}: {cleaned}")

    # Keep only the most recent lines so the prompt does not get too large.
    max_lines = CONVERSATION_MEMORY_LIMIT * 2
    conversation_history = conversation_history[-max_lines:]


def get_recent_conversation_text():
    if not conversation_history:
        return "No prior conversation in this session yet."
    return "\n".join(conversation_history)




# -----------------------------
# SMART ANSWER ROUTING
# -----------------------------
def get_latest_logged_record():
    """Return the latest saved momentum record from the history file."""
    history = load_history()
    latest_key, latest_record = get_last_saved_day(history)
    return latest_key, latest_record or {}


def get_latest_task_lists():
    """Build accurate completed/remaining task lists from the latest saved day."""
    latest_key, record = get_latest_logged_record()
    tasks = record.get("tasks", []) if record else []

    completed = []
    remaining = []
    seen = set()

    for task in tasks:
        name = normalize_task_name(task.get("text", "")).strip()
        if not name or name.lower() in seen:
            continue

        # Prefer the first version of a task if duplicates exist.
        # This keeps bonus duplicates from making the answer messy.
        seen.add(name.lower())

        if task.get("done"):
            completed.append(name)
        else:
            remaining.append(name)

    return latest_key, record, completed, remaining


def format_task_status_answer():
    """Pure data answer. No AI. No coaching. No hallucination."""
    latest_key, record, completed, remaining = get_latest_task_lists()

    if not latest_key:
        return "TASK STATUS\n\nNo momentum history found yet."

    completed_count = int(record.get("completed", len(completed)) or 0)
    total_count = int(record.get("total", completed_count + len(remaining)) or 0)
    percent = get_completion_percent(record)

    completed_text = "\n".join(f"✓ {task}" for task in completed) if completed else "None yet."
    remaining_text = "\n".join(f"□ {task}" for task in remaining) if remaining else "None. Clean finish."

    return f"""TASK STATUS — LAST LOGGED DAY: {latest_key}

Completed: {completed_count}/{total_count} ({percent}%)

COMPLETED
{completed_text}

REMAINING
{remaining_text}""".strip()


def format_rule_answer(user_input):
    """Pure rule answer for time questions. No AI needed."""
    text = user_input.lower()

    rule_cards = {
        "linkedin": (
            "LINKEDIN RULE",
            "10–20 minutes.",
            "Success condition: 1 comment OR 1 connection."
        ),
        "linked in": (
            "LINKEDIN RULE",
            "10–20 minutes.",
            "Success condition: 1 comment OR 1 connection."
        ),
        "networking": (
            "NETWORKING RULE",
            "10–20 minutes.",
            "Success condition: 1 comment OR 1 connection."
        ),
        "coding": (
            "CODING RULE",
            "10 minutes minimum on low energy. 25 minutes if stable.",
            "Success condition: open the project and make one small improvement."
        ),
        "spanish": (
            "SPANISH RULE",
            "10 minutes minimum.",
            "Success condition: one short review session."
        ),
        "workout": (
            "WORKOUT RULE",
            "20–30 minutes normally. 10 minutes minimum on low energy.",
            "Success condition: movement counts; perfection does not."
        ),
        "exercise": (
            "EXERCISE RULE",
            "20–30 minutes normally. 10 minutes minimum on low energy.",
            "Success condition: movement counts; perfection does not."
        ),
        "reading": (
            "READING RULE",
            "10 minutes minimum.",
            "Success condition: one useful section, chapter, or page."
        ),
        "read": (
            "READING RULE",
            "10 minutes minimum.",
            "Success condition: one useful section, chapter, or page."
        ),
    }

    for keyword, (title, time_rule, success) in rule_cards.items():
        if keyword in text:
            return f"""{title}

Time: {time_rule}

{success}""".strip()

    return """GENERAL TIME RULE

Time: 10 minutes minimum. Stop at 20 minutes unless momentum is clearly building.

Success condition: start the task, complete one small loop, then stop clean.""".strip()


def format_analysis_answer():
    """Structured analysis answer from Python-generated momentum stats.

    Keep this clean. Categories are still calculated in the background,
    but the chat should only show the most useful habit-level summary.
    """
    brain = analyze_history()
    companion_state = build_companion_state()

    return f"""MOMENTUM ANALYSIS

Current State: {brain.get('current_state')}
Recent Calendar Average: {brain.get('average_recent_completion')}%
Logged Session Average: {brain.get('logged_session_average')}%

Strongest Habit: {brain.get('strongest_habit')}
Weakest Habit: {brain.get('weakest_habit')}
Strongest Category: {brain.get('strongest_category')}
Weakest Category: {brain.get('weakest_category')}

Companion Mode: {companion_state.get('mode')}
Mood: {companion_state.get('mood')}
Urgency: {companion_state.get('urgency')}
Voice Style: {companion_state.get('voice_style')}
Animation: {companion_state.get('animation')}

Recommended Move:
{brain.get('recommended_move')}

Reason:
{brain.get('reason')}""".strip()


def route_user_message(user_input):
    """Decide whether the answer should come from Python or Ollama."""
    text = user_input.lower().strip()

    if is_alert_request(text):
        return "alerts"

    asks_time = any(phrase in text for phrase in [
        "how long", "how many minutes", "how much time", "time should", "stay on"
    ])

    asks_task_status = any(phrase in text for phrase in [
        "what tasks", "tasks have i", "already completed", "have i completed",
        "what did i complete", "what have i done", "what did i do",
        "what's left", "whats left", "remaining", "what is left", "completed so far"
    ])

    asks_analysis = any(phrase in text for phrase in [
        "weakest", "strongest", "pattern", "patterns", "momentum", "current state",
        "what should i do next", "what should i focus", "recommended move",
        "where am i slipping", "what am i missing"
    ])

    if asks_time:
        return "rule"
    if asks_task_status:
        return "data"
    if asks_analysis:
        return "analysis"

    return "coaching"


def get_routed_response(user_input):
    """Return a direct Python answer when possible; otherwise return None for Ollama."""
    mode = route_user_message(user_input)

    if mode == "alerts":
        return format_trend_alerts_answer()
    if mode == "rule":
        return format_rule_answer(user_input)
    if mode == "data":
        return format_task_status_answer()
    if mode == "analysis":
        return format_analysis_answer()

    return None


# -----------------------------
# AI CALL
# -----------------------------

def compress_companion_response(text, max_sentences=4):
    """Final cleanup pass for Ollama coaching responses.

    The router already handles data/rule questions. This keeps AI coaching short,
    removes greetings/pet names, and prevents the companion from rambling.
    """
    text = str(text or "").strip()
    if not text:
        return text

    # Remove common chatbot greetings at the beginning.
    text = re.sub(r"^(hi|hello|hey|hi there|hello there)[,!\.\s]+", "", text, flags=re.IGNORECASE)

    # Remove pet names anywhere they sneak in.
    banned_phrases = ["my dear", "sweetie", "honey", "champ", "buddy"]
    for phrase in banned_phrases:
        text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)

    # Remove filler encouragement that tends to make responses feel generic.
    filler_patterns = [
        r"\bRemember,\s*small steps can lead to significant progress\.?",
        r"\bLet's get through this together!?",
        r"\bYou got this!?",
        r"\bKeep up the good work!?",
    ]
    for pattern in filler_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text).strip()

    # Split into sentences and keep only the first few.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    text = " ".join(sentences[:max_sentences])

    # Restore readable paragraph breaks for the chat box.
    text = re.sub(r"(?<=[.!?])\s+(?=[A-Z])", "\n", text)
    return text.strip()

def chat_with_ollama(user_input):
    brain_summary = build_brain_summary(user_input)
    recent_conversation = get_recent_conversation_text()

    prompt = f"""
{brain_summary}

RECENT CONVERSATION THIS SESSION:
{recent_conversation}

CURRENT USER MESSAGE:
{user_input}

COMPANION RESPONSE:
""".strip()

    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=25
        )
        response.raise_for_status()
        raw_response = response.json().get("response", "[No response received]").strip()
        return compress_companion_response(raw_response)
    except requests.exceptions.RequestException:
        return (
            "[ERROR: Could not connect to Ollama.]\\n\\n"
            "Checklist:\\n"
            "1. Make sure Ollama is running.\\n"
            "2. Try: ollama serve\\n"
            "3. Try: ollama pull mistral"
        )
    except Exception as error:
        return f"[ERROR: Unexpected issue: {error}]"



# -----------------------------
# INSIGHTS TAB / PHASE 2A
# -----------------------------


# -----------------------------
# MORNING BRIEFING / PHASE 2A.5
# -----------------------------
def get_task_rule_brief(task_name):
    """Return a short action rule for the priority task."""
    task = normalize_task_name(task_name)

    if task == "Networking / LinkedIn":
        return "10–20 minutes. One comment OR one connection."
    if task == "Coding Core Task":
        return "10 minutes minimum if low energy. 25 minutes if stable. Make one small improvement."
    if task == "Spanish Review":
        return "10 minutes minimum. One short review session keeps the chain alive."
    if task == "Complete Workout":
        return "20–30 minutes normally. 10 minutes minimum if low energy. Movement counts."

    return "10 minutes minimum. Complete one small loop and stop clean."


def get_priority_move(task_name):
    """Return one concrete move for the priority focus."""
    task = normalize_task_name(task_name)

    if task == "Networking / LinkedIn":
        return "Complete one LinkedIn action: one comment OR one connection."
    if task == "Coding Core Task":
        return "Open the coding project and improve one small thing for 10 minutes."
    if task == "Spanish Review":
        return "Complete one 10-minute Spanish review session."
    if task == "Complete Workout":
        return "Complete one short movement block; 10 minutes counts if energy is low."

    return "Complete one small growth task and close the loop."


def get_habit_metric_data(task_name, brain):
    """Return exact done/expected/rate/missed data for a habit."""
    task = normalize_task_name(task_name)
    stats = brain.get("growth_task_stats", {}) or {}
    row = stats.get(task, {})
    expected = int(row.get("expected", 0) or 0)
    done = int(row.get("done", 0) or 0)
    missed = int(row.get("missed", max(expected - done, 0)) or 0)
    rate = int(row.get("rate", 0) or 0)

    return {
        "task": task,
        "done": done,
        "expected": expected,
        "missed": missed,
        "rate": rate,
    }


def format_priority_performance(metric):
    """Readable performance line for the morning briefing."""
    if metric["task"] == "Unknown" or metric["expected"] == 0:
        return "Not enough logged data yet."
    return f"{metric['rate']}% ({metric['done']} of {metric['expected']} logged opportunities)"


def format_priority_gap(metric):
    """Readable gap line for the morning briefing."""
    if metric["task"] == "Unknown" or metric["expected"] == 0:
        return "No measurable gap yet."
    if metric["missed"] == 0:
        return "No missed logged opportunities. Maintain this."
    return f"Missed {metric['missed']} logged opportunity" + ("." if metric["missed"] == 1 else "ies.")


def build_morning_briefing_packet():
    """Create the focused metrics packet used by the Morning Briefing.

    Phase 2A.6 intentionally removes State and Strongest Habit from the briefing.
    Morning Briefing is Action Mode: what slipped, by how much, and what fixes it.
    """
    brain = analyze_history()
    history = load_history()
    latest_key, latest_record = get_last_saved_day(history)

    latest_completed = int(latest_record.get("completed", 0) or 0) if latest_record else 0
    latest_total = int(latest_record.get("total", 0) or 0) if latest_record else 0
    latest_percent = get_completion_percent(latest_record) if latest_record else 0

    weakest = brain.get("weakest_habit", "Unknown")
    priority = weakest if weakest != "Unknown" else "one growth task"
    priority_metric = get_habit_metric_data(priority, brain)

    observation = build_priority_observation(priority_metric, brain)

    return {
        # Kept internally for Ollama context, but not printed as a mode label in the briefing.
        "state": brain.get("current_state", "Unknown"),
        "last_logged_day": latest_key or "None",
        "last_session": f"{latest_completed}/{latest_total} tasks completed ({latest_percent}%)" if latest_key else "No saved session yet.",
        "calendar_average": int(brain.get("average_recent_completion", 0) or 0),
        "logged_session_average": int(brain.get("logged_session_average", 0) or 0),
        "inactive_days": int(brain.get("inactive_days_recent", 0) or 0),
        "priority": priority,
        "priority_metric": priority_metric,
        "priority_performance": format_priority_performance(priority_metric),
        "priority_gap": format_priority_gap(priority_metric),
        "rule": get_task_rule_brief(priority),
        "recommended_move": get_priority_move(priority),
        "reason": brain.get("reason", "No reason available yet."),
        "observation": observation,
    }


def build_priority_observation(metric, brain):
    """Problem-focused observation for the briefing."""
    task = metric.get("task", "Unknown")
    expected = metric.get("expected", 0)
    missed = metric.get("missed", 0)
    rate = metric.get("rate", 0)
    inactive = int(brain.get("inactive_days_recent", 0) or 0)
    logged_avg = int(brain.get("logged_session_average", 0) or 0)

    if task == "Unknown" or expected == 0:
        if inactive:
            return f"The biggest issue right now is absence from the system: {inactive} inactive calendar day(s) recently."
        return "The system needs more logged sessions before it can identify the biggest gap."

    if missed > 0:
        return f"{task} has the largest gap right now: {missed} missed logged opportunit{'y' if missed == 1 else 'ies'} at {rate}%."

    if logged_avg >= 80:
        return "No major gap is showing in logged sessions. Today is about maintaining pressure without overcomplicating the list."

    return f"{task} is the priority because it has the lowest logged-session rate at {rate}%."


def format_morning_briefing(packet, companion_note=""):
    """Build a focused command-center style briefing."""
    note = companion_note.strip()
    if not note:
        note = "You do not need a perfect day. You need one completed loop."

    return f"""MORNING BRIEFING

LAST SESSION
{packet['last_logged_day']} — {packet['last_session']}

RECENT METRICS
Calendar Average: {packet['calendar_average']}%
Logged Session Average: {packet['logged_session_average']}%
Inactive Days: {packet['inactive_days']}

PRIORITY FOCUS
{packet['priority']}

Performance:
{packet['priority_performance']}

Gap:
{packet['priority_gap']}

RULE
{packet['rule']}

OBSERVATION
{packet['observation']}

TODAY'S MOVE
{packet['recommended_move']}

COMPANION NOTE
{note}""".strip()


def get_morning_companion_note(packet, quote):
    """Let Ollama add personality, but only as a small closing note."""
    metric = packet.get("priority_metric", {})
    prompt = f"""
You are the user's Momentum Companion.
Write ONLY a short closing note for a morning briefing.
Do not repeat the full briefing.
No greeting. No pet names. No long speech.
Maximum 2 short sentences.
Tone: direct, grounded, encouraging, lightly playful if natural.
Focus on the priority gap and one completed loop.

Opening thought available if useful: {quote}

Metrics:
Last Session: {packet['last_session']}
Calendar Average: {packet['calendar_average']}%
Logged Session Average: {packet['logged_session_average']}%
Inactive Days: {packet['inactive_days']}
Priority Focus: {packet['priority']}
Performance: {packet['priority_performance']}
Gap: {packet['priority_gap']}
Missed Count: {metric.get('missed', 0)}
Rule: {packet['rule']}
Today Move: {packet['recommended_move']}
Observation: {packet['observation']}

Closing note:
""".strip()

    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=18
        )
        response.raise_for_status()
        raw_response = response.json().get("response", "").strip()
        return compress_companion_response(raw_response, max_sentences=2)
    except Exception:
        metric = packet.get("priority_metric", {})
        missed = int(metric.get("missed", 0) or 0)
        priority = packet.get("priority", "this task")
        if missed:
            return f"You missed {missed} {priority} opportunit{'y' if missed == 1 else 'ies'} recently. One completed loop today starts closing that gap."
        return "No perfect day required. One completed loop is enough to keep the system moving."


def build_generated_observations():
    """Create plain-English observations from real momentum stats."""
    brain = analyze_history()
    stats = brain.get("growth_task_stats", {}) or {}

    strongest = brain.get("strongest_habit", "Unknown")
    weakest = brain.get("weakest_habit", "Unknown")
    inactive = int(brain.get("inactive_days_recent", 0) or 0)
    calendar_avg = int(brain.get("average_recent_completion", 0) or 0)
    logged_avg = int(brain.get("logged_session_average", 0) or 0)
    state = brain.get("current_state", "Unknown")

    observations = []

    if strongest != "Unknown":
        row = stats.get(strongest, {})
        observations.append(
            f"{strongest} is your strongest logged growth habit "
            f"({row.get('done', 0)}/{row.get('expected', 0)} logged opportunities, {row.get('rate', 0)}%)."
        )

    if weakest != "Unknown":
        row = stats.get(weakest, {})
        observations.append(
            f"{weakest} needs the most attention "
            f"({row.get('done', 0)}/{row.get('expected', 0)} logged opportunities, {row.get('rate', 0)}%)."
        )

    if inactive >= 3:
        observations.append(
            f"You have {inactive} inactive calendar day(s) recently, so the current priority is restarting the chain."
        )
    elif inactive > 0:
        observations.append(
            f"You have {inactive} inactive calendar day(s) recently, but the chain is still recoverable with one small action."
        )

    if calendar_avg == 0 and logged_avg > 0:
        observations.append(
            f"Your recent calendar average is 0% because the bot has not been logged recently; your saved-session average is {logged_avg}%."
        )
    elif calendar_avg < logged_avg:
        observations.append(
            f"Logged sessions are stronger than the calendar view, which means absence from the bot is hurting the score more than bad sessions."
        )

    if state == "Rebuild Mode":
        observations.append("The system is reading this as Rebuild Mode: one clean growth task matters more than a huge day.")
    elif state == "Momentum Rising":
        observations.append("Momentum is rising. Protect the anchor habit and add one career rep.")
    elif state == "Momentum Stable":
        observations.append("Momentum is stable. The next win comes from tightening the weakest habit.")
    elif state == "Danger Zone":
        observations.append("Momentum is in Danger Zone. Shrink the list and complete one core action today.")

    if not observations:
        observations.append("Keep logging sessions. The system needs more completed days to generate stronger observations.")

    return observations


def show_insights_window():
    brain = analyze_history()
    observations = build_generated_observations()
    stats = brain.get("growth_task_stats", {}) or {}

    window = tk.Toplevel(root)
    window.title("Momentum Insights - Phase 2A")
    window.geometry("1000x700")
    window.configure(bg="#111111")
    window.transient(root)

    tk.Label(
        window,
        text="Momentum Insights",
        font=("Segoe UI", 22, "bold"),
        bg="#111111",
        fg="#f2f2f2"
    ).pack(anchor="w", padx=18, pady=(18, 4))

    tk.Label(
        window,
        text="Phase 2A: pattern readout generated from your real saved momentum sessions.",
        font=("Segoe UI", 10),
        bg="#111111",
        fg="#aaaaaa"
    ).pack(anchor="w", padx=18, pady=(0, 12))

    summary = tk.Frame(window, bg="#191919", relief="solid", bd=1)
    summary.pack(fill="x", padx=18, pady=(0, 14))

    rows = [
        ("Current State", brain.get("current_state")),
        ("Last Logged Day", brain.get("last_logged_day")),
        ("Last Result", brain.get("last_result")),
        ("Calendar Average", f"{brain.get('average_recent_completion')}% — last 7 calendar days"),
        ("Logged Session Average", f"{brain.get('logged_session_average')}% — latest saved sessions"),
        ("Strongest Habit", brain.get("strongest_habit")),
        ("Weakest Habit", brain.get("weakest_habit")),
        ("Inactive Days", brain.get("inactive_days_recent")),
        ("Recommended Move", brain.get("recommended_move")),
        ("Reason", brain.get("reason")),
    ]

    for i, (label, value) in enumerate(rows):
        tk.Label(summary, text=label, font=("Segoe UI", 10, "bold"), bg="#191919", fg="#8bd3ff", width=24, anchor="w").grid(row=i, column=0, sticky="w", padx=14, pady=6)
        tk.Label(summary, text=str(value), font=("Segoe UI", 10), bg="#191919", fg="#f2f2f2", anchor="w", wraplength=700, justify="left").grid(row=i, column=1, sticky="w", padx=10, pady=6)

    body = tk.Frame(window, bg="#111111")
    body.pack(fill="both", expand=True, padx=18, pady=(0, 12))
    body.columnconfigure(0, weight=2)
    body.columnconfigure(1, weight=1)
    body.rowconfigure(1, weight=1)

    tk.Label(body, text="Generated Observations", font=("Segoe UI", 12, "bold"), bg="#111111", fg="#f2f2f2").grid(row=0, column=0, sticky="w", pady=(0, 8))
    tk.Label(body, text="Growth Habit Stats", font=("Segoe UI", 12, "bold"), bg="#111111", fg="#f2f2f2").grid(row=0, column=1, sticky="w", padx=(14, 0), pady=(0, 8))

    obs_box = scrolledtext.ScrolledText(body, wrap=tk.WORD, font=("Segoe UI", 11), bg="#0b0b0b", fg="#ffecec", relief="solid", bd=1, padx=12, pady=10)
    obs_box.grid(row=1, column=0, sticky="nsew")

    for obs in observations:
        obs_box.insert(tk.END, f"• {obs}\n\n")
    obs_box.configure(state="disabled")

    stats_box = scrolledtext.ScrolledText(body, wrap=tk.WORD, font=("Consolas", 10), bg="#0b0b0b", fg="#e6e6e6", relief="solid", bd=1, padx=12, pady=10)
    stats_box.grid(row=1, column=1, sticky="nsew", padx=(14, 0))

    for task in GROWTH_TASKS:
        row = stats.get(task, {})
        stats_box.insert(tk.END, f"{task}\n")
        stats_box.insert(tk.END, f"  Done:     {row.get('done', 0)}\n")
        stats_box.insert(tk.END, f"  Missed:   {row.get('missed', 0)}\n")
        stats_box.insert(tk.END, f"  Expected: {row.get('expected', 0)}\n")
        stats_box.insert(tk.END, f"  Rate:     {row.get('rate', 0)}%\n\n")
    stats_box.configure(state="disabled")

    buttons = tk.Frame(window, bg="#111111")
    buttons.pack(fill="x", padx=18, pady=(0, 16))

    tk.Button(
        buttons,
        text="Refresh Insights",
        font=("Segoe UI", 10, "bold"),
        bg="#5b4bb7",
        fg="white",
        command=lambda: [window.destroy(), show_insights_window()],
        width=18
    ).pack(side="left", ipady=5)

    tk.Button(
        buttons,
        text="Close",
        font=("Segoe UI", 10, "bold"),
        bg="#333333",
        fg="white",
        command=window.destroy,
        width=14
    ).pack(side="right", ipady=5)



# -----------------------------
# PHASE 2B - TREND DETECTION
# -----------------------------
def record_mentions_growth_task(record, task_name):
    """A task is expected only when the saved record actually mentions it.

    This keeps early prototype days fair if they did not include every growth habit yet.
    """
    target = normalize_task_name(task_name).lower()
    task_names = {
        normalize_task_name(task.get("text", "")).lower()
        for task in record.get("tasks", [])
    }
    missed_names = {
        normalize_task_name(task).lower()
        for task in record.get("missed_tasks", [])
    }
    return target in task_names or target in missed_names


def get_logged_records_chronological(history=None, limit=7):
    """Return real logged sessions oldest-to-newest for trend reading."""
    history = history if history is not None else load_history()
    rows = get_recent_logged_records(history, limit=limit)
    return list(reversed(rows))


def split_rate(values):
    """Compare older half against newer half for simple trend direction."""
    if not values:
        return 0, 0

    if len(values) == 1:
        rate = 100 if values[0] else 0
        return rate, rate

    midpoint = max(1, len(values) // 2)
    older = values[:midpoint]
    newer = values[midpoint:]

    older_rate = int((sum(older) / len(older)) * 100) if older else 0
    newer_rate = int((sum(newer) / len(newer)) * 100) if newer else older_rate
    return older_rate, newer_rate


def classify_trend_status(older_rate, newer_rate, current_rate, expected):
    """Return a readable status label for a habit."""
    if expected < 2:
        return "DATA BUILDING", "Not enough logged opportunities yet."

    change = newer_rate - older_rate

    if change >= 20:
        return "IMPROVING", f"Recent rate improved by {change} points."
    if change <= -20:
        return "DECLINING", f"Recent rate dropped by {abs(change)} points."
    if current_rate >= 75:
        return "STABLE / STRONG", "This habit is holding as a reliable anchor."
    if current_rate <= 40:
        return "STABLE / WEAK", "This habit is still lagging and needs intervention."
    return "STABLE", "This habit is moving, but not clearly improving yet."


def count_latest_streak(values, target_value):
    """Count newest-backward streak of completions or misses from chronological values."""
    streak = 0
    for value in reversed(values):
        if value == target_value:
            streak += 1
        else:
            break
    return streak


def build_task_trend_rows(limit=7):
    """Build trend rows for the four growth habits only.

    Check Tickets and misc work tasks are intentionally ignored.
    """
    history = load_history()
    records = get_logged_records_chronological(history, limit=limit)
    rows = []

    for task_name in GROWTH_TASKS:
        values = []
        dates = []

        for date_key, record, _ in records:
            if not record_mentions_growth_task(record, task_name):
                continue
            values.append(1 if task_done(record, task_name) else 0)
            dates.append(date_key)

        expected = len(values)
        done = sum(values)
        missed = expected - done
        current_rate = int((done / expected) * 100) if expected else 0
        older_rate, newer_rate = split_rate(values)
        status, status_reason = classify_trend_status(older_rate, newer_rate, current_rate, expected)
        completed_streak = count_latest_streak(values, 1)
        missed_streak = count_latest_streak(values, 0)
        pattern = " ".join("✓" if value else "□" for value in values) if values else "No logged opportunities yet."

        if expected == 0:
            observation = "No usable logged opportunities yet for this habit."
        elif missed_streak >= 2:
            observation = f"{task_name} has been missed for {missed_streak} consecutive logged opportunit{'y' if missed_streak == 1 else 'ies'}."
        elif completed_streak >= 2:
            observation = f"{task_name} has been completed for {completed_streak} consecutive logged opportunit{'y' if completed_streak == 1 else 'ies'}."
        elif status == "DECLINING":
            observation = f"{task_name} is slipping compared with earlier logged sessions."
        elif status == "IMPROVING":
            observation = f"{task_name} is recovering compared with earlier logged sessions."
        elif current_rate >= 75:
            observation = f"{task_name} is currently one of your anchors."
        elif current_rate <= 40:
            observation = f"{task_name} is a weak point and should be attacked with a tiny rep."
        else:
            observation = f"{task_name} is in the middle zone: not broken, not locked in."

        rows.append({
            "task": task_name,
            "values": values,
            "dates": dates,
            "expected": expected,
            "done": done,
            "missed": missed,
            "rate": current_rate,
            "older_rate": older_rate,
            "newer_rate": newer_rate,
            "change": newer_rate - older_rate,
            "status": status,
            "status_reason": status_reason,
            "completed_streak": completed_streak,
            "missed_streak": missed_streak,
            "pattern": pattern,
            "observation": observation,
        })

    return rows



def display_habit_name(task_name):
    """Short UI labels for the four growth habits."""
    normalized = normalize_task_name(task_name)
    labels = {
        "Complete Workout": "WORKOUT",
        "Coding Core Task": "CODING",
        "Networking / LinkedIn": "NETWORKING",
        "Spanish Review": "SPANISH",
        "Reading": "READING",
    }
    return labels.get(normalized, normalized.upper())


def display_status(status):
    """Make status labels cleaner for the dashboard."""
    if status == "STABLE / WEAK":
        return "NEEDS ATTENTION"
    if status == "STABLE / STRONG":
        return "STABLE / STRONG"
    return status

def build_trend_summary(rows):
    usable = [row for row in rows if row["expected"] > 0]
    if not usable:
        return {
            "strongest": "Unknown",
            "weakest": "Unknown",
            "intervention": "Log more sessions",
            "improved": "Unknown",
            "declining": "Unknown",
            "summary_note": "Not enough trend data yet. Finish more sessions so patterns can emerge.",
        }

    strongest = max(usable, key=lambda row: (row["rate"], row["done"], -row["missed"]))
    weakest = min(usable, key=lambda row: (row["rate"], -row["missed"], row["done"]))
    intervention = max(usable, key=lambda row: (row["missed_streak"], row["missed"], -row["rate"]))
    improved = max(usable, key=lambda row: (row["change"], row["newer_rate"]))
    declining = min(usable, key=lambda row: (row["change"], row["newer_rate"]))

    if intervention["missed"] > 0:
        note = f"{intervention['task']} needs the most attention: {intervention['missed']} missed logged opportunit{'y' if intervention['missed'] == 1 else 'ies'}."
    else:
        note = "No major missed-opportunity gap is showing. Keep logging and maintain pressure."

    return {
        "strongest": strongest["task"],
        "weakest": weakest["task"],
        "intervention": intervention["task"],
        "improved": improved["task"] if improved["change"] > 0 else "No clear improvement yet",
        "declining": declining["task"] if declining["change"] < 0 else "No clear decline yet",
        "summary_note": note,
    }


def build_trend_alerts(rows, max_alerts=4):
    """Small BAM section: most important trend signals first.

    Alerts are intentionally short so Trends can be understood without opening
    every habit card. Check Tickets and misc work tasks are ignored because rows
    only contain the four growth habits.
    """
    alerts = []
    usable = [row for row in rows if row.get("expected", 0) > 0]

    if not usable:
        return [("INFO", "Log more finished sessions so trend alerts can form.")]

    brain = analyze_history()
    inactive_days = int(brain.get("inactive_days_recent", 0) or 0)
    if inactive_days >= 3:
        alerts.append((
            "WARNING",
            f"{inactive_days} inactive calendar days recently. Restart with one priority action."
        ))

    # Main warning: largest missed-opportunity gap.
    largest_gap = max(usable, key=lambda row: (row.get("missed", 0), -row.get("rate", 0)))
    if largest_gap.get("missed", 0) > 0:
        alerts.append((
            "WARNING",
            f"{display_habit_name(largest_gap['task'])} has the largest gap: "
            f"{largest_gap['missed']} missed logged opportunit{'y' if largest_gap['missed'] == 1 else 'ies'}."
        ))

    # Consecutive misses matter more than simple low percentage.
    missed_streaks = [row for row in usable if row.get("missed_streak", 0) >= 2]
    missed_streaks.sort(key=lambda row: (row["missed_streak"], row["missed"]), reverse=True)
    for row in missed_streaks[:1]:
        alerts.append((
            "WARNING",
            f"{display_habit_name(row['task'])} has been missed "
            f"{row['missed_streak']} logged opportunities in a row."
        ))

    # Positive anchor: a real completion streak.
    completion_streaks = [row for row in usable if row.get("completed_streak", 0) >= 3]
    completion_streaks.sort(key=lambda row: (row["completed_streak"], row["rate"]), reverse=True)
    for row in completion_streaks[:1]:
        alerts.append((
            "POSITIVE",
            f"{display_habit_name(row['task'])} has been completed "
            f"{row['completed_streak']} logged opportunities in a row."
        ))

    # Improvement signal.
    improvers = [row for row in usable if row.get("change", 0) >= 20]
    improvers.sort(key=lambda row: (row["change"], row["newer_rate"]), reverse=True)
    for row in improvers[:1]:
        alerts.append((
            "UP",
            f"{display_habit_name(row['task'])} improved from {row['older_rate']}% to {row['newer_rate']}%."
        ))

    # Decline signal.
    decliners = [row for row in usable if row.get("change", 0) <= -20]
    decliners.sort(key=lambda row: (row["change"], row["newer_rate"]))
    for row in decliners[:1]:
        alerts.append((
            "WARNING",
            f"{display_habit_name(row['task'])} dropped from {row['older_rate']}% to {row['newer_rate']}%."
        ))

    # Remove duplicates while preserving order.
    cleaned = []
    seen = set()
    for level, message in alerts:
        if message in seen:
            continue
        seen.add(message)
        cleaned.append((level, message))

    return cleaned[:max_alerts] if cleaned else [("INFO", "No major trend alerts yet. Keep logging sessions.")]



def get_warning_trend_alerts():
    """Return only caution-sign trend alerts for chat commands like 'show alerts'."""
    rows = build_task_trend_rows(limit=7)
    alerts = build_trend_alerts(rows)
    warnings = [(level, message) for level, message in alerts if level == "WARNING"]
    return warnings


def format_trend_alerts_answer():
    """Compact chat answer for trend alerts only."""
    warnings = get_warning_trend_alerts()
    if not warnings:
        return "TREND ALERTS\n\nNo caution alerts right now. Keep logging sessions so the bot can keep reading the pattern."

    lines = ["TREND ALERTS", ""]
    for _, message in warnings:
        lines.append(f"⚠ {message}")
    lines.append("")
    lines.append("Next move: handle the first alert with one small logged action.")
    return "\n".join(lines).strip()


def is_alert_request(user_input):
    """Chat shortcuts for alert-only readout."""
    text = str(user_input or "").lower().strip()
    return any(phrase in text for phrase in [
        "show alerts", "any alerts", "alerts", "trend alerts", "warning alerts",
        "caution alerts", "what alerts", "what are my alerts"
    ])


# -----------------------------
# BACKFILL / MISSED LOGGING HELPERS
# -----------------------------
def parse_backfill_date(user_input):
    """Detect simple backfill dates from chat text using the 2 AM momentum day."""
    text = str(user_input or "").lower()
    today = get_momentum_now().date()

    if "yesterday" in text:
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if "today" in text:
        return today.strftime("%Y-%m-%d")

    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if match:
        try:
            datetime.strptime(match.group(1), "%Y-%m-%d")
            return match.group(1)
        except Exception:
            pass

    return None


def is_backfill_logging_message(user_input):
    """Detect messages like: 'yesterday I did Spanish 20m and workout 30m'."""
    text = str(user_input or "").lower()
    if not parse_backfill_date(text):
        return False
    if not detect_completed_tasks_from_text(text):
        return False
    return any(word in text for word in [
        "did", "done", "finished", "completed", "logged", "worked", "exercised",
        "yesterday", "backfill", "back log", "late log"
    ])


def update_history_for_date_from_text(date_key, user_input):
    """Backfill a prior date without needing the GUI.

    This is intentionally simple: one message can mark one or more tasks complete.
    Duration uses the same 10/20/30+ detection already used for today's chat logging.
    """
    history = load_history()
    previous = history.get(date_key, {}) if isinstance(history, dict) else {}
    detected = detect_completed_tasks_from_text(user_input)
    duration = detect_duration_from_text(user_input)

    existing_durations = {}
    for item in previous.get("tasks", []):
        canonical = normalize_task_name(item.get("text", ""))
        existing_durations[canonical] = normalize_duration(
            item.get("duration_minutes") or item.get("minutes") or (10 if item.get("done") else 0)
        )

    for canonical in detected:
        existing_durations[canonical] = normalize_task_duration(canonical, duration)

    completed_count = 0
    missed_tasks = []
    tasks_payload = []
    xp_earned = 0

    for task in DAILY_TASKS:
        canonical = task["canonical"]
        task_duration = normalize_task_duration(canonical, existing_durations.get(canonical, 0))
        done = task_duration > 0
        xp = get_task_xp(canonical, task_duration)
        if done:
            completed_count += 1
            xp_earned += xp
        else:
            missed_tasks.append(canonical)

        tasks_payload.append({
            "text": canonical,
            "display": task["display"],
            "done": done,
            "duration_minutes": task_duration,
            "duration_label": DURATION_LABELS.get(task_duration, ""),
            "core": True,
            "task_type": task["task_type"],
            "difficulty": task["difficulty"],
            "xp": xp,
        })

    history[date_key] = {
        "date": date_key,
        "saved_at": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
        "location": normalize_location(previous.get("location", "Work")),
        "energy": normalize_energy(previous.get("energy", "Normal")),
        "completed": completed_count,
        "total": len(DAILY_TASKS),
        "finished_all": completed_count == len(DAILY_TASKS),
        "missed_tasks": missed_tasks,
        "bonus_completed": previous.get("bonus_completed", 0),
        "bonus_total": previous.get("bonus_total", 0),
        "tasks": tasks_payload,
        "xp_earned": xp_earned,
        "xp_possible": get_max_daily_xp(),
        "day_closed": bool(previous.get("day_closed", False)),
        "overall_streak": previous.get("overall_streak", 0),
        "energy_note": "Backfilled from chat command.",
    }

    save_json_file(HISTORY_FILE, history)
    return detected, duration, history[date_key]


def format_backfill_response(date_key, detected, duration, record):
    logged_names = ", ".join(get_daily_task_display_name(task) for task in detected)
    duration_label = DURATION_LABELS.get(duration, f"{duration}m")
    return f"""BACKFILLED LOG — {date_key}

Logged: {logged_names} — {duration_label}

Completed: {record.get('completed')}/{record.get('total')}
EXP: {record.get('xp_earned')}/{record.get('xp_possible')} XP

This is now saved into momentum_history.json.""".strip()


def get_start_day_gap_prompt():
    """Short prompt shown when starting the day and recent calendar gaps exist."""
    brain = analyze_history()
    inactive_days = int(brain.get("inactive_days_recent", 0) or 0)
    if inactive_days <= 0:
        return ""

    return (
        f"\n\nGap check: {inactive_days} inactive calendar day(s) recently.\n"
        "If you did work away from this PC, type it like:\n"
        "yesterday I did Spanish 20m and workout 30m"
    )

def show_trends_window():
    rows = build_task_trend_rows(limit=7)
    summary = build_trend_summary(rows)

    window = tk.Toplevel(root)
    window.title("Trend Detection - Phase 2B.2")
    window.geometry("1180x840")
    window.configure(bg="#111111")
    window.transient(root)

    tk.Label(
        window,
        text="Trend Detection",
        font=("Segoe UI", 22, "bold"),
        bg="#111111",
        fg="#f2f2f2"
    ).pack(anchor="w", padx=18, pady=(18, 4))

    tk.Label(
        window,
        text="Phase 2B.2: trend alerts, quick summary, and expandable habit cards. Work tickets are ignored.",
        font=("Segoe UI", 10),
        bg="#111111",
        fg="#aaaaaa"
    ).pack(anchor="w", padx=18, pady=(0, 12))

    alerts = build_trend_alerts(rows)
    alerts_frame = tk.Frame(window, bg="#0b0b0b", relief="solid", bd=1)
    alerts_frame.pack(fill="x", padx=18, pady=(0, 12))

    tk.Label(
        alerts_frame,
        text="TREND ALERTS",
        font=("Segoe UI", 12, "bold"),
        bg="#0b0b0b",
        fg="#f2f2f2",
        anchor="w"
    ).pack(fill="x", padx=14, pady=(10, 4))

    icon_map = {
        "WARNING": "⚠",
        "POSITIVE": "✓",
        "UP": "↑",
        "INFO": "•",
    }
    color_map = {
        "WARNING": "#ffd166",
        "POSITIVE": "#74c476",
        "UP": "#8bd3ff",
        "INFO": "#d6d6d6",
    }

    for level, message in alerts:
        row_frame = tk.Frame(alerts_frame, bg="#0b0b0b")
        row_frame.pack(fill="x", padx=14, pady=2)

        tk.Label(
            row_frame,
            text=icon_map.get(level, "•"),
            font=("Segoe UI", 12, "bold"),
            bg="#0b0b0b",
            fg=color_map.get(level, "#d6d6d6"),
            width=3,
            anchor="center"
        ).pack(side="left")

        tk.Label(
            row_frame,
            text=message,
            font=("Segoe UI", 10, "bold" if level == "WARNING" else "normal"),
            bg="#0b0b0b",
            fg="#f2f2f2",
            anchor="w",
            justify="left",
            wraplength=900
        ).pack(side="left", fill="x", expand=True)


    summary_frame = tk.Frame(window, bg="#191919", relief="solid", bd=1)
    summary_frame.pack(fill="x", padx=18, pady=(0, 14))

    summary_rows = [
        ("Strongest Trend", display_habit_name(summary["strongest"])),
        ("Weakest Trend", display_habit_name(summary["weakest"])),
        ("Needs Attention", display_habit_name(summary["intervention"])),
        ("Most Improved", display_habit_name(summary["improved"])),
        ("Summary", summary["summary_note"]),
    ]

    # Only show declining when there is a real decline. Otherwise it is noise.
    if summary.get("declining") and summary["declining"] != "No clear decline yet":
        summary_rows.insert(4, ("Declining", display_habit_name(summary["declining"])))

    for i, (label, value) in enumerate(summary_rows):
        tk.Label(
            summary_frame,
            text=label,
            font=("Segoe UI", 10, "bold"),
            bg="#191919",
            fg="#8bd3ff",
            width=20,
            anchor="w"
        ).grid(row=i, column=0, sticky="w", padx=14, pady=5)

        # Make summary note use display labels too.
        value_text = str(value)
        for task_name in GROWTH_TASKS:
            value_text = value_text.replace(task_name, display_habit_name(task_name))

        tk.Label(
            summary_frame,
            text=value_text,
            font=("Segoe UI", 10),
            bg="#191919",
            fg="#f2f2f2",
            anchor="w",
            wraplength=780,
            justify="left"
        ).grid(row=i, column=1, sticky="w", padx=10, pady=5)

    body = tk.Frame(window, bg="#111111")
    body.pack(fill="both", expand=True, padx=18, pady=(0, 12))
    body.columnconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)

    canvas = tk.Canvas(body, bg="#111111", highlightthickness=0)
    canvas.grid(row=0, column=0, sticky="nsew")

    scrollbar = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    canvas.configure(yscrollcommand=scrollbar.set)

    cards_frame = tk.Frame(canvas, bg="#111111")
    window_id = canvas.create_window((0, 0), window=cards_frame, anchor="nw")

    def refresh_scroll_region(event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def resize_cards(event=None):
        canvas.itemconfigure(window_id, width=canvas.winfo_width())

    cards_frame.bind("<Configure>", refresh_scroll_region)
    canvas.bind("<Configure>", resize_cards)

    expanded_rows = {}

    def trend_card_color(status):
        clean_status = display_status(status)
        if clean_status == "IMPROVING":
            return "#16351f"
        if clean_status == "DECLINING":
            return "#3a1616"
        if clean_status == "NEEDS ATTENTION":
            return "#3a2d12"
        if clean_status == "STABLE / STRONG":
            return "#132b3a"
        return "#191919"

    def make_detail_text(row):
        observation = row["observation"]
        status_reason = row["status_reason"]
        for task_name in GROWTH_TASKS:
            observation = observation.replace(task_name, display_habit_name(task_name).title())
            status_reason = status_reason.replace(task_name, display_habit_name(task_name).title())

        lines = [
            f"Rate: {row['rate']}% ({row['done']} of {row['expected']} logged opportunities)",
            f"Missed: {row['missed']}",
            f"Older vs Recent: {row['older_rate']}% → {row['newer_rate']}%",
            f"Pattern: {row['pattern']}  (oldest → newest)",
        ]

        if row["completed_streak"]:
            lines.append(f"Completion streak: {row['completed_streak']} logged opportunit{'y' if row['completed_streak'] == 1 else 'ies'}")
        if row["missed_streak"]:
            lines.append(f"Miss streak: {row['missed_streak']} logged opportunit{'y' if row['missed_streak'] == 1 else 'ies'}")

        lines.append(f"Observation: {observation}")
        lines.append(f"Reason: {status_reason}")
        return "\n".join(lines)

    def toggle_card(row_index):
        data = expanded_rows[row_index]
        is_open = data["open"]
        detail_frame = data["detail"]
        arrow_var = data["arrow_var"]

        if is_open:
            detail_frame.pack_forget()
            arrow_var.set("▶")
            data["open"] = False
        else:
            detail_frame.pack(fill="x", padx=14, pady=(0, 12))
            arrow_var.set("▼")
            data["open"] = True
        refresh_scroll_region()

    tk.Label(
        cards_frame,
        text="Click a habit to expand details. The cards stay collapsed by default so this remains a quick-read dashboard.",
        font=("Segoe UI", 9),
        bg="#111111",
        fg="#aaaaaa",
        anchor="w"
    ).pack(fill="x", pady=(0, 8))

    for index, row in enumerate(rows):
        card = tk.Frame(cards_frame, bg="#0b0b0b", relief="solid", bd=1)
        card.pack(fill="x", pady=(0, 10))

        header_bg = trend_card_color(row["status"])
        header = tk.Frame(card, bg=header_bg, cursor="hand2")
        header.pack(fill="x")

        arrow_var = tk.StringVar(value="▶")
        tk.Label(
            header,
            textvariable=arrow_var,
            font=("Segoe UI", 13, "bold"),
            bg=header_bg,
            fg="#f2f2f2",
            width=3,
            anchor="center"
        ).pack(side="left", padx=(6, 0), pady=10)

        tk.Label(
            header,
            text=display_habit_name(row["task"]),
            font=("Segoe UI", 13, "bold"),
            bg=header_bg,
            fg="#8bd3ff",
            anchor="w"
        ).pack(side="left", padx=(8, 16), pady=10)

        status_label = display_status(row["status"])
        tk.Label(
            header,
            text=status_label,
            font=("Segoe UI", 11, "bold"),
            bg=header_bg,
            fg="#ffffff",
            anchor="w"
        ).pack(side="left", padx=(0, 20), pady=10)

        tk.Label(
            header,
            text=f"{row['rate']}%  |  missed {row['missed']}  |  {row['pattern']}",
            font=("Segoe UI", 10),
            bg=header_bg,
            fg="#e6e6e6",
            anchor="w"
        ).pack(side="left", fill="x", expand=True, padx=(0, 12), pady=10)

        detail = tk.Frame(card, bg="#0b0b0b")
        detail_text = tk.Label(
            detail,
            text=make_detail_text(row),
            font=("Consolas", 10),
            bg="#0b0b0b",
            fg="#ffecec",
            justify="left",
            anchor="w",
            wraplength=950,
        )
        detail_text.pack(fill="x", padx=18, pady=(12, 4), anchor="w")

        expanded_rows[index] = {
            "open": False,
            "detail": detail,
            "arrow_var": arrow_var,
        }

        header.bind("<Button-1>", lambda event, i=index: toggle_card(i))
        for child in header.winfo_children():
            child.bind("<Button-1>", lambda event, i=index: toggle_card(i))

    buttons = tk.Frame(window, bg="#111111")
    buttons.pack(fill="x", padx=18, pady=(0, 16))

    tk.Button(
        buttons,
        text="Refresh Trends",
        font=("Segoe UI", 10, "bold"),
        bg="#5b4bb7",
        fg="white",
        command=lambda: [window.destroy(), show_trends_window()],
        width=18
    ).pack(side="left", ipady=5)

    tk.Button(
        buttons,
        text="Close",
        font=("Segoe UI", 10, "bold"),
        bg="#333333",
        fg="white",
        command=window.destroy,
        width=14
    ).pack(side="right", ipady=5)


# -----------------------------
# DAILY TASKS / V8 - EXP + DURATION OVALS + COMPLETE DAY REVIEW
# -----------------------------
TODAY_TASKS_FILE = Path("today_tasks_state.json")

DAILY_TASKS = [
    # V17 tiers: core-heavy tasks require 20m minimum, 30m growth, 40m+ mastery.
    {"display": "Coding", "canonical": "Coding Core Task", "difficulty": "Hard", "task_type": "manual", "xp_by_minutes": {20: 40, 30: 60, 40: 80}},
    {"display": "Spanish", "canonical": "Spanish Review", "difficulty": "Medium", "task_type": "study", "xp_by_minutes": {20: 30, 30: 45, 40: 60}},
    {"display": "Exercise", "canonical": "Complete Workout", "difficulty": "Hard", "task_type": "workout", "xp_by_minutes": {20: 40, 30: 60, 40: 80}},
    # Networking and Reading stay intentionally lighter.
    {"display": "Networking", "canonical": "Networking / LinkedIn", "difficulty": "Medium", "task_type": "link", "xp_by_minutes": {10: 15, 20: 35, 30: 50}},
    {"display": "Reading", "canonical": "Reading", "difficulty": "Easy", "task_type": "manual", "xp_by_minutes": {10: 10, 20: 20, 30: 30}},
]

TASK_LINKS = {
    "Spanish Review": "https://spanish-flashcards-voice.onrender.com/",
}

DURATION_OPTIONS = [10, 20, 30, 40]
DURATION_LABELS = {0: "", 10: "10m", 20: "20m", 30: "30m+", 40: "40m+"}


def get_task_link(canonical):
    return TASK_LINKS.get(canonical, "")


def open_task_link(canonical):
    """Open the task link/tool if one exists. Returns True when opened."""
    if normalize_task_name(canonical) == "Complete Workout":
        try:
            show_workout_tracker_window()
            return True
        except Exception as error:
            messagebox.showerror("Could not open workout tracker", f"Could not open Workout Tracker.\n\n{error}")
            return False

    url = get_task_link(canonical)
    if not url:
        return False
    try:
        webbrowser.open_new_tab(url)
        return True
    except Exception as error:
        messagebox.showerror("Could not open link", f"Could not open {get_daily_task_display_name(canonical)} link.\n\n{error}")
        return False


ENERGY_OPTIONS = ["Low", "Normal"]
LOCATION_OPTIONS = ["Work", "Home"]

TASK_MINIMUMS = {
    "Low": {
        "Coding Core Task": "10m minimum",
        "Spanish Review": "10m minimum",
        "Complete Workout": "10m movement",
        "Networking / LinkedIn": "10m / one action",
        "Reading": "5–10m",
    },
    "Normal": {
        "Coding Core Task": "20m minimum / 30m growth / 40m mastery",
        "Spanish Review": "20m minimum / 30m growth / 40m mastery",
        "Complete Workout": "20m minimum / 30m growth / 40m mastery",
        "Networking / LinkedIn": "10m minimum / 20m growth / 30m mastery",
        "Reading": "10m minimum / 20m growth / 30m mastery",
    },
}


def normalize_energy(value):
    value = str(value or "Normal").strip().title()
    return value if value in ENERGY_OPTIONS else "Normal"


def normalize_location(value):
    value = str(value or "Work").strip().title()
    return value if value in LOCATION_OPTIONS else "Work"


def normalize_duration(value):
    try:
        value = int(value or 0)
    except Exception:
        return 0
    if value >= 40:
        return 40
    if value >= 30:
        return 30
    if value >= 20:
        return 20
    if value >= 10:
        return 10
    return 0


def get_duration_options(canonical):
    """Return allowed buttons for each task. Heavy tasks get 20/30/40; lighter tasks get 10/20/30."""
    canonical = normalize_task_name(canonical)
    task = get_task_definition(canonical)
    if not task:
        return [10, 20, 30]
    return sorted(int(value) for value in task.get("xp_by_minutes", {}).keys())


def normalize_task_duration(canonical, value):
    """Normalize a duration, then cap it to that task's highest supported tier."""
    duration = normalize_duration(value)
    options = get_duration_options(canonical)
    if not options:
        return duration
    if duration >= max(options):
        return max(options)
    valid = [option for option in options if duration >= option]
    return max(valid) if valid else 0


def get_task_minimum(canonical, energy):
    energy = normalize_energy(energy)
    return TASK_MINIMUMS.get(energy, TASK_MINIMUMS["Normal"]).get(canonical, "one small loop")


def get_task_definition(canonical):
    for task in DAILY_TASKS:
        if task["canonical"] == canonical:
            return task
    return None


def get_task_xp(canonical, minutes):
    task = get_task_definition(canonical)
    if not task:
        return 0
    minutes = normalize_task_duration(canonical, minutes)
    return int(task.get("xp_by_minutes", {}).get(minutes, 0) or 0)


def get_max_daily_xp():
    total = 0
    for task in DAILY_TASKS:
        total += max(task.get("xp_by_minutes", {0: 0}).values())
    return total


def get_state_duration(state, canonical):
    durations = state.get("durations", {}) if isinstance(state, dict) else {}
    if canonical in durations:
        return normalize_task_duration(canonical, durations.get(canonical, 0))
    # Backward compatibility with older checkbox-only state.
    if state.get("tasks", {}).get(canonical, False):
        return normalize_task_duration(canonical, 10)
    return 0


TASK_ALIAS_PATTERNS = {
    "Coding Core Task": [r"\bcod(e|ed|ing)\b", r"\bworked on (the )?app\b", r"\bpython\b", r"\bprogram(med|ming)?\b"],
    "Spanish Review": [r"\bspanish\b", r"\bespa[nñ]ol\b", r"\bflash ?cards?\b"],
    "Complete Workout": [r"\bwork(ed)? ?out\b", r"\bexercise(d)?\b", r"\bexercised\b", r"\bexcercised\b", r"\bexcercise(d)?\b", r"\br(an|un|unning)\b", r"\bpush ?ups?\b", r"\bpull ?ups?\b", r"\bdips?\b", r"\bsquats?\b", r"\bjump(ed)? rope\b"],
    "Networking / LinkedIn": [r"\blinked ?in\b", r"\bnetwork(ed|ing)?\b", r"\bcomment(ed)?\b", r"\bconnection\b", r"\bconnect(ed)?\b"],
    "Reading": [r"\bread(ing)?\b", r"\bbook\b", r"\bchapter\b"],
}


def get_momentum_now():
    """Return the effective momentum timestamp using the 2 AM rollover.

Anything before 2 AM still belongs to the previous momentum day.
This keeps late-night work from being split across two days.
"""
    now = datetime.now()
    if now.hour < DAY_ROLLOVER_HOUR:
        now = now - timedelta(days=1)
    return now


def today_key():
    return get_momentum_now().strftime("%Y-%m-%d")


def get_default_today_state():
    key = today_key()
    history = load_history()
    existing = history.get(key, {}) if isinstance(history, dict) else {}
    durations = {}

    for task in existing.get("tasks", []):
        canonical = normalize_task_name(task.get("text", ""))
        if task.get("done"):
            durations[canonical] = normalize_duration(task.get("duration_minutes") or task.get("minutes") or 10)

    return {
        "date": key,
        "updated_at": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
        "tasks": {task["canonical"]: (normalize_duration(durations.get(task["canonical"], 0)) > 0) for task in DAILY_TASKS},
        "durations": {task["canonical"]: normalize_duration(durations.get(task["canonical"], 0)) for task in DAILY_TASKS},
        "location": normalize_location(existing.get("location", "")) if existing.get("location") else "",
        "energy": normalize_energy(existing.get("energy", "")) if existing.get("energy") else "",
        "day_closed": bool(existing.get("day_closed", False)),
    }


def load_today_task_state():
    state = load_json_file(TODAY_TASKS_FILE, None)
    if not isinstance(state, dict) or state.get("date") != today_key():
        state = get_default_today_state()
        save_json_file(TODAY_TASKS_FILE, state)
    state["energy"] = normalize_energy(state.get("energy", "")) if state.get("energy") else ""
    state["location"] = normalize_location(state.get("location", "")) if state.get("location") else ""
    state.setdefault("tasks", {})
    state.setdefault("durations", {})
    state["day_closed"] = bool(state.get("day_closed", False))
    for task in DAILY_TASKS:
        canonical = task["canonical"]
        duration = normalize_task_duration(canonical, state["durations"].get(canonical, 0))
        if duration == 0 and state["tasks"].get(canonical, False):
            duration = 10
        state["durations"][canonical] = duration
        state["tasks"][canonical] = duration > 0
    return state


def save_today_task_state(state):
    state["date"] = today_key()
    state["updated_at"] = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    state["day_closed"] = bool(state.get("day_closed", False))
    state.setdefault("tasks", {})
    state.setdefault("durations", {})
    for task in DAILY_TASKS:
        canonical = task["canonical"]
        duration = normalize_task_duration(canonical, state["durations"].get(canonical, 0))
        state["durations"][canonical] = duration
        state["tasks"][canonical] = duration > 0
    save_json_file(TODAY_TASKS_FILE, state)


def get_daily_task_display_name(canonical):
    for task in DAILY_TASKS:
        if task["canonical"] == canonical:
            return task["display"]
    return canonical


def detect_completed_tasks_from_text(user_input):
    text = str(user_input or "").lower()
    detected = []
    for canonical, patterns in TASK_ALIAS_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                detected.append(canonical)
                break
    cleaned = []
    seen = set()
    for item in detected:
        if item not in seen:
            seen.add(item)
            cleaned.append(item)
    return cleaned


def detect_duration_from_text(user_input):
    text = str(user_input or "").lower()
    if "40+" in text or "forty" in text or re.search(r"\b(40|45|50|60|90|120)\s*(min|mins|minutes|m)\b", text):
        return 40
    if "30+" in text or "thirty" in text or re.search(r"\b(30|35)\s*(min|mins|minutes|m)\b", text):
        return 30
    if "twenty" in text or re.search(r"\b(20|25)\s*(min|mins|minutes|m)\b", text):
        return 20
    if "ten" in text or re.search(r"\b(10|15)\s*(min|mins|minutes|m)\b", text):
        return 10
    return 10


def has_duration_in_text(user_input):
    """Return True when the user explicitly typed a time like 10m, 20 mins, 30+, etc."""
    text = str(user_input or "").lower()
    return bool(
        "30+" in text
        or any(word in text for word in ["ten", "twenty", "thirty"])
        or re.search(r"\b(10|15|20|25|30|35|40|45|50|60|90|120)\s*(min|mins|minutes|m)\b", text)
    )


def is_task_display_request(user_input):
    text = str(user_input or "").lower()
    return any(phrase in text for phrase in [
        "daily tasks", "show tasks", "show me tasks", "task list", "open tasks", "today's tasks", "todays tasks"
    ])


def is_task_logging_message(user_input):
    text = str(user_input or "").lower()
    if is_task_display_request(text) or is_task_start_request(text):
        return False
    detected = detect_completed_tasks_from_text(text)
    if not detected:
        return False

    # Mobile/tablet shortcut: "Spanish 30mins", "read 20m", "coding 45 minutes".
    # Anything above 30 is capped to the 30m+ tier by normalize_duration().
    if has_duration_in_text(text):
        return True

    return any(word in text for word in [
        "did", "done", "finished", "completed", "logged", "today", "i ", "worked", "exercised", "excercised"
    ])


def is_task_start_request(user_input):
    text = str(user_input or "").lower()
    detected = detect_completed_tasks_from_text(text)
    if not detected:
        return False
    return any(phrase in text for phrase in [
        "i want to do", "want to do", "start", "open", "launch", "pull up",
        "practice", "study", "learn", "work on", "do spanish", "spanish app"
    ])


def handle_task_start_request(user_input):
    state = load_today_task_state()
    detected = detect_completed_tasks_from_text(user_input)
    opened = []
    no_link = []

    for canonical in detected:
        if open_task_link(canonical):
            opened.append(get_daily_task_display_name(canonical))
        else:
            no_link.append(get_daily_task_display_name(canonical))

    if opened:
        response = f"Opened: {', '.join(opened)}.\n\n"
    else:
        response = "No direct link is set for that task yet.\n\n"

    if no_link:
        response += f"No link yet for: {', '.join(no_link)}.\n\n"

    response += format_today_tasks_status(state, title="DAILY TASKS")
    return response


def update_today_tasks_from_text(user_input):
    state = load_today_task_state()
    detected = detect_completed_tasks_from_text(user_input)
    duration = detect_duration_from_text(user_input)
    for canonical in detected:
        state.setdefault("durations", {})[canonical] = normalize_task_duration(canonical, duration)
        state.setdefault("tasks", {})[canonical] = True
    save_today_task_state(state)
    save_today_progress_to_history(state)
    return detected, state


def get_today_completed_remaining(state=None):
    state = state or load_today_task_state()
    completed = []
    remaining = []
    for task in DAILY_TASKS:
        duration = get_state_duration(state, task["canonical"])
        if duration > 0:
            completed.append(task["display"])
        else:
            remaining.append(task["display"])
    return completed, remaining


def format_today_tasks_status(state=None, title="DAILY TASKS"):
    state = state or load_today_task_state()
    completed, remaining = get_today_completed_remaining(state)
    xp_earned = get_today_xp(state)
    xp_total = get_max_daily_xp()
    lines = [title, ""]
    for task in DAILY_TASKS:
        canonical = task["canonical"]
        duration = get_state_duration(state, canonical)
        mark = "✓" if duration > 0 else "☐"
        xp = get_task_xp(canonical, duration)
        if duration > 0:
            lines.append(f"{mark} {task['display']} — {DURATION_LABELS[duration]} — {format_task_tier(canonical, duration)} (+{xp} XP)")
        else:
            lines.append(f"{mark} {task['display']} — not logged")
    lines.append("")
    lines.append(f"Today EXP: {xp_earned}/{xp_total} XP")
    lines.append(f"Completed: {len(completed)}/{len(DAILY_TASKS)}")
    if remaining:
        lines.append("Remaining: " + ", ".join(remaining))
    else:
        lines.append("Clean finish. All daily tasks are checked off.")
    return "\n".join(lines).strip()


def get_today_xp(state=None):
    state = state or load_today_task_state()
    total = 0
    for task in DAILY_TASKS:
        canonical = task["canonical"]
        total += get_task_xp(canonical, get_state_duration(state, canonical))
    return total


def build_today_progress_snapshot(state=None):
    """Small tablet-friendly EXP snapshot for the Daily Tasks top card."""
    state = state or load_today_task_state()
    completed, remaining = get_today_completed_remaining(state)
    total_tasks = len(DAILY_TASKS)
    done_count = len(completed)
    xp_earned = get_today_xp(state)
    xp_total = get_max_daily_xp()
    percent = int((xp_earned / xp_total) * 100) if xp_total else 0

    filled = int(round((percent / 100) * 10)) if xp_total else 0
    bar = "█" * filled + "░" * (10 - filled)

    minimums_met, masteries = get_minimums_masteries_snapshot(state)
    all_minimums_met = minimums_met >= total_tasks
    bonus = get_bonus_round_recommendation(state) if all_minimums_met else None

    if not all_minimums_met:
        next_task = remaining[0] if remaining else "next minimum"
        next_move = f"Next minimum: {next_task}"
    elif bonus:
        next_move = f"Bonus target: {bonus['display']} → {TIER_NAMES.get(bonus['next_tier'], 'Next Tier')} (+{bonus['xp_gain']} XP)"
    else:
        next_move = "Full Mastery board — nothing left to upgrade today."

    return {
        "completed": done_count,
        "total": total_tasks,
        "remaining_count": len(remaining),
        "minimums_met": minimums_met,
        "masteries": masteries,
        "all_minimums_met": all_minimums_met,
        "bonus": bonus,
        "bonus_xp_remaining": max(xp_total - xp_earned, 0),
        "percent": percent,
        "bar": bar,
        "remaining": remaining,
        "next_move": next_move,
        "xp_earned": xp_earned,
        "xp_total": xp_total,
    }


def save_today_progress_to_history(state=None):
    state = state or load_today_task_state()
    history = load_history()
    key = today_key()
    completed_count = sum(1 for task in DAILY_TASKS if get_state_duration(state, task["canonical"]) > 0)
    total_count = len(DAILY_TASKS)

    tasks_payload = []
    missed_tasks = []
    xp_earned = 0

    for task in DAILY_TASKS:
        canonical = task["canonical"]
        duration = get_state_duration(state, canonical)
        done = duration > 0
        xp = get_task_xp(canonical, duration)
        if not done:
            missed_tasks.append(canonical)
        else:
            xp_earned += xp
        tasks_payload.append({
            "text": canonical,
            "display": task["display"],
            "done": done,
            "duration_minutes": duration,
            "duration_label": DURATION_LABELS.get(duration, ""),
            "core": True,
            "task_type": task["task_type"],
            "difficulty": task["difficulty"],
            "xp": xp,
        })

    previous = history.get(key, {}) if isinstance(history, dict) else {}
    history[key] = {
        "date": key,
        "saved_at": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
        "location": normalize_location(state.get("location") or previous.get("location") or "Work"),
        "energy": normalize_energy(state.get("energy") or previous.get("energy") or "Normal"),
        "completed": completed_count,
        "total": total_count,
        "finished_all": completed_count == total_count,
        "missed_tasks": missed_tasks,
        "bonus_completed": previous.get("bonus_completed", 0),
        "bonus_total": previous.get("bonus_total", 0),
        "tasks": tasks_payload,
        "xp_earned": xp_earned,
        "xp_possible": get_max_daily_xp(),
        "day_closed": bool(state.get("day_closed", previous.get("day_closed", False))),
        "overall_streak": previous.get("overall_streak", 0),
        "energy_note": "Daily task progress saved from Builder Branch v17 Bonus Round EXP duration buttons.",
    }
    save_json_file(HISTORY_FILE, history)
    return history[key]



def get_minimum_required_minutes(canonical, energy):
    """Minimum effort needed before the task feels fairly handled for the selected energy."""
    energy = normalize_energy(energy)
    if energy == "Low":
        return 10
    normal_minimums = {
        "Coding Core Task": 20,
        "Spanish Review": 20,
        "Complete Workout": 20,
        "Networking / LinkedIn": 10,
        "Reading": 10,
    }
    return normal_minimums.get(canonical, 10)




# -----------------------------
# V17 TIERS / BONUS ROUND
# -----------------------------
TIER_NAMES = {
    "none": "Not Started",
    "minimum": "Minimum Met",
    "growth": "Growth",
    "mastery": "Mastery",
}

TIER_ICONS = {
    "none": "⚪",
    "minimum": "🟢",
    "growth": "🔵",
    "mastery": "🟣",
}


def get_tier_thresholds(canonical):
    options = get_duration_options(canonical)
    if len(options) >= 3:
        return {"minimum": options[0], "growth": options[1], "mastery": options[2]}
    if len(options) == 2:
        return {"minimum": options[0], "growth": options[1], "mastery": options[1]}
    return {"minimum": 10, "growth": 20, "mastery": 30}


def get_task_tier(canonical, duration):
    duration = normalize_task_duration(canonical, duration)
    thresholds = get_tier_thresholds(canonical)
    if duration >= thresholds["mastery"]:
        return "mastery"
    if duration >= thresholds["growth"]:
        return "growth"
    if duration >= thresholds["minimum"]:
        return "minimum"
    return "none"


def format_task_tier(canonical, duration):
    tier = get_task_tier(canonical, duration)
    return f"{TIER_ICONS.get(tier, '⚪')} {TIER_NAMES.get(tier, 'Not Started')}"


def get_next_tier_duration(canonical, duration):
    duration = normalize_task_duration(canonical, duration)
    for option in get_duration_options(canonical):
        if option > duration:
            return option
    return 0


def get_bonus_round_recommendation(state=None):
    """Pick the best optional re-engagement target after all minimums are met."""
    state = state or load_today_task_state()
    brain = analyze_history()
    stats = brain.get("growth_task_stats", {}) or {}
    weakest = brain.get("weakest_habit", "Unknown")
    candidates = []

    for task in DAILY_TASKS:
        canonical = task["canonical"]
        duration = get_state_duration(state, canonical)
        next_duration = get_next_tier_duration(canonical, duration)
        if not next_duration:
            continue

        row = stats.get(canonical, {}) or {}
        missed = int(row.get("missed", 0) or 0)
        rate = int(row.get("rate", 0) or 0)
        current_xp = get_task_xp(canonical, duration)
        next_xp = get_task_xp(canonical, next_duration)
        xp_gain = max(next_xp - current_xp, 0)
        tier = get_task_tier(canonical, duration)

        score = xp_gain
        score += missed * 6
        if canonical == weakest:
            score += 14
        if tier == "none":
            score += 20
        elif tier == "minimum":
            score += 10
        elif tier == "growth":
            score += 5
        if rate and rate <= 50:
            score += 6

        if canonical == weakest and missed:
            reason = f"{task['display']} is your weakest recent habit and still has room to climb today."
        elif canonical == weakest:
            reason = f"{task['display']} is the weakest recent habit, so extra reps here pay off."
        elif missed:
            reason = f"{task['display']} has {missed} recent missed logged opportunit{'y' if missed == 1 else 'ies'}."
        elif tier == "minimum":
            reason = f"{task['display']} is only at Minimum Met. One more block turns it into Growth."
        elif tier == "growth":
            reason = f"{task['display']} is close to Mastery. One more push finishes the upgrade."
        else:
            reason = f"{task['display']} gives the cleanest optional upgrade right now."

        candidates.append({
            "canonical": canonical,
            "display": task["display"],
            "score": score,
            "duration": duration,
            "next_duration": next_duration,
            "xp_gain": xp_gain,
            "reason": reason,
            "current_tier": tier,
            "next_tier": get_task_tier(canonical, next_duration),
        })

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item["score"], item["xp_gain"], item["next_duration"]), reverse=True)
    return candidates[0]


def get_minimums_masteries_snapshot(state=None):
    state = state or load_today_task_state()
    minimums = 0
    masteries = 0
    for task in DAILY_TASKS:
        tier = get_task_tier(task["canonical"], get_state_duration(state, task["canonical"]))
        if tier in ("minimum", "growth", "mastery"):
            minimums += 1
        if tier == "mastery":
            masteries += 1
    return minimums, masteries


# -----------------------------
# WORKOUT TRACKER
# -----------------------------
WORKOUT_ROWS = [
    ("Biceps", "Chin ups"),
    ("Biceps", "Dumbbell curls"),
    ("Shoulders", "Pull ups"),
    ("Shoulders", "Push ups"),
    ("Triceps", "Dips"),
    ("Triceps", "Close-grip push ups"),
    ("Legs", "Barbell squats"),
    ("Legs", "Squats"),
    ("Cardio", "Jump rope"),
    ("Cardio", "Jogging"),
    ("Abs", "Leg raises"),
    ("Abs", "Curved leg twisting"),
]


WORKOUT_SESSION_LABELS = ["Home", "Work", "Extra"]


def normalize_workout_session_label(value):
    value = str(value or "Home").strip().title()
    return value if value in WORKOUT_SESSION_LABELS else "Extra"


def load_workout_history():
    data = load_json_file(WORKOUT_HISTORY_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("max_reps", {})
    data.setdefault("sessions", [])
    return data


def save_workout_history(data):
    data.setdefault("max_reps", {})
    data.setdefault("sessions", [])
    save_json_file(WORKOUT_HISTORY_FILE, data)


def normalize_workout_text(value):
    """Small normalizer so chat commands match exercises/muscles cleanly."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def get_workout_muscles():
    return sorted({muscle for muscle, _ in WORKOUT_ROWS})


def get_exercises_for_muscle(muscle_name):
    target = normalize_workout_text(muscle_name)
    return [
        (muscle, exercise)
        for muscle, exercise in WORKOUT_ROWS
        if normalize_workout_text(muscle) == target
    ]


def find_requested_workout_muscle(user_input):
    """Return a muscle group if the user typed it by itself or inside a max-rep question."""
    text = normalize_workout_text(user_input)
    for muscle in get_workout_muscles():
        muscle_key = normalize_workout_text(muscle)
        if text == muscle_key or re.search(rf"\b{re.escape(muscle_key)}\b", text):
            return muscle
    return ""


def is_max_reps_request(user_input):
    text = normalize_workout_text(user_input)
    if "max rep" in text or "max reps" in text or "maxed reps" in text:
        return True

    # Shortcut: typing only "Biceps", "Legs", etc. shows that group's maxes.
    return bool(find_requested_workout_muscle(user_input) and text in [normalize_workout_text(m) for m in get_workout_muscles()])


def format_max_reps_answer(user_input=""):
    """Compact max-rep readout for all exercises or one muscle group."""
    history = load_workout_history()
    max_reps = history.get("max_reps", {}) if isinstance(history.get("max_reps", {}), dict) else {}

    muscle_filter = find_requested_workout_muscle(user_input)
    rows = get_exercises_for_muscle(muscle_filter) if muscle_filter else WORKOUT_ROWS

    title = f"MAX REPS — {muscle_filter.upper()}" if muscle_filter else "MAX REPS"
    lines = [title, ""]
    for muscle, exercise in rows:
        value = parse_rep_value(max_reps.get(exercise, 0))
        if muscle_filter:
            lines.append(f"{exercise}: {value}")
        else:
            lines.append(f"{exercise}: {value}")
    return "\n".join(lines).strip()


def is_workout_log_request(user_input):
    text = normalize_workout_text(user_input)
    phrases = [
        "exercise log",
        "workout log",
        "show exercise log",
        "show workout log",
        "full exercise log",
        "full workout log",
        "i want to exercise",
        "i exercised",
    ]
    return any(phrase in text for phrase in phrases)


def format_workout_session_row(row):
    exercise = row.get("exercise", "Unknown")
    sets = row.get("sets", [])
    clean_sets = [str(value) for value in sets if parse_rep_value(value) > 0]
    sets_text = "/".join(clean_sets) if clean_sets else "no sets"
    session_best = parse_rep_value(row.get("session_best", 0))
    max_reps = parse_rep_value(row.get("max_reps", 0))
    return f"• {exercise}: {sets_text} | best {session_best} | max {max_reps}"


def format_workout_log_answer(limit=12):
    """Show only today's workout sessions in a clean chat format.

    Full older history stays saved in workout_history.json, but the normal
    chat command stays focused on today so it does not eat reading space.
    """
    history = load_workout_history()
    sessions = history.get("sessions", []) if isinstance(history.get("sessions", []), list) else []
    today = today_key()

    today_sessions = [
        session for session in sessions
        if session.get("date") == today
    ]

    if not today_sessions:
        return f"WORKOUT LOG — TODAY\n\nNo workout sessions saved for {today} yet."

    today_sessions = sorted(
        today_sessions,
        key=lambda item: (item.get("session_label", ""), item.get("saved_at", ""))
    )

    lines = ["WORKOUT LOG — TODAY", f"{today}", ""]

    for session in today_sessions:
        focus = session.get("focus_area", "Exercise")
        energy = session.get("energy", "Normal")
        session_label = normalize_workout_session_label(session.get("session_label", "Home"))
        rows = session.get("rows", []) if isinstance(session.get("rows", []), list) else []

        lines.append(f"{session_label} — {focus} / {energy}")
        if rows:
            for row in rows:
                lines.append(format_workout_session_row(row))
        else:
            lines.append("• No exercise rows were logged.")
        lines.append("")

    lines.append(f"Total Sessions Today: {len(today_sessions)}")
    return "\n".join(lines).strip()


# -----------------------------
# WHAT NOW / NEXT MOVE ENGINE
# -----------------------------
def is_what_now_request(user_input):
    """Chat shortcuts for the recommendation engine."""
    text = normalize_workout_text(user_input)
    phrases = [
        "what now",
        "next move",
        "what should i do next",
        "what do i do next",
        "what should i focus",
        "recommend next",
        "recommend a task",
        "where should i put time",
    ]
    return any(phrase in text for phrase in phrases)


def get_weekend_survival_day_name():
    """User-specific survival window: Saturday, Sunday, and Monday."""
    day_index = get_momentum_now().weekday()  # Monday=0, Sunday=6
    names = {0: "Monday", 5: "Saturday", 6: "Sunday"}
    return names.get(day_index, "")


def get_what_now_minutes(canonical, energy, survival_mode=False):
    """Return the suggested dose for the next move."""
    canonical = normalize_task_name(canonical)
    energy = normalize_energy(energy)

    if survival_mode:
        # Lowered standard for the danger window: enough to keep the chain alive.
        if canonical in ("Networking / LinkedIn", "Reading"):
            return 10
        return 20 if energy != "Low" else 10

    if energy == "Low":
        return 10

    # Normal workday/default targets.
    normal = {
        "Coding Core Task": 20,
        "Spanish Review": 20,
        "Complete Workout": 20,
        "Networking / LinkedIn": 10,
        "Reading": 10,
    }
    return normal.get(canonical, 10)


def get_what_now_action_line(canonical, minutes):
    """Give one concrete action instead of just naming a task."""
    canonical = normalize_task_name(canonical)
    display = get_daily_task_display_name(canonical)

    if canonical == "Networking / LinkedIn":
        return f"Do Networking for {minutes}m: one comment OR one connection."
    if canonical == "Coding Core Task":
        return f"Do Coding for {minutes}m: open the project and make one small improvement."
    if canonical == "Spanish Review":
        return f"Do Spanish for {minutes}m: one review/shadowing loop."
    if canonical == "Complete Workout":
        return f"Do Exercise for {minutes}m: movement first, intensity optional."
    if canonical == "Reading":
        return f"Read for {minutes}m: one useful section counts."
    return f"Do {display} for {minutes}m."


def score_what_now_candidate(task, state, brain, survival_mode=False):
    """Rule-based scoring that creates the illusion of intelligence without needing AI."""
    canonical = task["canonical"]
    duration = get_state_duration(state, canonical)
    done = duration > 0
    stats = brain.get("growth_task_stats", {}) or {}
    row = stats.get(canonical, {}) or {}
    weakest = brain.get("weakest_habit", "Unknown")

    score = 0

    # Missing tasks are the first priority.
    if not done:
        score += 100
    else:
        score -= 25

    # User-specific importance weights.
    weights = {
        "Coding Core Task": 35,
        "Spanish Review": 28,
        "Complete Workout": 30,
        "Networking / LinkedIn": 24,
        "Reading": 12,
    }
    score += weights.get(canonical, 10)

    missed = int(row.get("missed", 0) or 0)
    rate = int(row.get("rate", 0) or 0)
    score += missed * 8
    if canonical == weakest:
        score += 20
    if rate and rate <= 50:
        score += 8

    # Survival day: lower standards, but avoid total shutdown by opening with body/study/career.
    if survival_mode:
        survival_weights = {
            "Complete Workout": 22,
            "Spanish Review": 18,
            "Coding Core Task": 18,
            "Reading": 8,
            "Networking / LinkedIn": 4,
        }
        score += survival_weights.get(canonical, 0)

    return score


def pick_what_now_task(state, survival_mode=False):
    brain = analyze_history()
    candidates = []

    for task in DAILY_TASKS:
        canonical = task["canonical"]
        duration = get_state_duration(state, canonical)
        next_duration = get_next_tier_duration(canonical, duration)
        score = score_what_now_candidate(task, state, brain, survival_mode=survival_mode)
        candidates.append({
            "canonical": canonical,
            "display": task["display"],
            "duration": duration,
            "next_duration": next_duration,
            "score": score,
        })

    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[0] if candidates else None


def format_what_now_answer():
    """The command-center recommendation: status report -> one next move."""
    state = load_today_task_state()
    energy = normalize_energy(state.get("energy") or "Normal")
    location = normalize_location(state.get("location") or "Work")
    snapshot = build_today_progress_snapshot(state)
    brain = analyze_history()
    weekend_day = get_weekend_survival_day_name()
    zero_day = snapshot["completed"] == 0
    survival_mode = bool(weekend_day and zero_day)

    # If all minimums are done, use the existing bonus brain.
    if snapshot.get("all_minimums_met"):
        bonus = get_bonus_round_recommendation(state)
        if bonus:
            minutes_needed = max(
                normalize_task_duration(bonus["canonical"], bonus["next_duration"]) - normalize_task_duration(bonus["canonical"], bonus.get("duration", 0)),
                10
            )
            return f"""WHAT NOW

Mode: Bonus Round
Status: All minimums complete.
Energy: {energy}
Location: {location}

Recommended Next Move:
{bonus['display']} +{minutes_needed}m

Reason:
{bonus['reason']}

Reward:
+{bonus['xp_gain']} XP""".strip()

        return "WHAT NOW\n\nAll minimums are complete and the bonus board is maxed. Clean closeout is allowed."

    pick = pick_what_now_task(state, survival_mode=survival_mode)
    if not pick:
        return "WHAT NOW\n\nNo recommendation available yet. Open Daily Tasks and log one small action."

    canonical = pick["canonical"]
    minutes = get_what_now_minutes(canonical, energy, survival_mode=survival_mode)
    action = get_what_now_action_line(canonical, minutes)

    missing = snapshot.get("remaining", [])
    weakest = brain.get("weakest_habit", "Unknown")

    if survival_mode:
        mode = f"{weekend_day} Survival Mode"
        reason = "You are at 0 today inside the danger window, so the standard is lowered: restart the system, do not optimize."
        objective = "Objective: break the zero."
    elif len(missing) == 1:
        mode = "Finish The Board"
        reason = f"Only {missing[0]} remains. Finish the checklist before bonus decisions."
        objective = "Objective: close the daily loop."
    elif canonical == weakest:
        mode = "Pressure Target"
        reason = f"{get_daily_task_display_name(canonical)} is currently the weakest growth habit, so it gets priority."
        objective = "Objective: stop the slip."
    else:
        mode = "Next Best Move"
        reason = f"{get_daily_task_display_name(canonical)} is the highest-value incomplete task right now."
        objective = "Objective: move the day forward."

    return f"""WHAT NOW

Mode: {mode}
Energy: {energy}
Location: {location}
Progress: {snapshot['completed']}/{snapshot['total']} tasks • {snapshot['xp_earned']}/{snapshot['xp_total']} XP

Recommended Next Move:
{action}

Reason:
{reason}

{objective}""".strip()

def parse_rep_value(value):
    text = str(value or "").strip()
    if not text:
        return 0
    match = re.search(r"\d+", text)
    if not match:
        return 0
    try:
        return int(match.group(0))
    except Exception:
        return 0


def show_workout_tracker_window():
    """Simple workout tracker with persistent max reps by exercise."""
    data = load_workout_history()
    max_reps = data.get("max_reps", {}) if isinstance(data.get("max_reps", {}), dict) else {}

    window = tk.Toplevel(root)
    window.title("Workout Tracker")
    window.geometry("980x640")
    window.configure(bg="#f4f4f4")
    window.transient(root)

    tk.Label(
        window,
        text="Workout Tracker",
        font=("Segoe UI", 24, "bold"),
        bg="#f4f4f4",
        fg="#4a5d6a"
    ).pack(anchor="w", padx=18, pady=(18, 4))

    tk.Label(
        window,
        text="Keep it simple. Log the work. Compare later.",
        font=("Segoe UI", 10, "bold"),
        bg="#f4f4f4",
        fg="#111111"
    ).pack(anchor="w", padx=18, pady=(0, 14))

    meta = tk.Frame(window, bg="#f4f4f4")
    meta.pack(fill="x", padx=18, pady=(0, 12))

    tk.Label(meta, text="Date:", font=("Segoe UI", 10, "bold"), bg="#f4f4f4").pack(side="left")
    date_entry = tk.Entry(meta, width=12, font=("Segoe UI", 10))
    date_entry.insert(0, today_key())
    date_entry.pack(side="left", padx=(6, 24))

    tk.Label(meta, text="Focus Area:", font=("Segoe UI", 10, "bold"), bg="#f4f4f4").pack(side="left")
    focus_entry = tk.Entry(meta, width=18, font=("Segoe UI", 10))
    focus_entry.insert(0, "Exercise")
    focus_entry.pack(side="left", padx=(6, 18))

    tk.Label(meta, text="Session:", font=("Segoe UI", 10, "bold"), bg="#f4f4f4").pack(side="left")
    session_var = tk.StringVar(value="Home")
    tk.OptionMenu(meta, session_var, *WORKOUT_SESSION_LABELS).pack(side="left", padx=(6, 18))

    tk.Label(meta, text="Energy:", font=("Segoe UI", 10, "bold"), bg="#f4f4f4").pack(side="left")
    energy_entry = tk.Entry(meta, width=12, font=("Segoe UI", 10))
    energy_entry.insert(0, normalize_energy(load_today_task_state().get("energy") or "Normal"))
    energy_entry.pack(side="left", padx=(6, 0))

    table_outer = tk.Frame(window, bg="#f4f4f4")
    table_outer.pack(fill="both", expand=True, padx=18, pady=(0, 12))

    canvas = tk.Canvas(table_outer, bg="#f4f4f4", highlightthickness=0)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar = tk.Scrollbar(table_outer, orient="vertical", command=canvas.yview)
    scrollbar.pack(side="right", fill="y")
    canvas.configure(yscrollcommand=scrollbar.set)

    table = tk.Frame(canvas, bg="#f4f4f4")
    table_window = canvas.create_window((0, 0), window=table, anchor="nw")

    def update_scroll(event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def resize_table(event=None):
        canvas.itemconfigure(table_window, width=canvas.winfo_width())

    table.bind("<Configure>", update_scroll)
    canvas.bind("<Configure>", resize_table)

    headers = ["Muscle", "Exercise", "Set 1", "Set 2", "Set 3", "Max Reps"]
    widths = [16, 30, 11, 11, 11, 14]
    colors = ["#e8bfd6", "#e8bfd6", "#cbc6e9", "#d1e2f2", "#cde5c8", "#efc5c2"]

    for col, header in enumerate(headers):
        tk.Label(
            table,
            text=header,
            font=("Segoe UI", 10, "bold"),
            bg=colors[col],
            fg="#000000",
            relief="solid",
            bd=1,
            width=widths[col],
            pady=7,
        ).grid(row=0, column=col, sticky="nsew")

    entry_rows = []
    for row_index, (muscle, exercise) in enumerate(WORKOUT_ROWS, start=1):
        tk.Label(table, text=muscle, font=("Segoe UI", 10), bg="#ffffff", relief="solid", bd=1, width=widths[0], anchor="w", padx=4, pady=6).grid(row=row_index, column=0, sticky="nsew")
        tk.Label(table, text=exercise, font=("Segoe UI", 10), bg="#ffffff", relief="solid", bd=1, width=widths[1], anchor="w", padx=4, pady=6).grid(row=row_index, column=1, sticky="nsew")

        set_entries = []
        for col in range(2, 5):
            entry = tk.Entry(table, font=("Segoe UI", 10), justify="center", relief="solid", bd=1, width=widths[col])
            entry.grid(row=row_index, column=col, sticky="nsew")
            set_entries.append(entry)

        max_var = tk.StringVar(value=str(max_reps.get(exercise, "")))
        max_entry = tk.Entry(table, textvariable=max_var, font=("Segoe UI", 10), justify="center", relief="solid", bd=1, width=widths[5])
        max_entry.grid(row=row_index, column=5, sticky="nsew")
        entry_rows.append({"muscle": muscle, "exercise": exercise, "sets": set_entries, "max_var": max_var})

    def clear_inputs():
        for row in entry_rows:
            for entry in row["sets"]:
                entry.delete(0, tk.END)

    def reload_today(show_missing=True):
        clear_inputs()
        history = load_workout_history()
        sessions = history.get("sessions", [])
        key = date_entry.get().strip() or today_key()
        wanted_label = normalize_workout_session_label(session_var.get())
        latest = None
        for session in reversed(sessions):
            session_label = normalize_workout_session_label(session.get("session_label", "Home"))
            if session.get("date") == key and session_label == wanted_label:
                latest = session
                break
        if not latest:
            if show_missing:
                messagebox.showinfo("Reload Session", f"No {wanted_label} workout session saved for {key} yet.")
            return
        by_exercise = {item.get("exercise"): item for item in latest.get("rows", [])}
        for row in entry_rows:
            item = by_exercise.get(row["exercise"])
            if not item:
                continue
            values = item.get("sets", [])
            for i, entry in enumerate(row["sets"]):
                if i < len(values) and values[i]:
                    entry.insert(0, str(values[i]))
        focus_entry.delete(0, tk.END)
        focus_entry.insert(0, latest.get("focus_area", "Exercise"))
        energy_entry.delete(0, tk.END)
        energy_entry.insert(0, latest.get("energy", "Normal"))

    def save_workout_session():
        key = date_entry.get().strip() or today_key()
        focus = focus_entry.get().strip() or "Exercise"
        session_label = normalize_workout_session_label(session_var.get())
        energy = normalize_energy(energy_entry.get().strip() or "Normal")

        history = load_workout_history()
        max_reps_data = history.get("max_reps", {}) if isinstance(history.get("max_reps", {}), dict) else {}
        rows_payload = []

        for row in entry_rows:
            set_values = [parse_rep_value(entry.get()) for entry in row["sets"]]
            typed_max = parse_rep_value(row["max_var"].get())
            best_from_sets = max(set_values) if set_values else 0
            previous_best = parse_rep_value(max_reps_data.get(row["exercise"], 0))
            new_best = max(previous_best, typed_max, best_from_sets)
            if new_best:
                max_reps_data[row["exercise"]] = new_best
                row["max_var"].set(str(new_best))
            if any(value > 0 for value in set_values):
                rows_payload.append({
                    "muscle": row["muscle"],
                    "exercise": row["exercise"],
                    "sets": set_values,
                    "session_best": best_from_sets,
                    "max_reps": new_best,
                })

        session = {
            "date": key,
            "session_label": session_label,
            "session_id": f"{key}_{normalize_workout_text(session_label).replace(' ', '_')}",
            "saved_at": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
            "focus_area": focus,
            "energy": energy,
            "rows": rows_payload,
        }

        sessions = [
            item for item in history.get("sessions", [])
            if not (item.get("date") == key and normalize_workout_session_label(item.get("session_label", "Home")) == session_label)
        ]
        sessions.append(session)
        sessions.sort(key=lambda item: (item.get("date", ""), item.get("session_label", "")))
        history["sessions"] = sessions
        history["max_reps"] = max_reps_data
        save_workout_history(history)

        # Tie tracker save into today's momentum task when the saved date is today's momentum date.
        if key == today_key():
            state = load_today_task_state()
            state["energy"] = energy
            state.setdefault("durations", {})["Complete Workout"] = max(get_state_duration(state, "Complete Workout"), 30)
            state.setdefault("tasks", {})["Complete Workout"] = True
            save_today_task_state(state)
            save_today_progress_to_history(state)
            refresh_brain_preview("Workout saved")

        message = f"Workout saved for {key} — {session_label}. Rows logged: {len(rows_payload)}. Exercise marked complete for today."
        insert_chat_line("Companion", message, "companion")
        messagebox.showinfo("Workout Saved", message)

    buttons = tk.Frame(window, bg="#f4f4f4")
    buttons.pack(fill="x", padx=18, pady=(0, 18))

    tk.Button(buttons, text="Save Workout Session", font=("Segoe UI", 10, "bold"), bg="#002855", fg="white", command=save_workout_session, width=22).pack(side="left", ipady=8)
    tk.Button(buttons, text="Clear Inputs", font=("Segoe UI", 10, "bold"), bg="#ffffff", fg="#000000", command=clear_inputs, width=16).pack(side="left", padx=(14, 0), ipady=8)
    tk.Button(buttons, text="Reload Session", font=("Segoe UI", 10, "bold"), bg="#ffffff", fg="#000000", command=lambda: reload_today(True), width=16).pack(side="left", padx=(14, 0), ipady=8)

    def on_session_change(*_):
        reload_today(False)

    session_var.trace_add("write", on_session_change)

    # Auto-restore saved set values for the selected current-day session.
    # It naturally starts blank after the 2 AM momentum day rollover.
    reload_today(False)



# -----------------------------
# COMPANION PERSONALITY / DAY CLOSEOUT
# -----------------------------
MISSION_COMPANION_LINES = {
    "MISSION COMPLETE": [
        "Everything got fed today. No loose ends, no recovery debt — close the loop and enjoy the win.",
        "Clean sweep. Tomorrow starts from momentum, not cleanup.",
        "That is a full loop. Pack it in without guilt.",
    ],
    "SOLID DAY": [
        "The main loops got attention. This was not perfect, but it was real progress.",
        "Solid work. Nothing dramatic needed — just carry the thread forward tomorrow.",
        "The day moved forward. That is the whole game.",
    ],
    "RECOVERY DAY": [
        "The chain survived on low energy. That counts — do not turn recovery into defeat.",
        "Not a power day, but not a zero day either. That matters.",
        "Maintenance is still momentum. Close it clean and come back sharper.",
    ],
    "MORE IN THE TANK": [
        "{focus} never got a turn today. Not a disaster — just do not let it become tomorrow's excuse too.",
        "The day moved, but {focus} is still sitting on the table. One small block would make this stronger.",
        "You can close the day, but the scoreboard is pointing at {focus}. Remember that tomorrow.",
    ],
    "WARNING": [
        "{focus} is starting to slip. Tomorrow should begin there before anything fun opens.",
        "This is the warning light, not the crash. Put the first rep into {focus} tomorrow.",
        "The pattern is getting loud around {focus}. Attack it early next session.",
    ],
}

FINAL_COMPANION_LINES = {
    "MISSION COMPLETE": [
        "Day sealed. No loose ends tonight.",
        "Mission complete. Take the win and shut it down clean.",
        "Full loop closed. That is the standard you are building toward.",
    ],
    "SOLID DAY": [
        "Day sealed. Progress counted, thread preserved.",
        "Closed clean. Tomorrow does not start from zero.",
        "Good checkpoint. Now recover without negotiating with yourself.",
    ],
    "RECOVERY DAY": [
        "Day sealed. The chain stayed alive — that was the job today.",
        "Closed as recovery. No shame in maintenance when energy was low.",
        "Recovery logged. Tomorrow gets a cleaner shot.",
    ],
    "MORE IN THE TANK": [
        "Day sealed with something left on the table. Tomorrow's first move is {focus}.",
        "Closed anyway. That is allowed — but {focus} gets first claim tomorrow.",
        "Day closed. The note is simple: {focus} cannot keep getting skipped.",
    ],
    "WARNING": [
        "Day sealed, but the warning stays active. Open tomorrow with {focus}.",
        "Closed. No lecture — just a target: {focus} first tomorrow.",
        "Day closed. The next session starts by breaking the slip around {focus}.",
    ],
}


def get_review_focus(review):
    """Pick the one task the companion should react to."""
    if review.get("untouched"):
        return review["untouched"][0]
    below = review.get("below_minimum") or []
    if below:
        return below[0].get("display", "the weakest task")
    remaining = review.get("snapshot", {}).get("remaining", [])
    if remaining:
        return remaining[0]
    return "the next clean loop"


def pick_companion_line(review, final=False):
    """Return a short personality line so closeout does not feel like a static report."""
    status = review.get("status", "SOLID DAY")
    focus = get_review_focus(review)
    pool_map = FINAL_COMPANION_LINES if final else MISSION_COMPANION_LINES
    pool = pool_map.get(status) or pool_map.get("SOLID DAY") or ["Keep the loop alive."]
    line = random.choice(pool)
    return line.format(focus=focus)


def build_mission_review(state=None):
    """Build final-day review data before the user commits to ending the day."""
    state = state or load_today_task_state()
    energy = normalize_energy(state.get("energy") or "Normal")
    snapshot = build_today_progress_snapshot(state)
    untouched = []
    below_minimum = []

    for task in DAILY_TASKS:
        canonical = task["canonical"]
        duration = get_state_duration(state, canonical)
        minimum = get_minimum_required_minutes(canonical, energy)
        if duration <= 0:
            untouched.append(task["display"])
        elif duration < minimum:
            below_minimum.append({
                "display": task["display"],
                "duration": duration,
                "minimum": minimum,
            })

    if not untouched and not below_minimum and snapshot["percent"] >= 90:
        status = "MISSION COMPLETE"
    elif energy == "Low" and snapshot["completed"] >= 1:
        status = "RECOVERY DAY"
    elif untouched or below_minimum:
        status = "MORE IN THE TANK"
    else:
        status = "SOLID DAY"

    # Companion line is intentionally chosen separately so the day closeout
    # feels alive instead of repeating the same static report every time.
    temp_review = {
        "status": status,
        "untouched": untouched,
        "below_minimum": below_minimum,
        "snapshot": snapshot,
        "energy": energy,
    }
    companion = pick_companion_line(temp_review, final=False)

    return {
        "status": status,
        "companion": companion,
        "untouched": untouched,
        "below_minimum": below_minimum,
        "snapshot": snapshot,
        "energy": energy,
    }


def split_companion_sentences(text, max_sentences=3):
    """Turn one companion line into short spaced thoughts for the closeout screen."""
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if not cleaned:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
    return sentences[:max_sentences]


def append_companion_block(lines, companion_line):
    """Add visual separation before the companion thought, no heading needed."""
    thoughts = split_companion_sentences(companion_line)
    if not thoughts:
        return

    # Two blank lines create the visual handoff from scoreboard to companion.
    lines.append("")
    lines.append("")

    for thought in thoughts:
        lines.append(thought)
        lines.append("")

    # Remove the extra trailing blank line for cleaner text boxes.
    while lines and lines[-1] == "":
        lines.pop()


def format_mission_review_text(review):
    """Readable popup layout: tight stats up top, companion thought separated below."""
    snapshot = review["snapshot"]
    lines = [
        "MISSION REVIEW",
        "",
        review["status"],
        "",
        f"{snapshot['xp_earned']} / {snapshot['xp_total']} XP",
        "",
        f"Minimums: {snapshot['minimums_met']}/{snapshot['total']}",
        f"Masteries: {snapshot['masteries']}/{snapshot['total']}",
        "",
    ]

    lines.append("Not Touched:")
    if review["untouched"]:
        for name in review["untouched"]:
            lines.append(f"• {name}")
    else:
        lines.append("• None")
    lines.append("")

    lines.append("Below Minimum:")
    if review["below_minimum"]:
        for item in review["below_minimum"]:
            lines.append(f"• {item['display']}")
    else:
        lines.append("• None")

    append_companion_block(lines, review["companion"])
    return "\n".join(lines).strip()



def is_day_complete_request(user_input):
    """Tablet-friendly command for ending/reviewing the day from the chat box."""
    text = str(user_input or "").lower().strip()
    phrases = [
        "i'm done for today", "im done for today", "i am done for today",
        "done for today", "tasks complete", "task complete", "complete tasks",
        "complete day", "end day", "finish day", "finish today's tasks",
        "finish todays tasks", "call it a day", "wrap up day", "day complete",
    ]
    return any(phrase in text for phrase in phrases)


def is_finish_day_request(user_input):
    """Follow-up command after a short mission review.

    Keep this forgiving for mobile/tablet use. The user should not have to
    remember one exact phrase when closing the day.
    """
    text = str(user_input or "").lower().strip()
    text = re.sub(r"\s+", " ", text)

    phrases = {
        "finish",
        "done",
        "close day",
        "close the day",
        "end day",
        "end the day",
        "day complete",
        "complete day",
        "complete the day",
        "call it",
        "call it a day",
        "wrap it",
        "wrap up",
        "wrap up day",
        "finish day",
        "finish today",
        "yes finish",
        "seal it",
        "log it",
        # Backward compatibility if an older screen/message is still open.
        "complete anyway",
        "finish anyway",
        "complete it",
    }
    return text in phrases


def format_mission_review_mobile_text(review, final=False):
    """Tight chat-sized closeout for mobile/tablet use.

    Quick review shows the scoreboard plus gaps.
    Final closeout removes the gap lists and leaves only the final companion thought.
    """
    snapshot = review["snapshot"]
    companion_line = pick_companion_line(review, final=final) if final else review["companion"]

    lines = [
        "DAY CLOSED" if final else "QUICK DAY REVIEW",
        "",
        f"{snapshot['xp_earned']} / {snapshot['xp_total']} XP",
        f"Minimums: {snapshot['minimums_met']}/{snapshot['total']}",
        f"Masteries: {snapshot['masteries']}/{snapshot['total']}",
    ]

    if not final:
        lines.append("")
        lines.append("Not Touched:")
        if review["untouched"]:
            for name in review["untouched"]:
                lines.append(f"• {name}")
        else:
            lines.append("• None")

        lines.append("")
        lines.append("Below Minimum:")
        if review["below_minimum"]:
            for item in review["below_minimum"]:
                lines.append(f"• {item['display']}")
        else:
            lines.append("• None")

    append_companion_block(lines, companion_line)

    if not final:
        lines.append("")
        lines.append("Type: finish")

    return "\n".join(lines).strip()


def handle_day_complete_command(final=False):
    """Save progress, run the Mission Review, and return a compact chat response."""
    state = load_today_task_state()
    if final:
        state["day_closed"] = True
    save_today_task_state(state)
    save_today_progress_to_history(state)
    review = build_mission_review(state)
    return format_mission_review_mobile_text(review, final=final)


def show_daily_tasks_window():
    state = load_today_task_state()

    window = tk.Toplevel(root)
    window.title("Daily Tasks")
    window.geometry("640x820")
    window.configure(bg="#111111")
    window.transient(root)

    tk.Label(
        window,
        text="Daily Tasks",
        font=("Segoe UI", 20, "bold"),
        bg="#111111",
        fg="#f2f2f2"
    ).pack(anchor="w", padx=18, pady=(18, 4))

    subtitle_var = tk.StringVar(value="Choose location and energy. Log effort. Bonus Round opens after all minimums are met.")
    tk.Label(
        window,
        textvariable=subtitle_var,
        font=("Segoe UI", 9),
        bg="#111111",
        fg="#aaaaaa",
        wraplength=500,
        justify="left"
    ).pack(anchor="w", padx=18, pady=(0, 8))

    progress_var = tk.StringVar()
    next_move_var = tk.StringVar()

    top_card = tk.Frame(window, bg="#191919", relief="solid", bd=1)
    top_card.pack(fill="x", padx=18, pady=(0, 12))

    tk.Label(
        top_card,
        textvariable=progress_var,
        font=("Consolas", 12, "bold"),
        bg="#191919",
        fg="#f2f2f2",
        anchor="w"
    ).pack(fill="x", padx=14, pady=(10, 2))

    tk.Label(
        top_card,
        textvariable=next_move_var,
        font=("Segoe UI", 9),
        bg="#191919",
        fg="#8bd3ff",
        anchor="w"
    ).pack(fill="x", padx=14, pady=(0, 10))

    location_var = tk.StringVar(value=state.get("location") or "Work")
    energy_var = tk.StringVar(value=normalize_energy(state.get("energy") or "Normal"))

    setup_frame = tk.Frame(window, bg="#191919", relief="solid", bd=1)
    setup_frame.pack(fill="x", padx=18, pady=(0, 12))

    tk.Label(setup_frame, text="START DAY SETUP", font=("Segoe UI", 11, "bold"), bg="#191919", fg="#8bd3ff").pack(anchor="w", padx=14, pady=(12, 8))

    controls = tk.Frame(setup_frame, bg="#191919")
    controls.pack(fill="x", padx=14, pady=(0, 12))
    controls.columnconfigure(0, weight=1)
    controls.columnconfigure(1, weight=1)

    tk.Label(controls, text="Location", font=("Segoe UI", 9, "bold"), bg="#191919", fg="#e6e6e6").grid(row=0, column=0, sticky="w")
    tk.Label(controls, text="Energy", font=("Segoe UI", 9, "bold"), bg="#191919", fg="#e6e6e6").grid(row=0, column=1, sticky="w", padx=(18, 0))

    tk.OptionMenu(controls, location_var, *LOCATION_OPTIONS).grid(row=1, column=0, sticky="ew", pady=(4, 0))
    tk.OptionMenu(controls, energy_var, *ENERGY_OPTIONS).grid(row=1, column=1, sticky="ew", padx=(18, 0), pady=(4, 0))

    task_frame = tk.Frame(window, bg="#0b0b0b", relief="solid", bd=1)
    task_frame.pack(fill="both", expand=True, padx=18, pady=(0, 12))

    bonus_frame = tk.Frame(window, bg="#15131f", relief="solid", bd=1)
    bonus_text_var = tk.StringVar(value="")

    def start_bonus_timer_window(bonus):
        """Open a tiny countdown for the extra block, then let the user log the upgrade."""
        current_duration = normalize_task_duration(bonus["canonical"], bonus.get("duration", 0))
        next_duration = normalize_task_duration(bonus["canonical"], bonus.get("next_duration", 0))
        minutes_needed = max(next_duration - current_duration, 10)
        total_seconds = minutes_needed * 60
        remaining_seconds = tk.IntVar(value=total_seconds)
        running = tk.BooleanVar(value=True)

        timer_window = tk.Toplevel(window)
        timer_window.title("Bonus Round Timer")
        timer_window.geometry("420x300")
        timer_window.configure(bg="#111111")
        timer_window.transient(window)

        tk.Label(
            timer_window,
            text="Bonus Round",
            font=("Segoe UI", 18, "bold"),
            bg="#111111",
            fg="#d6b3ff"
        ).pack(anchor="w", padx=18, pady=(18, 4))

        tk.Label(
            timer_window,
            text=f"{bonus['display']} → {TIER_NAMES.get(bonus['next_tier'], 'Next Tier')}",
            font=("Segoe UI", 12, "bold"),
            bg="#111111",
            fg="#f2f2f2"
        ).pack(anchor="w", padx=18, pady=(0, 4))

        tk.Label(
            timer_window,
            text=f"Extra block: {minutes_needed} minutes  •  Reward: +{bonus['xp_gain']} XP",
            font=("Segoe UI", 10, "bold"),
            bg="#111111",
            fg="#8bd3ff"
        ).pack(anchor="w", padx=18, pady=(0, 10))

        timer_text_var = tk.StringVar(value="")
        tk.Label(
            timer_window,
            textvariable=timer_text_var,
            font=("Consolas", 32, "bold"),
            bg="#0b0b0b",
            fg="#f2f2f2",
            relief="solid",
            bd=1,
            width=10
        ).pack(padx=18, pady=(0, 12), ipady=8)

        reason_label = tk.Label(
            timer_window,
            text=bonus.get("reason", "This is the best bonus target right now."),
            font=("Segoe UI", 9),
            bg="#111111",
            fg="#aaaaaa",
            wraplength=370,
            justify="left"
        )
        reason_label.pack(anchor="w", padx=18, pady=(0, 12))

        def format_seconds(value):
            value = max(int(value), 0)
            minutes = value // 60
            seconds = value % 60
            return f"{minutes:02d}:{seconds:02d}"

        def mark_bonus_complete():
            duration_vars_by_task[bonus["canonical"]].set(next_duration)
            state = collect_window_state()
            save_today_task_state(state)
            record = save_today_progress_to_history(state)
            refresh_task_styles()
            refresh_brain_preview("Bonus Round completed")
            insert_chat_line(
                "Companion",
                f"BONUS ROUND COMPLETE\n\n{bonus['display']} upgraded to {TIER_NAMES.get(bonus['next_tier'], 'Next Tier')}.\nToday EXP: {record.get('xp_earned', 0)}/{record.get('xp_possible', get_max_daily_xp())} XP.",
                "companion"
            )
            timer_window.destroy()

        def tick():
            timer_text_var.set(format_seconds(remaining_seconds.get()))
            if not running.get():
                return
            if remaining_seconds.get() <= 0:
                running.set(False)
                timer_text_var.set("DONE")
                insert_chat_line("Companion", f"Bonus timer finished for {bonus['display']}. Hit Mark Complete if the rep is done.", "companion")
                return
            remaining_seconds.set(remaining_seconds.get() - 1)
            timer_window.after(1000, tick)

        button_row = tk.Frame(timer_window, bg="#111111")
        button_row.pack(fill="x", padx=18, pady=(0, 16))

        def toggle_pause():
            running.set(not running.get())
            pause_button.configure(text="Pause" if running.get() else "Resume")
            if running.get():
                tick()

        pause_button = tk.Button(
            button_row,
            text="Pause",
            font=("Segoe UI", 9, "bold"),
            bg="#333333",
            fg="white",
            command=toggle_pause,
            width=10
        )
        pause_button.pack(side="left", ipady=5)

        tk.Button(
            button_row,
            text="Mark Bonus Complete",
            font=("Segoe UI", 9, "bold"),
            bg="#5b4bb7",
            fg="white",
            command=mark_bonus_complete,
            width=22
        ).pack(side="right", ipady=5)

        tick()

    def start_bonus_round_from_card():
        live_state = current_state_snapshot()
        bonus = get_bonus_round_recommendation(live_state)
        if not bonus:
            insert_chat_line("Companion", "Bonus board is already maxed. Full Mastery board today.", "companion")
            return

        opened = open_task_link(bonus["canonical"])
        open_note = "Opened the tool." if opened else "No direct tool link set, but the target is chosen."
        current_duration = normalize_task_duration(bonus["canonical"], bonus.get("duration", 0))
        minutes_needed = max(normalize_task_duration(bonus["canonical"], bonus["next_duration"]) - current_duration, 10)
        insert_chat_line(
            "Companion",
            f"BONUS ROUND STARTED\n\nTarget: {bonus['display']} → {TIER_NAMES.get(bonus['next_tier'], 'Next Tier')} ({DURATION_LABELS.get(bonus['next_duration'], str(bonus['next_duration']) + 'm')})\nExtra timer: {minutes_needed} minutes\nReward: +{bonus['xp_gain']} XP\n\nReason: {bonus['reason']}\n\n{open_note}",
            "companion"
        )
        start_bonus_timer_window(bonus)

    tk.Label(
        bonus_frame,
        text="BONUS ROUND AVAILABLE",
        font=("Segoe UI", 10, "bold"),
        bg="#15131f",
        fg="#d6b3ff",
        anchor="w"
    ).pack(fill="x", padx=14, pady=(8, 2))

    tk.Label(
        bonus_frame,
        textvariable=bonus_text_var,
        font=("Segoe UI", 9, "bold"),
        bg="#15131f",
        fg="#f2f2f2",
        anchor="w",
        justify="left",
        wraplength=500
    ).pack(fill="x", padx=14, pady=(0, 8))

    tk.Button(
        bonus_frame,
        text="Start Bonus Round Timer",
        font=("Segoe UI", 9, "bold"),
        bg="#5b4bb7",
        fg="white",
        command=start_bonus_round_from_card
    ).pack(fill="x", padx=14, pady=(0, 10), ipady=4)

    def refresh_bonus_card(live_state):
        snapshot = build_today_progress_snapshot(live_state)
        bonus = snapshot.get("bonus")
        if snapshot.get("all_minimums_met") and bonus:
            bonus_text_var.set(
                f"Recommended: {bonus['display']} → {TIER_NAMES.get(bonus['next_tier'], 'Next Tier')} "
                f"({DURATION_LABELS.get(bonus['next_duration'], str(bonus['next_duration']) + 'm')})\n"
                f"Reward: +{bonus['xp_gain']} XP\n"
                f"Reason: {bonus['reason']}"
            )
            if not bonus_frame.winfo_ismapped():
                bonus_frame.pack(fill="x", padx=18, pady=(0, 12), before=buttons)
        else:
            if bonus_frame.winfo_ismapped():
                bonus_frame.pack_forget()

    normal_font = ("Segoe UI", 12)
    done_font = ("Segoe UI", 12, "overstrike")
    duration_vars_by_task = {}
    label_widgets_by_task = {}
    pill_widgets_by_task = {}
    xp_widgets_by_task = {}

    save_button = None

    def current_state_snapshot():
        durations = {k: normalize_task_duration(k, v.get()) for k, v in duration_vars_by_task.items()}
        return {
            "tasks": {k: minutes > 0 for k, minutes in durations.items()},
            "durations": durations,
            "energy": normalize_energy(energy_var.get()),
            "location": normalize_location(location_var.get()),
        }

    def refresh_task_styles():
        selected_energy = normalize_energy(energy_var.get())
        for task in DAILY_TASKS:
            canonical = task["canonical"]
            duration = normalize_duration(duration_vars_by_task[canonical].get())
            done = duration > 0
            label_widgets_by_task[canonical].configure(
                text=task["display"],
                font=done_font if done else normal_font,
                fg="#777777" if done else "#f2f2f2"
            )
            if done:
                xp_text = f"{format_task_tier(canonical, duration)}  +{get_task_xp(canonical, duration)} XP"
            else:
                xp_text = get_task_minimum(canonical, selected_energy)
            tier = get_task_tier(canonical, duration)
            tier_color = {"minimum": "#74c476", "growth": "#8bd3ff", "mastery": "#d6b3ff", "none": "#aaaaaa"}.get(tier, "#aaaaaa")
            xp_widgets_by_task[canonical].configure(text=xp_text, fg=tier_color)

            for minutes, pill in pill_widgets_by_task[canonical].items():
                selected = duration == minutes
                pill.configure(
                    bg="#5b4bb7" if selected else "#191919",
                    fg="white" if selected else "#e6e6e6",
                    relief="sunken" if selected else "raised"
                )

        live_state = current_state_snapshot()
        snapshot = build_today_progress_snapshot(live_state)
        if save_button:
            save_button.configure(text="Save Progress")
        progress_var.set(f"TODAY EXP  {snapshot['bar']}  {snapshot['xp_earned']}/{snapshot['xp_total']} XP")
        next_move_var.set(
            f"Minimums: {snapshot['minimums_met']}/{snapshot['total']}  •  "
            f"Masteries: {snapshot['masteries']}/{snapshot['total']}  •  "
            f"Bonus XP left: {snapshot['bonus_xp_remaining']}  •  {snapshot['next_move']}"
        )
        refresh_bonus_card(live_state)
        subtitle_var.set(f"{normalize_location(location_var.get())} / {selected_energy} energy — tap an oval to log effort.")

    def set_duration(canonical, minutes):
        current = normalize_duration(duration_vars_by_task[canonical].get())
        # Tap the selected oval again to clear it.
        duration_vars_by_task[canonical].set(0 if current == minutes else minutes)
        refresh_task_styles()

    def open_from_task_label(canonical):
        if open_task_link(canonical):
            insert_chat_line("Companion", f"Opened {get_daily_task_display_name(canonical)}.", "companion")
        else:
            insert_chat_line("Companion", f"No direct link is set for {get_daily_task_display_name(canonical)} yet.", "companion")

    for task in DAILY_TASKS:
        canonical = task["canonical"]
        duration_vars_by_task[canonical] = tk.IntVar(value=get_state_duration(state, canonical))

        row = tk.Frame(task_frame, bg="#0b0b0b")
        row.pack(fill="x", padx=12, pady=7)
        row.columnconfigure(0, weight=1)

        left_box = tk.Frame(row, bg="#0b0b0b")
        left_box.grid(row=0, column=0, sticky="ew")

        label = tk.Label(
            left_box,
            text=task["display"],
            font=normal_font,
            bg="#0b0b0b",
            fg="#f2f2f2",
            anchor="w",
            padx=4,
            pady=2,
            justify="left"
        )
        label.pack(side="left")
        if get_task_link(canonical) or canonical == "Complete Workout":
            label.configure(cursor="hand2")
            label.bind("<Button-1>", lambda event, c=canonical: open_from_task_label(c))

        xp_label = tk.Label(
            left_box,
            text="",
            font=("Segoe UI", 8),
            bg="#0b0b0b",
            fg="#aaaaaa",
            padx=8,
            pady=2,
            anchor="w"
        )
        xp_label.pack(side="left")

        pill_box = tk.Frame(row, bg="#0b0b0b")
        pill_box.grid(row=0, column=1, sticky="e", padx=(6, 0))

        pill_widgets_by_task[canonical] = {}
        for minutes in get_duration_options(canonical):
            pill = tk.Button(
                pill_box,
                text=DURATION_LABELS[minutes],
                font=("Segoe UI", 9, "bold"),
                bg="#191919",
                fg="#e6e6e6",
                activebackground="#5b4bb7",
                activeforeground="white",
                command=lambda c=canonical, m=minutes: set_duration(c, m),
                width=5,
                cursor="hand2"
            )
            pill.pack(side="left", padx=2, ipady=2)
            pill_widgets_by_task[canonical][minutes] = pill

        label_widgets_by_task[canonical] = label
        xp_widgets_by_task[canonical] = xp_label

    def start_day_setup():
        state = load_today_task_state()
        state["location"] = normalize_location(location_var.get())
        state["energy"] = normalize_energy(energy_var.get())
        save_today_task_state(state)
        refresh_task_styles()
        insert_chat_line(
            "Companion",
            f"Start day set: {state['location']} / {state['energy']} energy. Duration buttons are ready." + get_start_day_gap_prompt(),
            "companion"
        )

    tk.Button(
        setup_frame,
        text="Start Day / Update Mode",
        font=("Segoe UI", 10, "bold"),
        bg="#5b4bb7",
        fg="white",
        command=start_day_setup
    ).pack(fill="x", padx=14, pady=(0, 14), ipady=5)

    def collect_window_state():
        state = load_today_task_state()
        state["location"] = normalize_location(location_var.get())
        state["energy"] = normalize_energy(energy_var.get())
        state["durations"] = {canonical: normalize_task_duration(canonical, var.get()) for canonical, var in duration_vars_by_task.items()}
        state["tasks"] = {canonical: minutes > 0 for canonical, minutes in state["durations"].items()}
        return state

    def save_from_window(show_message=True):
        state = collect_window_state()
        save_today_task_state(state)
        record = save_today_progress_to_history(state)
        refresh_brain_preview("Daily Tasks saved")
        if show_message:
            response = format_today_tasks_status(state, title="DAILY TASKS SAVED")
            insert_chat_line("Companion", response, "companion")
            enqueue_voice(f"Saved progress. {record.get('xp_earned', 0)} XP earned today.")
        refresh_task_styles()
        return state, record

    def show_mission_review(review, state):
        review_window = tk.Toplevel(window)
        review_window.title("Mission Review")
        review_window.geometry("470x430")
        review_window.configure(bg="#111111")
        review_window.transient(window)
        review_window.grab_set()

        status_colors = {
            "MISSION COMPLETE": "#74c476",
            "SOLID DAY": "#8bd3ff",
            "RECOVERY DAY": "#ffd166",
            "MORE IN THE TANK": "#ffd166",
            "WARNING": "#ff6b6b",
        }

        tk.Label(
            review_window,
            text="Mission Review",
            font=("Segoe UI", 18, "bold"),
            bg="#111111",
            fg="#f2f2f2"
        ).pack(anchor="w", padx=18, pady=(18, 4))

        tk.Label(
            review_window,
            text=review["status"],
            font=("Segoe UI", 12, "bold"),
            bg="#111111",
            fg=status_colors.get(review["status"], "#f2f2f2")
        ).pack(anchor="w", padx=18, pady=(0, 10))

        text_box = scrolledtext.ScrolledText(
            review_window,
            wrap=tk.WORD,
            font=("Segoe UI", 10),
            bg="#0b0b0b",
            fg="#f2f2f2",
            relief="solid",
            bd=1,
            padx=12,
            pady=10,
            height=14
        )
        text_box.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        text_box.insert(tk.END, format_mission_review_text(review))
        text_box.configure(state="disabled")

        button_row = tk.Frame(review_window, bg="#111111")
        button_row.pack(fill="x", padx=18, pady=(0, 16))

        def complete_anyway():
            state["day_closed"] = True
            save_today_task_state(state)
            record = save_today_progress_to_history(state)
            refresh_brain_preview("Day completed")
            final_message = format_mission_review_mobile_text(review, final=True)
            insert_chat_line("Companion", final_message, "companion")
            enqueue_voice(pick_companion_line(review, final=True))
            refresh_task_styles()
            review_window.destroy()

        tk.Button(
            button_row,
            text="Go Back",
            font=("Segoe UI", 10, "bold"),
            bg="#333333",
            fg="white",
            command=review_window.destroy,
            width=12
        ).pack(side="left", ipady=5)

        tk.Button(
            button_row,
            text="Complete Day",
            font=("Segoe UI", 10, "bold"),
            bg="#5b4bb7",
            fg="white",
            command=complete_anyway,
            width=18
        ).pack(side="right", ipady=5)

    def complete_day_from_window():
        state, _ = save_from_window(show_message=False)
        review = build_mission_review(state)
        show_mission_review(review, state)

    buttons = tk.Frame(window, bg="#111111")
    buttons.pack(fill="x", padx=18, pady=(0, 16))

    save_button = tk.Button(
        buttons,
        text="Save Progress",
        font=("Segoe UI", 10, "bold"),
        bg="#5b4bb7",
        fg="white",
        command=save_from_window,
        width=15
    )
    save_button.pack(side="left", ipady=6)

    tk.Button(
        buttons,
        text="Complete Day",
        font=("Segoe UI", 10, "bold"),
        bg="#704214",
        fg="white",
        command=complete_day_from_window,
        width=15
    ).pack(side="left", padx=(8, 0), ipady=6)

    tk.Button(
        buttons,
        text="Close",
        font=("Segoe UI", 10, "bold"),
        bg="#333333",
        fg="white",
        command=window.destroy,
        width=12
    ).pack(side="right", ipady=6)

    refresh_task_styles()

# -----------------------------
# VOICE QUEUE
# -----------------------------
def set_voice_enabled(enabled):
    """Turn voice mode on/off without breaking the app if pyttsx3 is missing."""
    global VOICE_ENABLED
    VOICE_ENABLED = bool(enabled)

    if VOICE_ENABLED:
        start_voice_worker()

    update_voice_controls()


def start_voice_worker():
    global voice_worker_started
    with voice_lock:
        if voice_worker_started:
            return
        thread = threading.Thread(target=voice_worker_loop, daemon=True)
        thread.start()
        voice_worker_started = True


def voice_worker_loop():
    global voice_engine
    try:
        import pyttsx3
        voice_engine = pyttsx3.init()
    except Exception:
        voice_engine = None

    while True:
        text = voice_queue.get()
        if text == "__STOP__":
            continue

        if not VOICE_ENABLED or not text:
            continue

        if voice_engine is None:
            # Voice package missing or failed. Keep app alive silently.
            continue

        try:
            voice_engine.say(text)
            voice_engine.runAndWait()
        except Exception:
            pass


def prepare_text_for_voice(text):
    profile = load_user_profile()
    max_chars = int(profile.get("voice", {}).get("max_spoken_characters", 650) or 650)
    cleaned = str(text or "")
    cleaned = re.sub(r"[✓□•─]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_chars]


def enqueue_voice(text):
    if not VOICE_ENABLED:
        return
    start_voice_worker()
    voice_queue.put(prepare_text_for_voice(text))


def clear_voice_queue():
    while not voice_queue.empty():
        try:
            voice_queue.get_nowait()
        except Exception:
            break


def stop_voice():
    """Stop current speech if possible, clear pending speech, and turn voice mode off."""
    global VOICE_ENABLED
    VOICE_ENABLED = False
    clear_voice_queue()

    # Wake the worker if it is waiting, and try to interrupt pyttsx3 if it is talking.
    try:
        voice_queue.put_nowait("__STOP__")
    except Exception:
        pass

    try:
        if voice_engine is not None:
            voice_engine.stop()
    except Exception:
        pass

    update_voice_controls()


def toggle_voice():
    """Single button behavior: Start Voice when off, Stop Voice when on."""
    if VOICE_ENABLED:
        stop_voice()
    else:
        set_voice_enabled(True)


def get_voice_status_text():
    if not VOICE_ENABLED:
        return "Voice: OFF"
    if voice_engine is None and voice_worker_started:
        return "Voice: ON, but speech engine not ready / pyttsx3 missing"
    return "Voice: ON"


def update_voice_controls():
    """Refresh voice UI safely. This function is called before widgets exist too."""
    icon = "🔊" if VOICE_ENABLED else "🔇"
    tooltip = get_voice_status_text()

    try:
        voice_var.set(VOICE_ENABLED)
    except Exception:
        pass

    # Old big-button support, kept so older layouts do not crash.
    try:
        voice_toggle_button.configure(text="Stop Voice" if VOICE_ENABLED else "Start Voice")
    except Exception:
        pass

    # New compact speaker button beside the message box.
    try:
        speaker_button.configure(text=icon, bg="#3a2d12" if VOICE_ENABLED else "#333333")
    except Exception:
        pass

    try:
        voice_status_var.set(tooltip)
    except Exception:
        pass

# -----------------------------
# GUI
# -----------------------------
def clean_message(message):
    """Make AI/user text easier to read in the chat window."""
    message = str(message).strip()

    # Normalize excessive blank lines without destroying intentional paragraphs.
    message = re.sub(r"\n{3,}", "\n\n", message)

    # If Ollama returns one giant line with sentence spacing, keep it readable.
    message = re.sub(r"(?<=[.!?])\s+(?=[A-Z])", "\n", message)

    return message


def insert_chat_line(sender, message, tag):
    """Insert a clean chat block instead of one giant wall of text."""
    message = clean_message(message)

    sender_upper = sender.upper()
    separator = "─" * 76

    chat_area.configure(state="normal")

    # Add breathing room between chat blocks.
    if chat_area.index("end-1c") != "1.0":
        chat_area.insert(tk.END, f"\n{separator}\n", "separator")

    chat_area.insert(tk.END, f"{sender_upper}\n", f"{tag}_header")
    chat_area.insert(tk.END, f"{message}\n", tag)

    chat_area.configure(state="disabled")
    chat_area.see(tk.END)


def send_message():
    user_input = user_entry.get().strip()
    if not user_input:
        return

    insert_chat_line("You", user_input, "user")
    user_entry.delete(0, tk.END)
    root.update()

    # Task commands happen before Ollama so daily progress is instant and tablet-friendly.
    if is_backup_request(user_input):
        response = backup_now(show_popup=False)
        insert_chat_line("Companion", response, "companion")
    elif is_what_now_request(user_input):
        response = format_what_now_answer()
        insert_chat_line("Companion", response, "companion")
    elif is_max_reps_request(user_input):
        response = format_max_reps_answer(user_input)
        insert_chat_line("Companion", response, "companion")
    elif is_workout_log_request(user_input):
        response = format_workout_log_answer()
        insert_chat_line("Companion", response, "companion")
    elif is_backfill_logging_message(user_input):
        date_key = parse_backfill_date(user_input)
        detected, duration, record = update_history_for_date_from_text(date_key, user_input)
        response = format_backfill_response(date_key, detected, duration, record)
        insert_chat_line("Companion", response, "companion")
    elif is_finish_day_request(user_input):
        response = handle_day_complete_command(final=True)
        insert_chat_line("Companion", response, "companion")
    elif is_day_complete_request(user_input):
        response = handle_day_complete_command(final=False)
        insert_chat_line("Companion", response, "companion")
    elif is_task_display_request(user_input):
        response = format_today_tasks_status(load_today_task_state())
        insert_chat_line("Companion", response, "companion")
        show_daily_tasks_window()
    elif is_task_start_request(user_input):
        response = handle_task_start_request(user_input)
        insert_chat_line("Companion", response, "companion")
    elif is_task_logging_message(user_input):
        detected, state = update_today_tasks_from_text(user_input)
        duration = detect_duration_from_text(user_input)
        logged_names = ", ".join(get_daily_task_display_name(task) for task in detected)
        duration_label = DURATION_LABELS.get(duration, f"{duration}m")
        response = f"Logged: {logged_names} — {duration_label}.\n\n" + format_today_tasks_status(state, title="UPDATED DAILY TASKS")
        insert_chat_line("Companion", response, "companion")
    else:
        # Smart routing: factual/rule/analysis questions are answered by Python.
        # Coaching/personality questions still go to Ollama.
        response = get_routed_response(user_input)
        if response is None:
            response = chat_with_ollama(user_input)
        insert_chat_line("Companion", response, "companion")

    enqueue_voice(response)

    # Save both sides after the response is generated.
    # This makes the NEXT question aware of what was just said.
    add_to_conversation_history("User", user_input)
    add_to_conversation_history("Companion", response)

    refresh_brain_preview(user_input)


def morning_briefing():
    """Command-center briefing: metrics first, small Ollama note second."""
    quotes = load_quotes()
    quote = random.choice(quotes) if quotes else "Momentum is recovery."

    packet = build_morning_briefing_packet()
    companion_note = get_morning_companion_note(packet, quote)
    response = format_morning_briefing(packet, companion_note)

    insert_chat_line("Morning Briefing", response, "companion")
    enqueue_voice(response)

    add_to_conversation_history("User", "Morning Briefing requested")
    add_to_conversation_history("Companion", response)

    refresh_brain_preview("Morning Briefing requested")


def refresh_brain_preview(user_input=""):
    brain_preview.delete("1.0", tk.END)
    brain_preview.insert(tk.END, build_brain_summary(user_input))


def test_connection():
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": "Say online.", "stream": False},
            timeout=10
        )
        response.raise_for_status()
        messagebox.showinfo("Ollama Test", "Connection worked. Model responded.")
    except Exception:
        messagebox.showerror("Ollama Test Failed", "Could not reach Ollama. Try: ollama serve")


# Create user_profile.json on first run so the companion has stable settings to read.
load_user_profile()

root = tk.Tk()
root.title("Momentum Companion Builder Branch v19 Infrastructure")
root.geometry("1180x720")
root.configure(bg="#111111")

header = tk.Frame(root, bg="#111111")
header.pack(fill="x", padx=16, pady=(10, 6))

tk.Label(
    header,
    text="Momentum Companion Builder Branch v19 Infrastructure",
    font=("Segoe UI", 20, "bold"),
    bg="#111111",
    fg="#e6e6e6"
).pack(anchor="w")

tk.Label(
    header,
    text="Builder Branch v19: backups, Home/Work workout sessions, 2 AM rollover, workout tracker, backfill, alerts, tiered EXP + bonus rounds.",
    font=("Segoe UI", 10),
    bg="#111111",
    fg="#aaaaaa"
).pack(anchor="w", pady=(2, 0))

main = tk.Frame(root, bg="#111111")
main.pack(fill="both", expand=True, padx=16, pady=(0, 12))
main.columnconfigure(0, weight=3)
main.columnconfigure(1, weight=2)
main.rowconfigure(0, weight=1)

left = tk.Frame(main, bg="#111111")
left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
left.rowconfigure(0, weight=1)
left.columnconfigure(0, weight=1)

chat_area = scrolledtext.ScrolledText(
    left,
    wrap=tk.WORD,
    font=("Segoe UI", 11),
    bg="#0b0b0b",
    fg="#f2f2f2",
    relief="solid",
    bd=1,
    padx=14,
    pady=12,
    spacing1=4,
    spacing2=3,
    spacing3=10
)
chat_area.grid(row=0, column=0, sticky="nsew")

# Chat formatting tags
chat_area.tag_config("separator", foreground="#333333", spacing1=8, spacing3=8)

chat_area.tag_config("user_header", foreground="#00d9ff", font=("Segoe UI", 9, "bold"), spacing1=8, spacing3=2)
chat_area.tag_config("user", foreground="#dff8ff", font=("Segoe UI", 11), lmargin1=10, lmargin2=10, spacing3=8)

chat_area.tag_config("companion_header", foreground="#ff6b6b", font=("Segoe UI", 9, "bold"), spacing1=8, spacing3=2)
chat_area.tag_config("companion", foreground="#ffecec", font=("Segoe UI", 11), lmargin1=10, lmargin2=10, spacing3=8)

chat_area.tag_config("system_header", foreground="#d6b3ff", font=("Segoe UI", 9, "bold"), spacing1=8, spacing3=2)
chat_area.tag_config("system", foreground="#eadcff", font=("Segoe UI", 11), lmargin1=10, lmargin2=10, spacing3=8)

chat_area.configure(state="disabled")

entry_frame = tk.Frame(left, bg="#111111")
entry_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
entry_frame.columnconfigure(0, weight=1)

user_entry = tk.Entry(entry_frame, font=("Segoe UI", 11), bg="#222222", fg="white", insertbackground="white")
user_entry.grid(row=0, column=0, sticky="ew", ipady=6)
user_entry.focus()

tk.Button(
    entry_frame,
    text="Send",
    font=("Segoe UI", 10, "bold"),
    bg="#002855",
    fg="white",
    command=send_message,
    width=10
).grid(row=0, column=1, padx=(8, 0), ipady=4)

voice_var = tk.BooleanVar(value=load_user_profile().get("voice", {}).get("enabled_by_default", False))
voice_status_var = tk.StringVar(value="Voice: OFF")

speaker_button = tk.Button(
    entry_frame,
    text="🔇",
    font=("Segoe UI", 13, "bold"),
    bg="#333333",
    fg="white",
    command=toggle_voice,
    width=3
)
speaker_button.grid(row=0, column=2, padx=(8, 0), ipady=2)

voice_status_label = tk.Label(
    entry_frame,
    textvariable=voice_status_var,
    font=("Segoe UI", 8),
    bg="#111111",
    fg="#aaaaaa"
)
voice_status_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 0))

right = tk.Frame(main, bg="#111111")
right.grid(row=0, column=1, sticky="nsew")
right.rowconfigure(8, weight=1)
right.columnconfigure(0, weight=1)

tk.Button(
    right,
    text="Daily Tasks",
    font=("Segoe UI", 10, "bold"),
    bg="#5b4bb7",
    fg="white",
    command=show_daily_tasks_window
).grid(row=0, column=0, sticky="ew", pady=(0, 7), ipady=6)

tk.Button(
    right,
    text="Morning Briefing",
    font=("Segoe UI", 10, "bold"),
    bg="#5b4bb7",
    fg="white",
    command=morning_briefing
).grid(row=1, column=0, sticky="ew", pady=(0, 7), ipady=6)

tk.Button(
    right,
    text="Refresh Brain Data",
    font=("Segoe UI", 10, "bold"),
    bg="#333333",
    fg="white",
    command=lambda: refresh_brain_preview("")
).grid(row=2, column=0, sticky="ew", pady=(0, 7), ipady=6)

tk.Button(
    right,
    text="Insights",
    font=("Segoe UI", 10, "bold"),
    bg="#5b4bb7",
    fg="white",
    command=show_insights_window
).grid(row=3, column=0, sticky="ew", pady=(0, 7), ipady=6)

tk.Button(
    right,
    text="Trends",
    font=("Segoe UI", 10, "bold"),
    bg="#5b4bb7",
    fg="white",
    command=show_trends_window
).grid(row=4, column=0, sticky="ew", pady=(0, 7), ipady=6)

tk.Button(
    right,
    text="Backup Data",
    font=("Segoe UI", 10, "bold"),
    bg="#704214",
    fg="white",
    command=lambda: insert_chat_line("Companion", backup_now(show_popup=True), "companion")
).grid(row=5, column=0, sticky="ew", pady=(0, 7), ipady=6)

tk.Button(
    right,
    text="Test Ollama Connection",
    font=("Segoe UI", 10, "bold"),
    bg="#333333",
    fg="white",
    command=test_connection
).grid(row=6, column=0, sticky="ew", pady=(0, 7), ipady=6)

set_voice_enabled(voice_var.get())

tk.Label(
    right,
    text="Live Brain Data Preview",
    font=("Segoe UI", 11, "bold"),
    bg="#111111",
    fg="#e6e6e6"
).grid(row=7, column=0, sticky="w", pady=(0, 5))

brain_preview = scrolledtext.ScrolledText(
    right,
    wrap=tk.WORD,
    font=("Consolas", 9),
    bg="#191919",
    fg="#e6e6e6",
    relief="solid",
    bd=1
)
brain_preview.grid(row=8, column=0, sticky="nsew")

chat_area.insert(tk.END, "Companion: Online. I can read your momentum data and answer direct questions first now.\\n\\n", "companion")
refresh_brain_preview()

root.bind("<Return>", lambda event: send_message())
root.mainloop()
