"""
progress.py
----------------
Persistence and analytics layer for the AI Learning Coach.

Responsibilities:
    1. Save/load each student's data (assessment history, roadmaps,
       activity log) to a simple JSON file on disk -- no database
       required, easy to swap out later.
    2. Record events: assessment completed, topic status changed,
       practice exercise attempted.
    3. Compute summaries (overall completion %, concept mastery over
       time, study streak) used by `ai_coach.recommend_next_step()` and
       by the dashboard UI in this file.

Data is stored under ./data/<student_id>.json so multiple students can
use the same app installation without clashing.

Usage (from app.py):

    from progress import (
        load_student_data, save_student_data, record_assessment,
        record_roadmap, record_topic_update, log_practice_attempt,
        get_progress_summary, render_progress_dashboard
    )
"""

import os
import json
from datetime import datetime, date
from typing import Any, Dict, List, Optional

import streamlit as st

DATA_DIR = os.getenv("COACH_DATA_DIR", "data")


# --------------------------------------------------------------------------
# Low-level storage
# --------------------------------------------------------------------------

def _student_file(student_id: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    safe_id = "".join(c for c in student_id if c.isalnum() or c in ("-", "_")).strip() or "default"
    return os.path.join(DATA_DIR, f"{safe_id}.json")


def _default_student_data(student_id: str) -> Dict[str, Any]:
    return {
        "student_id": student_id,
        "created_at": datetime.now().isoformat(),
        "assessments": [],       # list of assessment_report dicts (history)
        "roadmaps": {},          # {topic: roadmap_dict} - one active roadmap per topic
        "activity_log": [],      # list of {"date": "YYYY-MM-DD", "type": "...", "detail": "..."}
        "practice_attempts": [], # list of {"timestamp","topic","concept","is_correct"}
    }


def load_student_data(student_id: str) -> Dict[str, Any]:
    """Loads a student's saved data, creating a fresh profile if none exists."""
    path = _student_file(student_id)
    if not os.path.exists(path):
        data = _default_student_data(student_id)
        save_student_data(student_id, data)
        return data

    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            # Corrupt file safety net -- don't crash the app, start fresh.
            data = _default_student_data(student_id)
            save_student_data(student_id, data)
            return data


def save_student_data(student_id: str, data: Dict[str, Any]) -> None:
    """Persists a student's full data dict to disk."""
    path = _student_file(student_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _log(data: Dict[str, Any], activity_type: str, detail: str) -> None:
    data.setdefault("activity_log", []).append({
        "date": date.today().isoformat(),
        "timestamp": datetime.now().isoformat(),
        "type": activity_type,
        "detail": detail,
    })


# --------------------------------------------------------------------------
# Recording events (called from app.py as things happen)
# --------------------------------------------------------------------------

def record_assessment(student_id: str, assessment_report: Dict[str, Any]) -> None:
    """Appends a completed assessment to the student's history and saves."""
    data = load_student_data(student_id)
    data.setdefault("assessments", []).append(assessment_report)
    _log(
        data,
        "assessment_completed",
        f"{assessment_report.get('topic')} - {assessment_report.get('score_percentage')}%",
    )
    save_student_data(student_id, data)


def record_roadmap(student_id: str, roadmap: Dict[str, Any]) -> None:
    """Saves/overwrites the active roadmap for a given topic."""
    data = load_student_data(student_id)
    data.setdefault("roadmaps", {})[roadmap["topic"]] = roadmap
    _log(data, "roadmap_generated", roadmap["topic"])
    save_student_data(student_id, data)


def get_roadmap(student_id: str, topic: str) -> Optional[Dict[str, Any]]:
    """Fetches a previously saved roadmap for a topic, if one exists."""
    data = load_student_data(student_id)
    return data.get("roadmaps", {}).get(topic)


def record_topic_update(student_id: str, topic: str, topic_id: str, new_status: str) -> None:
    """
    Persists an updated roadmap (after `roadmap.update_topic_status()` has
    already mutated it in memory) and logs the change.
    """
    data = load_student_data(student_id)
    if topic in data.get("roadmaps", {}):
        # The in-memory roadmap object (already mutated by roadmap.py) is
        # the source of truth; app.py should pass the updated roadmap in
        # via record_roadmap() right after mutating it. This helper just
        # logs the change for the activity feed / streak tracking.
        pass
    _log(data, "topic_status_changed", f"{topic}::{topic_id} -> {new_status}")
    save_student_data(student_id, data)


def log_practice_attempt(
    student_id: str,
    topic: str,
    concept: str,
    is_correct: bool,
) -> None:
    """Logs a practice-exercise attempt for later analytics."""
    data = load_student_data(student_id)
    data.setdefault("practice_attempts", []).append({
        "timestamp": datetime.now().isoformat(),
        "topic": topic,
        "concept": concept,
        "is_correct": is_correct,
    })
    _log(data, "practice_attempt", f"{topic}::{concept} -> {'correct' if is_correct else 'retry'}")
    save_student_data(student_id, data)


# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------

def _calculate_streak(activity_log: List[Dict[str, Any]]) -> int:
    """Counts consecutive days (including today) with at least one logged activity."""
    if not activity_log:
        return 0

    active_dates = sorted({datetime.fromisoformat(a["date"]).date() for a in activity_log}, reverse=True)
    today = date.today()

    streak = 0
    expected = today
    for d in active_dates:
        if d == expected:
            streak += 1
            expected = date.fromordinal(expected.toordinal() - 1)
        elif d < expected:
            break
    return streak


def get_progress_summary(student_id: str) -> Dict[str, Any]:
    """
    Returns an overall summary used by the dashboard and by
    `ai_coach.recommend_next_step()`:
        {
            "total_assessments": int,
            "topics_in_progress": [str, ...],
            "average_score": float,
            "concept_mastery": {concept: avg_score, ...},
            "practice_accuracy": float,
            "current_streak_days": int,
        }
    """
    data = load_student_data(student_id)
    assessments = data.get("assessments", [])
    attempts = data.get("practice_attempts", [])

    average_score = (
        round(sum(a["score_percentage"] for a in assessments) / len(assessments), 1)
        if assessments else 0.0
    )

    concept_totals: Dict[str, List[float]] = {}
    for a in assessments:
        for concept, score in a.get("concept_scores", {}).items():
            concept_totals.setdefault(concept, []).append(score)
    concept_mastery = {c: round(sum(s) / len(s), 2) for c, s in concept_totals.items()}

    practice_accuracy = (
        round(sum(1 for p in attempts if p["is_correct"]) / len(attempts) * 100, 1)
        if attempts else 0.0
    )

    return {
        "total_assessments": len(assessments),
        "topics_in_progress": list(data.get("roadmaps", {}).keys()),
        "average_score": average_score,
        "concept_mastery": concept_mastery,
        "practice_accuracy": practice_accuracy,
        "current_streak_days": _calculate_streak(data.get("activity_log", [])),
    }


# --------------------------------------------------------------------------
# Streamlit dashboard
# --------------------------------------------------------------------------

def render_progress_dashboard(student_id: str) -> None:
    """Renders a full progress dashboard for the student."""
    from roadmap import calculate_roadmap_progress  # local import, avoids circularity

    data = load_student_data(student_id)
    summary = get_progress_summary(student_id)

    st.subheader("📊 Your Progress Dashboard")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Assessments Taken", summary["total_assessments"])
    col2.metric("Average Score", f"{summary['average_score']}%")
    col3.metric("Practice Accuracy", f"{summary['practice_accuracy']}%")
    col4.metric("🔥 Streak", f"{summary['current_streak_days']} day(s)")

    st.markdown("### Active Roadmaps")
    roadmaps = data.get("roadmaps", {})
    if not roadmaps:
        st.info("No active roadmap yet. Start with an assessment to generate one!")
    else:
        for topic, roadmap in roadmaps.items():
            stats = calculate_roadmap_progress(roadmap)
            st.markdown(f"**{topic}** ({roadmap.get('difficulty', '').title()})")
            st.progress(stats["percentage_complete"] / 100)
            st.caption(
                f"{stats['completed_topics']}/{stats['total_topics']} topics complete "
                f"({stats['percentage_complete']}%)"
            )

    if summary["concept_mastery"]:
        st.markdown("### Concept Mastery")
        chart_data = summary["concept_mastery"]
        st.bar_chart(chart_data)

        weak_concepts = [c for c, s in chart_data.items() if s < 0.5]
        if weak_concepts:
            st.warning(f"📌 Concepts that may need more review: {', '.join(weak_concepts)}")

    with st.expander("Recent activity"):
        recent = list(reversed(data.get("activity_log", [])))[:15]
        if not recent:
            st.caption("No activity logged yet.")
        for entry in recent:
            st.caption(f"🕒 {entry['timestamp'][:16].replace('T', ' ')} — {entry['type']}: {entry['detail']}")
