import tkinter as tk
from tkinter import scrolledtext, messagebox
import json
import random
import re
import requests
from pathlib import Path
from datetime import datetime, timedelta

# -----------------------------
# FILES / SETTINGS
# -----------------------------
HISTORY_FILE = Path("momentum_history.json")
QUOTES_FILE = Path("companion_quotes_sample.json")

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"

# Keeps the last few exchanges so follow-up questions feel natural.
CONVERSATION_MEMORY_LIMIT = 10
conversation_history = []

# Check Tickets is useful for work, but it should NOT be treated as a growth habit.
GROWTH_TASKS = [
    "Complete Workout",
    "Coding Core Task",
    "Networking / LinkedIn",
    "Spanish Review",
]

TASK_CATEGORIES = {
    "Complete Workout": "Physical",
    "Coding Core Task": "Career",
    "Networking / LinkedIn": "Career",
    "Spanish Review": "Learning",
}

TIME_RULES = {
    "networking": "10 minutes minimum, 20 minutes maximum. One comment or one connection is enough.",
    "linkedin": "10 minutes minimum, 20 minutes maximum. One comment or one connection is enough.",
    "coding": "10 minutes minimum on low energy, 25 minutes if you feel stable.",
    "spanish": "10 minutes minimum. One short review session is enough to keep the chain alive.",
    "workout": "20 to 30 minutes, unless energy is low. Low energy minimum is 10 minutes of movement.",
    "exercise": "20 to 30 minutes, unless energy is low. Low energy minimum is 10 minutes of movement.",
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
# ANALYSIS
# -----------------------------
def normalize_task_name(text):
    key = str(text).strip().lower()
    aliases = {
        "networking": "Networking / LinkedIn",
        "linkedin": "Networking / LinkedIn",
        "comment on one post": "Networking / LinkedIn",
        "networking / linkedin": "Networking / LinkedIn",
        "spanish review": "Spanish Review",
        "review spanish notes": "Spanish Review",
        "complete workout": "Complete Workout",
        "workout": "Complete Workout",
        "coding": "Coding Core Task",
        "coding task": "Coding Core Task",
        "coding core task": "Coding Core Task",
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
    end = max(max(dates), datetime.now().date())
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
        "inactive_days_recent": inactive_days,
        "missed_days_recent": missed_days,
        "recovery_days_recent": recovery_days,
        "average_recent_completion": calendar_avg_percent,
        "logged_session_average": logged_avg_percent,
        "recommended_move": recommended_move,
        "reason": reason,
    }


def build_brain_summary(user_input=""):
    brain = analyze_history()
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

IMPORTANT ANALYSIS RULES:
- Never treat "Check Tickets" as strongest habit, weakest habit, or a growth focus.
- Growth habits are Workout, Coding, Networking/LinkedIn, and Spanish.
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

    return f"""MOMENTUM ANALYSIS

Current State: {brain.get('current_state')}
Recent Calendar Average: {brain.get('average_recent_completion')}%
Logged Session Average: {brain.get('logged_session_average')}%

Strongest Habit: {brain.get('strongest_habit')}
Weakest Habit: {brain.get('weakest_habit')}

Recommended Move:
{brain.get('recommended_move')}

Reason:
{brain.get('reason')}""".strip()


def route_user_message(user_input):
    """Decide whether the answer should come from Python or Ollama."""
    text = user_input.lower().strip()

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

    # Smart routing: factual/rule/analysis questions are answered by Python.
    # Coaching/personality questions still go to Ollama.
    response = get_routed_response(user_input)
    if response is None:
        response = chat_with_ollama(user_input)

    insert_chat_line("Companion", response, "companion")

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


root = tk.Tk()
root.title("Momentum Companion Phase 1 Router Cleanup POC")
root.geometry("1180x720")
root.configure(bg="#111111")

header = tk.Frame(root, bg="#111111")
header.pack(fill="x", padx=16, pady=(10, 6))

tk.Label(
    header,
    text="Momentum Companion Phase 1 Router Cleanup POC",
    font=("Segoe UI", 20, "bold"),
    bg="#111111",
    fg="#e6e6e6"
).pack(anchor="w")

tk.Label(
    header,
    text="Phase 1 Cleanup: cleaner analysis output, instant rules/data, Ollama only when coaching is needed.",
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

right = tk.Frame(main, bg="#111111")
right.grid(row=0, column=1, sticky="nsew")
right.rowconfigure(6, weight=1)
right.columnconfigure(0, weight=1)

tk.Button(
    right,
    text="Morning Briefing",
    font=("Segoe UI", 10, "bold"),
    bg="#5b4bb7",
    fg="white",
    command=morning_briefing
).grid(row=0, column=0, sticky="ew", pady=(0, 7), ipady=6)

tk.Button(
    right,
    text="Refresh Brain Data",
    font=("Segoe UI", 10, "bold"),
    bg="#333333",
    fg="white",
    command=lambda: refresh_brain_preview("")
).grid(row=1, column=0, sticky="ew", pady=(0, 7), ipady=6)

tk.Button(
    right,
    text="Insights",
    font=("Segoe UI", 10, "bold"),
    bg="#5b4bb7",
    fg="white",
    command=show_insights_window
).grid(row=2, column=0, sticky="ew", pady=(0, 7), ipady=6)

tk.Button(
    right,
    text="Trends",
    font=("Segoe UI", 10, "bold"),
    bg="#5b4bb7",
    fg="white",
    command=show_trends_window
).grid(row=3, column=0, sticky="ew", pady=(0, 7), ipady=6)

tk.Button(
    right,
    text="Test Ollama Connection",
    font=("Segoe UI", 10, "bold"),
    bg="#333333",
    fg="white",
    command=test_connection
).grid(row=4, column=0, sticky="ew", pady=(0, 10), ipady=6)

tk.Label(
    right,
    text="Live Brain Data Preview",
    font=("Segoe UI", 11, "bold"),
    bg="#111111",
    fg="#e6e6e6"
).grid(row=5, column=0, sticky="w", pady=(0, 5))

brain_preview = scrolledtext.ScrolledText(
    right,
    wrap=tk.WORD,
    font=("Consolas", 9),
    bg="#191919",
    fg="#e6e6e6",
    relief="solid",
    bd=1
)
brain_preview.grid(row=6, column=0, sticky="nsew")

chat_area.insert(tk.END, "Companion: Online. I can read your momentum data and answer direct questions first now.\\n\\n", "companion")
refresh_brain_preview()

root.bind("<Return>", lambda event: send_message())
root.mainloop()
