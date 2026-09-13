"""Final course assessment: question generation, timing, grading, and UI."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import streamlit as st
import streamlit.components.v1 as components

from ai_coach import call_llm_json

FINAL_QUIZ_QUESTIONS = 100
FINAL_QUIZ_MINUTES = 90


def _quiz_key(topic: str, difficulty: str) -> str:
    return f"final_quiz::{topic}::{difficulty}"


def generate_final_quiz(topic: str, difficulty: str) -> List[Dict[str, Any]]:
    """Generate a validated, objective 100-question course examination."""
    system_prompt = (
        "You are an expert course examiner. Create rigorous but fair multiple-choice "
        "course examinations. Respond with STRICT valid JSON only, with no markdown."
    )
    user_prompt = f"""
Create the final examination for this course:
Topic: {topic}
Level: {difficulty}

Requirements:
- Return exactly {FINAL_QUIZ_QUESTIONS} questions.
- Every question must be a multiple-choice question with exactly 4 concise options.
- Cover the full course logically: fundamentals, application, troubleshooting,
  analysis, and best practices. Avoid duplicates and trick wording.
- Each correct_answer must exactly match one option.
- Include a short explanation for the correct answer.

Return ONLY a JSON array. Each item must match:
{{
  "id": "final_q1",
  "concept": "short concept label",
  "question": "question text",
  "options": ["option A", "option B", "option C", "option D"],
  "correct_answer": "option B",
  "explanation": "brief explanation"
}}
"""
    questions = call_llm_json(
        system_prompt,
        user_prompt,
        temperature=0.45,
        max_tokens=12000,
    )
    if not isinstance(questions, list) or len(questions) != FINAL_QUIZ_QUESTIONS:
        raise ValueError(f"The quiz generator returned {len(questions) if isinstance(questions, list) else 0} questions; exactly 100 are required.")

    for index, question in enumerate(questions, start=1):
        question.setdefault("id", f"final_q{index}")
        question.setdefault("concept", "general")
        options = question.get("options", [])
        if len(options) != 4 or question.get("correct_answer") not in options:
            raise ValueError(f"Question {index} has invalid options or answer data.")
    return questions


def _get_or_create_quiz(topic: str, difficulty: str) -> Optional[List[Dict[str, Any]]]:
    key = _quiz_key(topic, difficulty)
    if key not in st.session_state:
        with st.spinner("Building your 100-question final examination..."):
            try:
                st.session_state[key] = generate_final_quiz(topic, difficulty)
            except Exception as error:
                st.error(f"Could not create the final quiz: {error}")
                return None
    return st.session_state[key]


def _grade_quiz(questions: List[Dict[str, Any]], answers: Dict[str, str], topic: str, started_at: str) -> Dict[str, Any]:
    results = []
    for question in questions:
        answer = answers.get(question["id"], "")
        is_correct = answer.strip().lower() == str(question["correct_answer"]).strip().lower()
        results.append({
            "id": question["id"],
            "concept": question.get("concept", "general"),
            "question": question["question"],
            "user_answer": answer,
            "correct_answer": question["correct_answer"],
            "is_correct": is_correct,
            "explanation": question.get("explanation", ""),
        })

    correct = sum(item["is_correct"] for item in results)
    percentage = round(correct / len(results) * 100, 1)
    grade = "A" if percentage >= 90 else "B" if percentage >= 80 else "C" if percentage >= 70 else "D" if percentage >= 60 else "F"
    return {
        "topic": topic,
        "total_questions": len(results),
        "correct_count": correct,
        "score_percentage": percentage,
        "grade": grade,
        "started_at": started_at,
        "completed_at": datetime.now().isoformat(),
        "per_question_results": results,
    }


def render_final_quiz(topic: str, difficulty: str) -> Optional[Dict[str, Any]]:
    """Render the timed final exam and return a result only after submission."""
    questions = _get_or_create_quiz(topic, difficulty)
    if not questions:
        return None

    state_key = f"final_quiz_state::{topic}::{difficulty}"
    if state_key not in st.session_state:
        st.session_state[state_key] = {
            "started_at": datetime.now().isoformat(),
            "deadline": (datetime.now() + timedelta(minutes=FINAL_QUIZ_MINUTES)).isoformat(),
            "submitted": False,
        }
    quiz_state = st.session_state[state_key]
    deadline = datetime.fromisoformat(quiz_state["deadline"])
    remaining_seconds = max(0, int((deadline - datetime.now()).total_seconds()))

    st.subheader("Final Course Examination")
    st.caption(f"100 questions | {FINAL_QUIZ_MINUTES} minutes | One attempt per course run")
    components.html(
        f"<div class='exam-banner'><strong>Time remaining</strong><span id='exam-timer'>{remaining_seconds // 60:02d}:{remaining_seconds % 60:02d}</span></div>"
        f"<script>const end=Date.now()+{remaining_seconds * 1000}; setInterval(() => {{ const left=Math.max(0,end-Date.now()); const el=document.getElementById('exam-timer'); if(el) el.textContent=String(Math.floor(left/60000)).padStart(2,'0')+':' + String(Math.floor(left/1000)%60).padStart(2,'0'); }},1000);</script>",
        height=72,
        scrolling=False,
    )
    if remaining_seconds == 0:
        st.warning("The 90-minute limit has ended. Submit the form now; unanswered questions will receive zero marks.")

    with st.form(f"final_quiz_form::{topic}::{difficulty}"):
        answers: Dict[str, str] = {}
        for index, question in enumerate(questions, start=1):
            st.markdown(f"**{index}. {question['question']}**")
            answers[question["id"]] = st.radio(
                "Choose one answer",
                question["options"],
                index=None,
                key=f"final_answer_{question['id']}",
                label_visibility="collapsed",
            ) or ""
            if index != len(questions):
                st.divider()
        submitted = st.form_submit_button("Submit Final Exam", type="primary", use_container_width=True)

    if not submitted:
        return None

    result = _grade_quiz(questions, answers, topic, quiz_state["started_at"])
    result["time_expired"] = datetime.now() >= deadline
    quiz_state["submitted"] = True
    st.session_state[f"final_result::{topic}::{difficulty}"] = result
    return result


def render_final_result(result: Dict[str, Any]) -> None:
    """Render the result card and useful review information."""
    st.success("Final examination submitted and graded.")
    first, second, third = st.columns(3)
    first.metric("Grade", result["grade"])
    second.metric("Score", f"{result['score_percentage']}%")
    third.metric("Marks", f"{result['correct_count']}/{result['total_questions']}")
    if result.get("time_expired"):
        st.warning("The time limit was reached. Unanswered questions were marked incorrect.")
    with st.expander("Review your answers"):
        for item in result["per_question_results"]:
            icon = "✅" if item["is_correct"] else "❌"
            st.markdown(f"{icon} **{item['question']}**")
            st.caption(f"Your answer: {item['user_answer'] or 'Not answered'} | Correct: {item['correct_answer']}")
            st.caption(item["explanation"])