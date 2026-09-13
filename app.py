"""
app.py
----------------
Main entry point for the AI Learning Coach (Streamlit app).

Flow:
    1. Student enters their name and picks a topic + difficulty.
    2. They take a short diagnostic assessment (assessment.py).
    3. A personalized roadmap is generated from the results (roadmap.py).
    4. Student works through the roadmap, gets guided explanations and
       practice exercises from the coach (ai_coach.py) instead of just
       being handed answers.
    5. Everything is saved and visualized in a progress dashboard
       (progress.py).

Run with:
    streamlit run app.py

Requires GROQ_API_KEY to be set as an environment variable or in
.streamlit/secrets.toml.
"""

import streamlit as st

from assessment import run_assessment_flow
from roadmap import generate_roadmap, render_roadmap_ui, get_next_topic
from ai_coach import (
    explain_concept,
    generate_practice_exercise,
    evaluate_practice_submission,
    chat_with_coach,
    recommend_next_step,
)
from progress import (
    load_student_data,
    record_assessment,
    record_roadmap,
    get_roadmap,
    log_practice_attempt,
    get_progress_summary,
    render_progress_dashboard,
    record_final_exam,
)
from final_assessment import render_final_quiz, render_final_result

st.set_page_config(page_title="AI Learning Coach", page_icon="🎓", layout="wide")

st.markdown(
    """
    <style>
    .stApp { background: #0b1f3a; color: #ffffff; }
    [data-testid="stSidebar"] { background: #061426; }
    [data-testid="stSidebar"] * { color: #ffffff !important; }
    .stApp p, .stApp label, .stApp span, .stApp li, .stApp td, .stApp th,
    .stApp .stMarkdown, .stApp [data-testid="stCaptionContainer"] { color: #ffffff; }
    h1, h2, h3, h4, h5, h6 { color: #ffffff; letter-spacing: 0; }
    .hero { padding: 1.7rem 2rem; border-radius: 12px; background: #123b69; color: #ffffff; margin-bottom: 1.4rem; }
    .hero h1, .hero p { color: #ffffff; margin-bottom: .35rem; }
    .exam-banner { display:flex; justify-content:space-between; align-items:center; padding: .85rem 1rem; margin: .75rem 0 1.25rem; border-left: 5px solid #f4b860; background:#123b69; color:#ffffff; border-radius: 6px; font-size:1.05rem; }
    #exam-timer { color:#ffd166; font-size:1.35rem; font-weight:700; font-variant-numeric: tabular-nums; }
    div[data-testid="stMetric"] { background: #123b69; border: 1px solid #2d5d91; padding: .65rem; border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Session state defaults
# --------------------------------------------------------------------------

def _init_session_state() -> None:
    defaults = {
        "student_id": "",
        "current_topic": "",
        "current_difficulty": "beginner",
        "assessment_result": None,
        "active_roadmap": None,
        "coach_chat_history": [],
        "active_exercise": None,
        "final_exam_recorded": set(),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


_init_session_state()


# --------------------------------------------------------------------------
# Sidebar: student identity + navigation
# --------------------------------------------------------------------------

with st.sidebar:
    st.title("🎓 AI Learning Coach")

    student_id_input = st.text_input(
        "Your name / student ID",
        value=st.session_state.student_id,
        placeholder="e.g. ali_khan",
    )
    if student_id_input != st.session_state.student_id:
        st.session_state.student_id = student_id_input
        # Reset topic-specific state when switching students
        st.session_state.active_roadmap = None
        st.session_state.assessment_result = None

    st.divider()

    if not st.session_state.student_id:
        st.info("👆 Enter your name to get started.")
        page = "Start"
    else:
        page = st.radio(
            "Navigate",
            options=["Start New Topic", "Assessment", "Roadmap", "Coach & Practice", "Final Quiz", "Progress Dashboard"],
            label_visibility="collapsed",
        )

    st.divider()
    st.caption("Powered by Groq LLM · Built with Streamlit")


# --------------------------------------------------------------------------
# Page: Start New Topic
# --------------------------------------------------------------------------

def render_start_page() -> None:
    st.markdown(
        "<div class='hero'><h1>Build skills that stick.</h1><p>Learn with a personalized roadmap, guided practice, and a final course examination.</p></div>",
        unsafe_allow_html=True,
    )
    st.header("What do you want to learn today?")

    with st.form("start_topic_form"):
        topic = st.text_input("Topic", value=st.session_state.current_topic or "", placeholder="e.g. Python Programming")
        difficulty = st.selectbox(
            "How would you describe your current level?",
            options=["beginner", "intermediate", "advanced"],
            index=["beginner", "intermediate", "advanced"].index(st.session_state.current_difficulty),
        )
        submitted = st.form_submit_button("Start Assessment", type="primary", use_container_width=True)

    if submitted:
        if not topic.strip():
            st.warning("Please enter a topic to continue.")
            return
        st.session_state.current_topic = topic.strip()
        st.session_state.current_difficulty = difficulty
        st.session_state.assessment_result = None
        st.session_state.active_roadmap = None
        st.success(f"Great! Head to the **Assessment** tab to test your {topic} knowledge.")

    existing_roadmaps = load_student_data(st.session_state.student_id).get("roadmaps", {})
    if existing_roadmaps:
        st.divider()
        st.subheader("Or continue an existing topic")
        for t in existing_roadmaps:
            if st.button(f"Continue: {t}", key=f"continue_{t}"):
                st.session_state.current_topic = t
                st.session_state.active_roadmap = get_roadmap(st.session_state.student_id, t)
                st.session_state.current_difficulty = st.session_state.active_roadmap.get("difficulty", "beginner")
                st.rerun()


# --------------------------------------------------------------------------
# Page: Assessment
# --------------------------------------------------------------------------

def render_assessment_page() -> None:
    if not st.session_state.current_topic:
        st.info("Pick a topic first on the **Start New Topic** page.")
        return

    st.header(f"Assessment: {st.session_state.current_topic}")

    result = run_assessment_flow(
        topic=st.session_state.current_topic,
        difficulty=st.session_state.current_difficulty,
    )

    if result:
        st.session_state.assessment_result = result
        record_assessment(st.session_state.student_id, result)

        with st.spinner("Building your personalized roadmap..."):
            roadmap = generate_roadmap(
                topic=st.session_state.current_topic,
                difficulty=st.session_state.current_difficulty,
                assessment_result=result,
            )
        st.session_state.active_roadmap = roadmap
        record_roadmap(st.session_state.student_id, roadmap)

        st.success("Your roadmap is ready! Head to the **Roadmap** tab. 🗺️")


# --------------------------------------------------------------------------
# Page: Roadmap
# --------------------------------------------------------------------------

def render_roadmap_page() -> None:
    roadmap = st.session_state.active_roadmap
    if not roadmap:
        st.info("No roadmap yet. Complete an assessment first on the **Assessment** page.")
        return

    render_roadmap_ui(roadmap)
    record_roadmap(st.session_state.student_id, roadmap)  # persist any status changes made in the UI


# --------------------------------------------------------------------------
# Page: Coach & Practice
# --------------------------------------------------------------------------

def render_coach_page() -> None:
    roadmap = st.session_state.active_roadmap
    if not roadmap:
        st.info("No active roadmap yet. Complete an assessment first.")
        return

    next_topic = get_next_topic(roadmap)

    tab_learn, tab_practice, tab_chat = st.tabs(["📖 Learn", "🛠 Practice", "💬 Ask the Coach"])

    # --- Learn tab: guided explanation of the next concept ---
    with tab_learn:
        if not next_topic:
            st.success("🎉 You've completed this roadmap! Check the Dashboard or start a new topic.")
        else:
            st.subheader(f"Next up: {next_topic['name']}")
            if st.button("Explain this to me", type="primary"):
                with st.spinner("Preparing your explanation..."):
                    explanation = explain_concept(
                        topic=roadmap["topic"],
                        concept=next_topic["name"],
                        student_level=roadmap["difficulty"],
                    )
                st.markdown(explanation)

    # --- Practice tab: exercise + guided evaluation (no free answers) ---
    with tab_practice:
        if not next_topic:
            st.info("No pending topic to practice — roadmap complete!")
        else:
            if st.button("Give me a practice exercise"):
                with st.spinner("Designing an exercise for you..."):
                    st.session_state.active_exercise = generate_practice_exercise(
                        topic=roadmap["topic"],
                        concept=next_topic["name"],
                        difficulty=roadmap["difficulty"],
                    )

            exercise = st.session_state.active_exercise
            if exercise:
                st.markdown(f"**{exercise['title']}**")
                st.write(exercise["instructions"])
                if exercise.get("starter_code_or_template"):
                    st.code(exercise["starter_code_or_template"])

                with st.expander("Need a hint?"):
                    for i, hint in enumerate(exercise.get("hints", []), start=1):
                        st.caption(f"Hint {i}: {hint}")

                submission = st.text_area("Your attempt", height=150, key="practice_submission")
                if st.button("Check my work", type="primary"):
                    if not submission.strip():
                        st.warning("Write your attempt first.")
                    else:
                        with st.spinner("Reviewing your attempt..."):
                            feedback = evaluate_practice_submission(exercise, submission)

                        log_practice_attempt(
                            st.session_state.student_id,
                            roadmap["topic"],
                            next_topic["name"],
                            feedback["is_correct"],
                        )

                        if feedback["is_correct"]:
                            st.success(feedback["feedback"])
                        else:
                            st.warning(feedback["feedback"])
                            if feedback.get("next_hint"):
                                st.info(f"💡 {feedback['next_hint']}")
                        if feedback.get("encouragement"):
                            st.caption(feedback["encouragement"])

    # --- Chat tab: free-form Q&A grounded in current topic ---
    with tab_chat:
        for turn in st.session_state.coach_chat_history:
            with st.chat_message(turn["role"]):
                st.write(turn["content"])

        user_message = st.chat_input("Ask your coach anything about this topic...")
        if user_message:
            st.session_state.coach_chat_history.append({"role": "user", "content": user_message})
            with st.spinner("Thinking..."):
                reply = chat_with_coach(
                    message=user_message,
                    topic=roadmap["topic"],
                    student_level=roadmap["difficulty"],
                    conversation_history=st.session_state.coach_chat_history[:-1],
                )
            st.session_state.coach_chat_history.append({"role": "assistant", "content": reply})
            st.rerun()

    # --- "What should I focus on next" nudge, shown at the bottom ---
    st.divider()
    if st.button("🎯 What should I focus on next?"):
        with st.spinner("Thinking about your progress..."):
            summary = get_progress_summary(st.session_state.student_id)
            recommendation = recommend_next_step(roadmap, summary)
        st.info(recommendation)


# --------------------------------------------------------------------------
# Page: Progress Dashboard
# --------------------------------------------------------------------------

def render_dashboard_page() -> None:
    render_progress_dashboard(st.session_state.student_id)


# --------------------------------------------------------------------------
# Page: Final Quiz
# --------------------------------------------------------------------------

def render_final_quiz_page() -> None:
    roadmap = st.session_state.active_roadmap
    if not roadmap:
        st.info("Generate a roadmap first. Your final course quiz will appear here afterwards.")
        return

    result_key = f"final_result::{roadmap['topic']}::{roadmap['difficulty']}"
    result = st.session_state.get(result_key)
    if result:
        render_final_result(result)
        return

    result = render_final_quiz(roadmap["topic"], roadmap["difficulty"])
    if result:
        if result_key not in st.session_state.final_exam_recorded:
            record_final_exam(st.session_state.student_id, result)
            st.session_state.final_exam_recorded.add(result_key)
        render_final_result(result)


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------

if not st.session_state.student_id:
    st.title("🎓 Welcome to your AI Learning Coach")
    st.write("Enter your name in the sidebar to begin your personalized learning journey.")
else:
    page_renderers = {
        "Start New Topic": render_start_page,
        "Assessment": render_assessment_page,
        "Roadmap": render_roadmap_page,
        "Coach & Practice": render_coach_page,
        "Final Quiz": render_final_quiz_page,
        "Progress Dashboard": render_dashboard_page,
    }
    page_renderers[page]()
