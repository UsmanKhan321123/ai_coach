"""
assessment.py
----------------
Handles the initial skill-assessment stage of the AI Learning Coach.

Responsibilities:
    1. Dynamically generate topic + difficulty specific assessment questions
       using an LLM (Groq).
    2. Render the assessment as an interactive Streamlit quiz.
    3. Evaluate the user's answers and produce a structured "assessment
       report" (scores per concept, strengths, weaknesses, recommended
       starting level) that `roadmap.py` consumes to build a personalized
       learning roadmap.

Usage (from app.py):

    from assessment import run_assessment_flow

    result = run_assessment_flow(topic="Python Programming", difficulty="beginner")
    if result:
        # assessment finished -> result is the assessment_report dict
        ...
"""

from datetime import datetime
from typing import List, Dict, Any, Optional

import streamlit as st

from ai_coach import call_llm_json

NUM_ASSESSMENT_QUESTIONS = 6


# --------------------------------------------------------------------------
# Question generation
# --------------------------------------------------------------------------

def generate_assessment_questions(
    topic: str,
    difficulty: str,
    num_questions: int = NUM_ASSESSMENT_QUESTIONS,
) -> List[Dict[str, Any]]:
    """
    Generates a list of assessment questions for the given topic & difficulty.

    Each question dict has the shape:
        MCQ:
            {
                "id": "q1", "concept": "variables", "type": "mcq",
                "question": "...", "options": [...],
                "correct_answer": "...", "explanation": "..."
            }
        Short answer:
            {
                "id": "q2", "concept": "loops", "type": "short_answer",
                "question": "...", "model_answer": "...", "explanation": "..."
            }
    """
    system_prompt = (
        "You are an expert curriculum designer and technical interviewer. "
        "You design short diagnostic quizzes that accurately measure a "
        "learner's current skill level on a given subject before a course "
        "starts. You always respond with STRICT valid JSON and nothing else "
        "(no markdown, no commentary)."
    )

    user_prompt = f"""
Create a diagnostic assessment quiz for a student who wants to learn:

Topic: {topic}
Self-reported difficulty level: {difficulty}

Requirements:
- Generate exactly {num_questions} questions.
- Mostly "mcq" (multiple choice, 4 options), with at most 1-2 "short_answer"
  conceptual questions.
- Questions should probe foundational concepts relevant to the stated
  difficulty level (for "beginner" test fundamentals; for
  "intermediate"/"advanced" test deeper/applied concepts).
- Tag every question with a short "concept" label (e.g. "variables",
  "loops", "functions", "data structures") so results can be grouped later.
- For "mcq": include 4 plausible "options" and the exact "correct_answer"
  string (must match one option exactly).
- For "short_answer": provide a "model_answer" (ideal answer) instead of
  "options"/"correct_answer".
- Provide a one-line "explanation" for each question's correct answer.

Return ONLY a valid JSON array where each element follows this schema:

MCQ:
{{
  "id": "q1",
  "concept": "short concept name",
  "type": "mcq",
  "question": "question text",
  "options": ["opt1", "opt2", "opt3", "opt4"],
  "correct_answer": "opt2",
  "explanation": "why opt2 is correct"
}}

Short answer:
{{
  "id": "q2",
  "concept": "short concept name",
  "type": "short_answer",
  "question": "question text",
  "model_answer": "ideal concise answer",
  "explanation": "what a good answer should include"
}}
"""

    questions = call_llm_json(system_prompt, user_prompt, temperature=0.7)

    if not isinstance(questions, list) or not questions:
        raise ValueError("LLM did not return a valid list of questions.")

    for i, q in enumerate(questions):
        q.setdefault("id", f"q{i+1}")
        q.setdefault("concept", "general")
        q.setdefault("type", "mcq")

    return questions


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

def _grade_short_answer(question: Dict[str, Any], user_answer: str) -> Dict[str, Any]:
    """
    Uses the LLM to grade a free-text short answer against the model answer.
    Returns {"is_correct": bool, "score": float (0-1), "feedback": str}.
    """
    if not user_answer or not user_answer.strip():
        return {"is_correct": False, "score": 0.0, "feedback": "No answer provided."}

    system_prompt = (
        "You are a fair, encouraging technical grader. You evaluate a "
        "student's short answer against a model answer and respond with "
        "STRICT valid JSON only."
    )
    user_prompt = f"""
Question: {question.get('question')}
Model / ideal answer: {question.get('model_answer', '')}
Student's answer: {user_answer}

Grade the student's answer on a 0.0 to 1.0 scale for conceptual correctness
(wording does not need to match, only the underlying understanding matters).

Return ONLY JSON:
{{
  "score": 0.0,
  "is_correct": true,
  "feedback": "one short sentence of feedback"
}}
"""
    try:
        result = call_llm_json(system_prompt, user_prompt, temperature=0.3)
        result.setdefault("score", 0.0)
        result.setdefault("is_correct", result["score"] >= 0.6)
        result.setdefault("feedback", "")
        return result
    except Exception:
        # Graceful fallback if the grading call itself fails.
        return {"is_correct": False, "score": 0.0, "feedback": "Could not auto-grade this answer."}


def _recommend_level(score_percentage: float, requested_difficulty: str) -> str:
    """
    Adjusts the recommended starting level based on actual performance,
    instead of blindly trusting the student's self-reported difficulty.
    """
    levels = ["beginner", "intermediate", "advanced"]
    requested_difficulty = requested_difficulty.lower()
    idx = levels.index(requested_difficulty) if requested_difficulty in levels else 0

    if score_percentage >= 85 and idx < len(levels) - 1:
        return levels[idx + 1]
    if score_percentage < 40 and idx > 0:
        return levels[idx - 1]
    return levels[idx]


def evaluate_assessment(
    questions: List[Dict[str, Any]],
    user_answers: Dict[str, str],
    topic: str,
    difficulty: str,
) -> Dict[str, Any]:
    """Evaluates all answers and produces a structured assessment report."""
    concept_scores: Dict[str, List[float]] = {}
    per_question_results = []
    correct_count = 0

    for q in questions:
        qid = q["id"]
        user_answer = user_answers.get(qid, "")
        concept = q.get("concept", "general")

        if q["type"] == "mcq":
            is_correct = (
                str(user_answer).strip().lower()
                == str(q.get("correct_answer", "")).strip().lower()
            )
            score = 1.0 if is_correct else 0.0
            feedback = q.get("explanation", "")
        else:  # short_answer
            grading = _grade_short_answer(q, user_answer)
            is_correct = grading["is_correct"]
            score = grading["score"]
            feedback = grading["feedback"]

        if is_correct:
            correct_count += 1

        concept_scores.setdefault(concept, []).append(score)

        per_question_results.append({
            "id": qid,
            "concept": concept,
            "question": q["question"],
            "user_answer": user_answer,
            "is_correct": is_correct,
            "score": score,
            "feedback": feedback,
        })

    total = len(questions)
    score_percentage = (
        round((sum(r["score"] for r in per_question_results) / total) * 100, 1)
        if total else 0.0
    )

    avg_concept_scores = {
        concept: round(sum(scores) / len(scores), 2)
        for concept, scores in concept_scores.items()
    }

    strengths = [c for c, s in avg_concept_scores.items() if s >= 0.7]
    weaknesses = [c for c, s in avg_concept_scores.items() if s < 0.5]
    recommended_level = _recommend_level(score_percentage, difficulty)

    return {
        "topic": topic,
        "difficulty_requested": difficulty,
        "total_questions": total,
        "correct_count": correct_count,
        "score_percentage": score_percentage,
        "concept_scores": avg_concept_scores,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommended_starting_level": recommended_level,
        "per_question_results": per_question_results,
        "timestamp": datetime.now().isoformat(),
    }


# --------------------------------------------------------------------------
# Streamlit UI flow
# --------------------------------------------------------------------------

def run_assessment_flow(topic: str, difficulty: str) -> Optional[Dict[str, Any]]:
    """
    Renders the full assessment experience inside Streamlit:
      1. Generates questions once (cached in session_state).
      2. Renders the quiz form.
      3. On submit, evaluates answers and returns the assessment report.

    Returns:
        The assessment_report dict once the user submits the quiz,
        otherwise None (still in progress / not submitted yet).
    """
    session_key = f"assessment_questions::{topic}::{difficulty}"

    if session_key not in st.session_state:
        with st.spinner("Generating your personalized assessment..."):
            try:
                st.session_state[session_key] = generate_assessment_questions(topic, difficulty)
            except Exception as e:
                st.error(f"Could not generate assessment: {e}")
                return None

    questions = st.session_state[session_key]

    st.subheader(f"📝 Quick Assessment: {topic} ({difficulty.title()})")
    st.caption(
        "Answer honestly — this helps the AI coach build a roadmap that "
        "actually fits your current level, not just what you think you know."
    )

    with st.form(key=f"assessment_form::{topic}::{difficulty}"):
        user_answers: Dict[str, str] = {}

        for i, q in enumerate(questions, start=1):
            st.markdown(f"**Q{i}. {q['question']}**")
            if q["type"] == "mcq":
                user_answers[q["id"]] = st.radio(
                    label="Select one:",
                    options=q.get("options", []),
                    key=f"ans_{q['id']}",
                    index=None,
                    label_visibility="collapsed",
                )
            else:
                user_answers[q["id"]] = st.text_area(
                    label="Your answer:",
                    key=f"ans_{q['id']}",
                    label_visibility="collapsed",
                )
            st.divider()

        submitted = st.form_submit_button(
            "Submit Assessment", type="primary", use_container_width=True
        )

    if submitted:
        unanswered = [q["id"] for q in questions if not user_answers.get(q["id"])]
        if unanswered:
            st.warning("Please answer all questions before submitting.")
            return None

        with st.spinner("Evaluating your answers..."):
            report = evaluate_assessment(questions, user_answers, topic, difficulty)

        _render_assessment_summary(report)
        return report

    return None


def _render_assessment_summary(report: Dict[str, Any]) -> None:
    """Displays a friendly, readable summary of the assessment result."""
    st.success("Assessment complete! ✅")

    col1, col2, col3 = st.columns(3)
    col1.metric("Score", f"{report['score_percentage']}%")
    col2.metric("Correct", f"{report['correct_count']}/{report['total_questions']}")
    col3.metric("Recommended Level", report["recommended_starting_level"].title())

    if report["strengths"]:
        st.markdown("**💪 Strengths:** " + ", ".join(report["strengths"]))
    if report["weaknesses"]:
        st.markdown("**📌 Focus areas:** " + ", ".join(report["weaknesses"]))

    with st.expander("See detailed question-by-question breakdown"):
        for r in report["per_question_results"]:
            icon = "✅" if r["is_correct"] else "❌"
            st.markdown(f"{icon} **{r['question']}**")
            st.caption(f"Your answer: {r['user_answer']}")
            if r["feedback"]:
                st.caption(f"💡 {r['feedback']}")
