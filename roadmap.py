"""
roadmap.py
----------------
Generates and manages the personalized learning roadmap for a student,
based on their assessment results (see assessment.py).

A roadmap is a structured, ordered set of modules -> topics that the
AI Learning Coach recommends the student work through. This module also
knows how to identify "what to focus on next" given the current progress
state, which `progress.py` and `ai_coach.py` build on top of.

Roadmap JSON schema:
{
    "topic": "Python Programming",
    "difficulty": "beginner",
    "generated_at": "2026-09-12T10:00:00",
    "overview": "short summary of the learning path",
    "modules": [
        {
            "id": "module_1",
            "title": "Python Fundamentals",
            "description": "...",
            "status": "not_started" | "in_progress" | "completed",
            "topics": [
                {
                    "id": "module_1_topic_1",
                    "name": "Variables & Data Types",
                    "status": "not_started" | "in_progress" | "completed",
                    "estimated_hours": 2,
                    "resources": ["...", "..."],
                    "practice_prompt": "short exercise description"
                }
            ]
        }
    ]
}

Usage (from app.py):

    from roadmap import generate_roadmap, render_roadmap_ui

    roadmap = generate_roadmap(topic, difficulty, assessment_result)
    render_roadmap_ui(roadmap)
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st

from ai_coach import call_llm_json

VALID_STATUSES = {"not_started", "in_progress", "completed"}


# --------------------------------------------------------------------------
# Roadmap generation
# --------------------------------------------------------------------------

def generate_roadmap(
    topic: str,
    difficulty: str,
    assessment_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generates a personalized learning roadmap for `topic`.

    If `assessment_result` (from assessment.py) is provided, the roadmap is
    tailored to the student's actual strengths/weaknesses and to the
    LLM-recommended starting level rather than just the requested one.
    """
    effective_level = difficulty
    weaknesses_note = ""
    strengths_note = ""

    if assessment_result:
        effective_level = assessment_result.get("recommended_starting_level", difficulty)
        weaknesses = assessment_result.get("weaknesses", [])
        strengths = assessment_result.get("strengths", [])
        if weaknesses:
            weaknesses_note = (
                f"The student showed weaker understanding in: {', '.join(weaknesses)}. "
                "Prioritize and reinforce these early in the roadmap."
            )
        if strengths:
            strengths_note = (
                f"The student already shows strength in: {', '.join(strengths)}. "
                "You can move faster through these or skip very basic coverage."
            )

    system_prompt = (
        "You are an expert learning-path designer and mentor. You design "
        "clear, well-sequenced, realistic learning roadmaps broken into "
        "modules and topics. You respond with STRICT valid JSON only, no "
        "markdown, no commentary."
    )

    user_prompt = f"""
Design a personalized learning roadmap for a student.

Topic: {topic}
Effective starting level: {effective_level}
{weaknesses_note}
{strengths_note}

Requirements:
- Create between 4 and 7 modules that progress logically from foundational
  to more advanced concepts, appropriate for the effective starting level.
- Each module must have 2 to 5 topics.
- Each topic needs: a clear "name", "estimated_hours" (realistic integer),
  2-3 short "resources" (types of resources to look for, e.g. "official
  docs section on X", "hands-on coding exercise", "short video tutorial" -
  do NOT invent fake URLs), and a "practice_prompt" describing a small
  hands-on exercise for that topic (describe the exercise only, never give
  the final answer/solution).
- Include a short 2-3 sentence "overview" of the overall learning path.
- All modules and topics must start with status "not_started".

Return ONLY valid JSON matching this schema:
{{
  "overview": "short overview text",
  "modules": [
    {{
      "id": "module_1",
      "title": "module title",
      "description": "1-2 sentence module description",
      "status": "not_started",
      "topics": [
        {{
          "id": "module_1_topic_1",
          "name": "topic name",
          "status": "not_started",
          "estimated_hours": 2,
          "resources": ["resource type 1", "resource type 2"],
          "practice_prompt": "short exercise description"
        }}
      ]
    }}
  ]
}}
"""

    roadmap_data = call_llm_json(system_prompt, user_prompt, temperature=0.6, max_tokens=4000)

    roadmap = {
        "topic": topic,
        "difficulty": effective_level,
        "generated_at": datetime.now().isoformat(),
        "overview": roadmap_data.get("overview", ""),
        "modules": roadmap_data.get("modules", []),
    }
    _validate_roadmap(roadmap)
    return roadmap


def _validate_roadmap(roadmap: Dict[str, Any]) -> None:
    """Defensive normalization in case the LLM omits some fields."""
    for m_idx, module in enumerate(roadmap.get("modules", [])):
        module.setdefault("id", f"module_{m_idx + 1}")
        module.setdefault("status", "not_started")
        for t_idx, topic in enumerate(module.get("topics", [])):
            topic.setdefault("id", f"{module['id']}_topic_{t_idx + 1}")
            topic.setdefault("status", "not_started")
            topic.setdefault("estimated_hours", 1)
            topic.setdefault("resources", [])


# --------------------------------------------------------------------------
# Roadmap navigation / progress helpers
# (used by progress.py and ai_coach.py to decide "what's next")
# --------------------------------------------------------------------------

def get_next_topic(roadmap: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Returns the next topic the student should focus on: the first topic
    that is not yet 'completed', walking modules in order.
    Returns None if the whole roadmap is completed.
    """
    for module in roadmap.get("modules", []):
        for topic in module.get("topics", []):
            if topic["status"] != "completed":
                return {**topic, "module_id": module["id"], "module_title": module["title"]}
    return None


def update_topic_status(roadmap: Dict[str, Any], topic_id: str, new_status: str) -> bool:
    """
    Updates a topic's status in-place and rolls the parent module's status
    up accordingly. Returns True if the topic was found and updated.
    """
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{new_status}'. Must be one of {VALID_STATUSES}")

    for module in roadmap.get("modules", []):
        for topic in module.get("topics", []):
            if topic["id"] == topic_id:
                topic["status"] = new_status
                _refresh_module_status(module)
                return True
    return False


def _refresh_module_status(module: Dict[str, Any]) -> None:
    statuses = [t["status"] for t in module.get("topics", [])]
    if statuses and all(s == "completed" for s in statuses):
        module["status"] = "completed"
    elif any(s in ("in_progress", "completed") for s in statuses):
        module["status"] = "in_progress"
    else:
        module["status"] = "not_started"


def calculate_roadmap_progress(roadmap: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns overall completion stats, used by progress.py for dashboards:
        {
            "total_topics": int,
            "completed_topics": int,
            "in_progress_topics": int,
            "percentage_complete": float
        }
    """
    all_topics = [t for m in roadmap.get("modules", []) for t in m.get("topics", [])]
    total = len(all_topics)
    completed = sum(1 for t in all_topics if t["status"] == "completed")
    in_progress = sum(1 for t in all_topics if t["status"] == "in_progress")
    percentage = round((completed / total) * 100, 1) if total else 0.0

    return {
        "total_topics": total,
        "completed_topics": completed,
        "in_progress_topics": in_progress,
        "percentage_complete": percentage,
    }


# --------------------------------------------------------------------------
# Streamlit UI
# --------------------------------------------------------------------------

def render_roadmap_ui(roadmap: Dict[str, Any]) -> None:
    """
    Renders the roadmap as an interactive Streamlit view: overview, overall
    progress bar, "what's next" callout, and expandable modules with a
    per-topic status selector.
    """
    st.subheader(f"🗺️ Your Learning Roadmap: {roadmap['topic']} ({roadmap['difficulty'].title()})")
    if roadmap.get("overview"):
        st.info(roadmap["overview"])

    stats = calculate_roadmap_progress(roadmap)
    st.progress(stats["percentage_complete"] / 100)
    st.caption(
        f"{stats['completed_topics']}/{stats['total_topics']} topics completed "
        f"({stats['percentage_complete']}%)"
    )

    next_topic = get_next_topic(roadmap)
    if next_topic:
        st.success(f"🎯 Recommended next: **{next_topic['name']}** (Module: {next_topic['module_title']})")
    else:
        st.balloons()
        st.success("🎉 You've completed the entire roadmap!")

    status_icon = {"not_started": "⚪", "in_progress": "🟡", "completed": "🟢"}
    status_options = ["not_started", "in_progress", "completed"]

    for module in roadmap.get("modules", []):
        icon = status_icon.get(module["status"], "⚪")
        with st.expander(f"{icon} {module['title']}", expanded=(module["status"] == "in_progress")):
            st.caption(module.get("description", ""))
            for topic in module.get("topics", []):
                t_col1, t_col2 = st.columns([4, 1])
                with t_col1:
                    st.markdown(f"**{topic['name']}** — ⏱ ~{topic.get('estimated_hours', 1)}h")
                    if topic.get("resources"):
                        st.caption("Resources: " + "; ".join(topic["resources"]))
                    if topic.get("practice_prompt"):
                        st.caption(f"🛠 Practice: {topic['practice_prompt']}")
                with t_col2:
                    new_status = st.selectbox(
                        "Status",
                        options=status_options,
                        index=status_options.index(topic["status"]),
                        key=f"status_{topic['id']}",
                        label_visibility="collapsed",
                    )
                    if new_status != topic["status"]:
                        update_topic_status(roadmap, topic["id"], new_status)
                        st.rerun()
                st.divider()
