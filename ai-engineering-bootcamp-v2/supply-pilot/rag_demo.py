"""
SupplyPilot Demo UI

Phase 1:
- Product-style navigation
- Working SupplyPilot chat
- Conversation continuity with session_id
- New Session creates a fresh conversational session
- Existing FastAPI /agent connection
- Contextual follow-up buttons after replenishment answers
- Other pages intentionally left empty for now

Run locally:

    export API_BASE_URL=http://127.0.0.1:8000
    streamlit run rag_demo.py
"""

import json
import os
import uuid

import httpx
import streamlit as st


# --------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------

st.set_page_config(
    page_title="SupplyPilot",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------
# STYLING
# --------------------------------------------------

st.markdown(
    """
    <style>

    .stApp {
        background: #ffffff;
    }

    .block-container {
        padding-top: 1.7rem;
        padding-bottom: 2rem;
        max-width: 1250px;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: #071a33;
        border-right: 1px solid #162a44;
    }

    section[data-testid="stSidebar"] * {
        color: #f8fafc;
    }

    section[data-testid="stSidebar"] .stRadio label {
        padding: 8px 6px;
        border-radius: 7px;
        font-size: 14px;
    }

    /* Hide Streamlit chrome */
    #MainMenu {
        visibility: hidden;
    }

    footer {
        visibility: hidden;
    }

    header[data-testid="stHeader"] {
        background: transparent;
    }

    /* App logo */
    .supplypilot-logo {
        font-size: 25px;
        font-weight: 700;
        padding: 4px 2px 18px 2px;
        letter-spacing: -0.5px;
    }

    .supplypilot-logo span {
        color: #3b82f6;
    }

    /* Page title */
    .page-title {
        font-size: 26px;
        font-weight: 700;
        margin-bottom: 2px;
        color: #0f172a;
    }

    .page-subtitle {
        color: #64748b;
        font-size: 14px;
        margin-bottom: 24px;
    }

    /* Chat messages */
    div[data-testid="stChatMessage"] {
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 8px 12px;
        margin-bottom: 10px;
        background: white;
    }

    /* Chat input */
    div[data-testid="stChatInput"] {
        padding-top: 10px;
    }

    /* Footer */
    .chat-footer {
        text-align: center;
        color: #94a3b8;
        font-size: 11px;
        margin-top: 10px;
    }

    /* Placeholder pages */
    .coming-soon {
        margin-top: 40px;
        padding: 40px;
        border: 1px dashed #cbd5e1;
        border-radius: 10px;
        color: #64748b;
        text-align: center;
    }

    /* Calculation rows */
    .calc-title {
        font-size: 17px;
        font-weight: 700;
        color: #0f172a;
        margin-top: 10px;
        margin-bottom: 8px;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------
# API CONFIG
# --------------------------------------------------

API_BASE_URL = os.getenv(
    "API_BASE_URL",
    "http://127.0.0.1:8000",
)


# --------------------------------------------------
# AGENT STREAM
# --------------------------------------------------

def stream_agent(
    base_url: str,
    message: str,
    session_id: str,
):
    """
    Stream events from FastAPI POST /agent.

    The same session_id is reused for all questions
    in the current Streamlit conversation.
    """

    try:
        with httpx.stream(
            "POST",
            f"{base_url.rstrip('/')}/agent",
            json={
                "message": message,
                "session_id": session_id,
            },
            timeout=180.0,
        ) as response:

            if response.status_code != 200:
                yield {
                    "type": "http_error",
                    "status": response.status_code,
                    "message": response.read().decode(),
                }
                return

            for line in response.iter_lines():

                if not line or not line.startswith("data:"):
                    continue

                try:
                    yield json.loads(
                        line[5:].strip()
                    )

                except json.JSONDecodeError:
                    yield {
                        "type": "error",
                        "message":
                            f"Invalid stream event: {line}",
                    }

    except httpx.HTTPError as exc:
        yield {
            "type": "error",
            "message": str(exc),
        }


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []

# This ID represents the current conversation.
if "session_id" not in st.session_state:
    st.session_state.session_id = str(
        uuid.uuid4()
    )

if "last_tool" not in st.session_state:
    st.session_state.last_tool = None

if "last_workflow" not in st.session_state:
    st.session_state.last_workflow = None

if "show_calculation" not in st.session_state:
    st.session_state.show_calculation = False

if "show_quantity_reason" not in st.session_state:
    st.session_state.show_quantity_reason = False


# --------------------------------------------------
# SIDEBAR
# --------------------------------------------------

with st.sidebar:

    st.markdown(
        """
        <div class="supplypilot-logo">
            <span>◆</span> SupplyPilot
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button(
        "＋  New Session",
        use_container_width=True,
        type="primary",
    ):
        # Clear visible conversation.
        st.session_state.messages = []

        # Create a genuinely fresh conversation.
        st.session_state.session_id = str(
            uuid.uuid4()
        )

        # Clear temporary UI state.
        st.session_state.last_tool = None
        st.session_state.last_workflow = None
        st.session_state.show_calculation = False
        st.session_state.show_quantity_reason = False

        st.rerun()

    st.write("")

    page = st.radio(
        "Navigation",
        [
            "💬  Chat",
            "✦  Recommendations",
            "▣  Inventory",
            "⌁  Forecast",
            "▤  Purchase Orders",
            "♙  Suppliers",
            "◇  Products",
            "▱  Policies",
            "◉  Memory",
            "◎  Evaluations",
            "⚙  Settings",
        ],
        label_visibility="collapsed",
    )

    st.markdown("---")

    st.markdown(
        """
        **P  Planner**

        <span style="font-size:11px;color:#94a3b8">
        Supply planning workspace
        </span>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------
# CHAT PAGE
# --------------------------------------------------

if page == "💬  Chat":

    st.markdown(
        '<div class="page-title">Chat</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="page-subtitle">
        Ask SupplyPilot anything about inventory
        and supply planning.
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ----------------------------------------------
    # Conversation history
    # ----------------------------------------------

    for message in st.session_state.messages:

        with st.chat_message(
            message["role"]
        ):
            st.markdown(
                message["content"]
            )

    # ----------------------------------------------
    # Chat input
    # ----------------------------------------------

    prompt = st.chat_input(
        "Ask SupplyPilot..."
    )

    # ----------------------------------------------
    # New user question
    # ----------------------------------------------

    if prompt:

        # Clear controls from previous answer.
        st.session_state.last_tool = None
        st.session_state.last_workflow = None
        st.session_state.show_calculation = False
        st.session_state.show_quantity_reason = False

        # Save user message for UI history.
        st.session_state.messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        with st.chat_message("user"):
            st.markdown(prompt)

        # ------------------------------------------
        # Assistant response
        # ------------------------------------------

        with st.chat_message(
            "assistant"
        ):

            status_box = st.empty()

            status_box.info(
                "SupplyPilot is analysing..."
            )

            final_answer = None
            last_tool = None

            for event in stream_agent(
                API_BASE_URL,
                prompt,
                st.session_state.session_id,
            ):

                event_type = event.get(
                    "type"
                )

                # ----------------------------------
                # ACT
                # ----------------------------------

                if event_type == "act":

                    last_tool = event.get(
                        "tool",
                        "planning workflow",
                    )

                    st.session_state.last_tool = (
                        last_tool
                    )

                    status_box.info(
                        f"Running {last_tool}..."
                    )

                # ----------------------------------
                # OBSERVE
                # ----------------------------------

                elif event_type == "observe":

                    tool_name = event.get(
                        "tool",
                        last_tool,
                    )

                    st.session_state.last_tool = (
                        tool_name
                    )

                    if (
                        tool_name
                        == "run_replenishment_workflow"
                    ):

                        workflow_data = (
                            event.get("data")
                        )

                        if workflow_data:
                            st.session_state.last_workflow = (
                                workflow_data
                            )

                        status_box.success(
                            "✓ Replenishment workflow completed"
                        )

                    else:

                        status_box.info(
                            "Reviewing planning data..."
                        )

                # ----------------------------------
                # MODEL RETRY
                # ----------------------------------

                elif event_type == "model_retry":

                    status_box.warning(
                        "Model temporarily busy — retrying..."
                    )

                # ----------------------------------
                # MODEL FALLBACK
                # ----------------------------------

                elif event_type == "model_fallback":

                    status_box.warning(
                        "Using fallback model..."
                    )

                # ----------------------------------
                # FINAL
                # ----------------------------------

                elif event_type == "final":

                    final_answer = event.get(
                        "answer",
                        "No answer returned.",
                    )

                # ----------------------------------
                # HTTP ERROR
                # ----------------------------------

                elif event_type == "http_error":

                    status_box.error(
                        f"API error — HTTP "
                        f"{event.get('status')}"
                    )

                    st.error(
                        event.get(
                            "message",
                            "Unknown API error.",
                        )
                    )

                    break

                # ----------------------------------
                # AGENT ERROR
                # ----------------------------------

                elif event_type == "error":

                    status_box.error(
                        "SupplyPilot could not "
                        "complete the request."
                    )

                    st.error(
                        event.get(
                            "message",
                            "Unknown error.",
                        )
                    )

                    break

            # --------------------------------------
            # Render final answer
            # --------------------------------------

            if final_answer:

                status_box.success(
                    "✓ Analysis complete"
                )

                st.markdown(
                    final_answer
                )

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": final_answer,
                    }
                )

    # --------------------------------------------------
    # CONTEXTUAL FOLLOW-UP CONTROLS
    # --------------------------------------------------

    if (
        st.session_state.last_tool
        == "run_replenishment_workflow"
        and st.session_state.last_workflow
    ):

        st.write("")

        col1, col2 = st.columns(2)

        if col1.button(
            "Show calculation",
            use_container_width=True,
            key="show_calculation_button",
        ):
            st.session_state.show_calculation = (
                not st.session_state.show_calculation
            )

        if col2.button(
            "Why this quantity?",
            use_container_width=True,
            key="show_quantity_reason_button",
        ):
            st.session_state.show_quantity_reason = (
                not st.session_state.show_quantity_reason
            )

    # --------------------------------------------------
    # CALCULATION DETAILS
    # --------------------------------------------------

    workflow = (
        st.session_state.last_workflow
    )

    if (
        workflow
        and st.session_state.show_calculation
    ):

        st.markdown(
            """
            <div class="calc-title">
            How this was calculated
            </div>
            """,
            unsafe_allow_html=True,
        )

        rows = [
            (
                "Current inventory",
                f"{workflow.get('current_inventory', '—')} units",
            ),
            (
                "Planning point",
                workflow.get(
                    "planning_week",
                    "—",
                ),
            ),
            (
                "Projected inventory",
                f"{workflow.get('projected_inventory', '—')} units",
            ),
            (
                "Forward average demand",
                f"{workflow.get('forward_average_demand', '—')} units/week",
            ),
            (
                "Projected WOS",
                workflow.get(
                    "projected_wos",
                    "—",
                ),
            ),
            (
                "Target WOS",
                workflow.get(
                    "target_wos",
                    "—",
                ),
            ),
            (
                "Target inventory",
                f"{workflow.get('target_inventory', '—')} units",
            ),
            (
                "Gap to target",
                f"{workflow.get('gap_to_target', '—')} units",
            ),
            (
                "Initial replenishment requirement",
                f"{workflow.get('initial_replenishment_requirement', '—')} units",
            ),
            (
                "MOQ",
                f"{workflow.get('moq', '—')} units",
            ),
            (
                "Order multiple",
                f"{workflow.get('order_multiple', '—')} units",
            ),
            (
                "Final recommended quantity",
                f"{workflow.get('recommended_order_qty', '—')} units",
            ),
        ]

        for label, value in rows:

            left, right = st.columns(
                [2, 1]
            )

            left.write(label)

            right.markdown(
                f"**{value}**"
            )

    # --------------------------------------------------
    # WHY THIS QUANTITY?
    # --------------------------------------------------

    if (
        workflow
        and st.session_state.show_quantity_reason
    ):

        required_qty = workflow.get(
            "initial_replenishment_requirement"
        )

        moq = workflow.get(
            "moq"
        )

        order_multiple = workflow.get(
            "order_multiple"
        )

        final_qty = workflow.get(
            "recommended_order_qty"
        )

        st.info(
            f"The initial replenishment requirement is "
            f"{required_qty} units. "
            f"The supplier requires an MOQ of "
            f"{moq} units and orders in multiples of "
            f"{order_multiple}. "
            f"Therefore the first valid order quantity is "
            f"{final_qty} units."
        )

    # --------------------------------------------------
    # CHAT FOOTER
    # --------------------------------------------------

    st.markdown(
        """
        <div class="chat-footer">
        SupplyPilot can make mistakes.
        Validate critical planning decisions.
        </div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------
# OTHER PAGES — PHASE 2+
# --------------------------------------------------

else:

    page_name = (
        page.split("  ", 1)[1]
        if "  " in page
        else page
    )

    st.markdown(
        f'<div class="page-title">'
        f'{page_name}'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="coming-soon">
        This workspace will be added
        in the next step.
        </div>
        """,
        unsafe_allow_html=True,
    )