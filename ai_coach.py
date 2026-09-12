"""
ai_coach.py
----------------
The core "brain" of the AI Learning Coach.

This module has two jobs:

1. LOW-LEVEL LLM ACCESS (shared across the whole project)
   `get_client()`, `call_llm_json()`, `call_llm_text()` are the single
   place that talks to Groq. `assessment.py` and `roadmap.py` import
   these instead of each keeping their own copy, so the API key, model
   name, and JSON-parsing logic only live in one place.

2. HIGH-LEVEL COACHING LOGIC
   - explain_concept(): gives a guided explanation of a topic, tuned to
     the student's level.
   - generate_practice_exercise(): creates a hands-on exercise (no
     solution attached) for the student to attempt.
   - evaluate_practice_submission(): reviews the student's attempt and
     gives feedback + hints -- WITHOUT just handing over the final
     answer, in line with the product's core philosophy.
   - chat_with_coach(): free-form Q&A grounded in the student's current
     roadmap/progress context.
   - recommend_next_step(): looks at the roadmap + progress history and
     tells the student what to focus on next and why.

Usage (from app.py):

    from ai_coach import (
        explain_concept, generate_practice_exercise,
        evaluate_practice_submission, chat_with_coach, recommend_next_step
    )
"""

import os
import json
import re
from typing import Any, Dict, List, Optional

import streamlit as st
from groq import Groq


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def _load_api_key() -> str:
    """Reads the Groq API key from env var first, then Streamlit secrets."""
    key = os.getenv("GROQ_API_KEY")
    if key:
        return key
    try:
        return st.secrets["GROQ_API_KEY"]
    except Exception:
        return ""


def get_client() -> Groq:
    """Lazily creates and caches a single Groq client for the whole app."""
    if "groq_client" not in st.session_state:
        api_key = _load_api_key()
        if not api_key:
            raise EnvironmentError(
                "GROQ_API_KEY not found. Set it as an environment variable "
                "or add it to .streamlit/secrets.toml, e.g.\n\n"
                'GROQ_API_KEY = "gsk_xxxxxxxx"'
            )
        st.session_state.groq_client = Groq(api_key=api_key)
    return st.session_state.groq_client


def _extract_json(raw_text: str) -> Any:
    """
    Extracts a JSON object/array from an LLM response that may be wrapped
    in markdown code fences or contain extra commentary around it.
    """
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, re.DOTALL)
    candidate = fence_match.group(1) if fence_match else raw_text

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = min((candidate.find(c) for c in "{[" if c in candidate), default=-1)
        end = max(candidate.rfind(c) for c in "}]")
        if start != -1 and end != -1:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError as e:
                raise ValueError(f"Could not parse LLM JSON output: {e}\nRaw: {raw_text[:500]}")
        raise ValueError(f"Could not parse LLM JSON output.\nRaw: {raw_text[:500]}")


def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.6,
    max_tokens: int = 3000,
) -> Any:
    """Calls Groq chat completion and parses the reply as JSON."""
    client = get_client()
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    raw_text = response.choices[0].message.content.strip()
    return _extract_json(raw_text)


def call_llm_text(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.6,
    max_tokens: int = 1500,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Calls Groq chat completion and returns plain text (for free-form
    explanations / chat, where forcing JSON would hurt output quality).
    `conversation_history` is an optional list of prior
    {"role": "user"/"assistant", "content": "..."} turns.
    """
    client = get_client()
    messages = [{"role": "system", "content": system_prompt}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_prompt})

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


# --------------------------------------------------------------------------
# Coaching philosophy (shared system prompt fragment)
# --------------------------------------------------------------------------

COACH_PERSONA = (
    "You are an encouraging, patient AI Learning Coach. Your goal is to "
    "help the student truly UNDERSTAND concepts and build skill through "
    "guided discovery -- not to just hand over exact final answers. "
    "When a student is stuck, you give hints, ask leading questions, and "
    "break problems into smaller steps before ever revealing a full "
    "solution. You adapt your language and pacing to the student's stated "
    "skill level."
)


# --------------------------------------------------------------------------
# Guided explanations
# --------------------------------------------------------------------------

def explain_concept(topic: str, concept: str, student_level: str) -> str:
    """
    Returns a guided, level-appropriate explanation of `concept` within
    the broader `topic`. Plain text (markdown-friendly), not JSON --
    explanations read better as natural prose.
    """
    system_prompt = COACH_PERSONA
    user_prompt = f"""
The student is learning: {topic}
Current skill level: {student_level}
Concept to explain: {concept}

Write a clear, friendly explanation of this concept for a student at this
level. Structure it with:
1. A one-line plain-language definition.
2. Why it matters / when it's used.
3. One small, simple illustrative example.
4. A short "check your understanding" question at the end (do not answer
   it yourself -- just pose it, to encourage active recall).

Keep it concise (roughly 150-250 words). Use markdown formatting.
"""
    return call_llm_text(system_prompt, user_prompt, temperature=0.5)


# --------------------------------------------------------------------------
# Practice exercises
# --------------------------------------------------------------------------

def generate_practice_exercise(topic: str, concept: str, difficulty: str) -> Dict[str, Any]:
    """
    Generates a hands-on practice exercise for `concept`.
    Returns:
        {
            "title": "...",
            "instructions": "...",
            "starter_code_or_template": "..." (optional, empty if not applicable),
            "hints": ["hint1", "hint2", "hint3"],   # progressively more revealing
            "success_criteria": "how the student can tell they got it right"
        }
    IMPORTANT: this never includes the final solution/answer.
    """
    system_prompt = (
        COACH_PERSONA
        + " You design small, focused practice exercises. You NEVER include "
        "the final solution or completed answer in the exercise itself -- "
        "only the problem, optional starter material, hints, and how the "
        "student can self-check. Respond with STRICT valid JSON only."
    )
    user_prompt = f"""
Topic: {topic}
Concept to practice: {concept}
Student level: {difficulty}

Create one focused practice exercise for this concept. Return ONLY JSON:
{{
  "title": "short exercise title",
  "instructions": "clear step-by-step task description (no solution)",
  "starter_code_or_template": "optional starter snippet or outline, empty string if not applicable",
  "hints": ["gentle first hint", "more specific second hint", "very specific third hint"],
  "success_criteria": "how the student can tell their solution works / is correct"
}}
"""
    exercise = call_llm_json(system_prompt, user_prompt, temperature=0.6)
    exercise.setdefault("hints", [])
    exercise.setdefault("starter_code_or_template", "")
    return exercise


def evaluate_practice_submission(
    exercise: Dict[str, Any],
    submission: str,
) -> Dict[str, Any]:
    """
    Reviews the student's attempt at `exercise` and returns constructive
    feedback -- guiding them toward the fix rather than dumping the
    correct answer, unless their submission is already correct.

    Returns:
        {
            "is_correct": bool,
            "feedback": "...",
            "next_hint": "..." (empty string if correct or no further hint needed),
            "encouragement": "..."
        }
    """
    system_prompt = (
        COACH_PERSONA
        + " You review a student's attempt at an exercise. If it is wrong "
        "or incomplete, explain WHAT is off conceptually and give ONE "
        "actionable hint to move them forward -- do not just give the "
        "corrected/final version of their work. If it is correct, confirm "
        "warmly and briefly explain why it works. Respond with STRICT "
        "valid JSON only."
    )
    user_prompt = f"""
Exercise title: {exercise.get('title')}
Exercise instructions: {exercise.get('instructions')}
Success criteria: {exercise.get('success_criteria')}

Student's submission:
{submission}

Return ONLY JSON:
{{
  "is_correct": true,
  "feedback": "conceptual feedback on their attempt",
  "next_hint": "one actionable next hint, empty string if not needed",
  "encouragement": "one short encouraging line"
}}
"""
    result = call_llm_json(system_prompt, user_prompt, temperature=0.4)
    result.setdefault("is_correct", False)
    result.setdefault("next_hint", "")
    result.setdefault("encouragement", "")
    return result


# --------------------------------------------------------------------------
# Conversational coach ("ask the coach anything")
# --------------------------------------------------------------------------

def chat_with_coach(
    message: str,
    topic: str,
    student_level: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Free-form chat with the coach, grounded in what the student is
    currently learning. Keeps the "guide, don't just answer" philosophy.
    """
    system_prompt = (
        COACH_PERSONA
        + f" The student is currently learning '{topic}' at a "
        f"'{student_level}' level. If they ask you to just 'give the "
        "answer' to something they should be practicing, gently push back "
        "and guide them toward figuring it out themselves, offering hints "
        "instead of the final answer, unless they are asking about a pure "
        "factual/definitional question -- those you can answer directly."
    )
    return call_llm_text(
        system_prompt,
        message,
        temperature=0.6,
        conversation_history=conversation_history,
    )


# --------------------------------------------------------------------------
# "What should I do next?" recommendation
# --------------------------------------------------------------------------

def recommend_next_step(
    roadmap: Dict[str, Any],
    progress_summary: Dict[str, Any],
) -> str:
    """
    Produces a short, personalized recommendation of what the student
    should focus on next, combining roadmap position and progress history
    (e.g. concepts they've struggled with, streak, pace).
    """
    from roadmap import get_next_topic  # local import avoids a circular dependency

    next_topic = get_next_topic(roadmap)
    system_prompt = COACH_PERSONA
    user_prompt = f"""
Roadmap topic: {roadmap.get('topic')}
Roadmap difficulty: {roadmap.get('difficulty')}
Next unfinished topic: {next_topic.get('name') if next_topic else 'None - roadmap complete'}
Overall progress: {progress_summary}

In 2-4 short sentences, tell the student what to focus on next and why,
in a warm, motivating coach voice. If the roadmap is complete, congratulate
them and suggest a logical next step (e.g. a related advanced topic or
project idea) instead.
"""
    return call_llm_text(system_prompt, user_prompt, temperature=0.6, max_tokens=300)
