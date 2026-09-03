"""
AppTest harness for `assistant.session` — the widget's state machine without the
popover / fragment / dialog chrome, so `streamlit.testing.v1.AppTest` can drive
it. Underscore-prefixed so pytest does not collect it as a test module.
"""

import streamlit as st

from assistant import session

session.init()

# Drain a pending answer synchronously (the widget does this via st.write_stream).
if st.session_state.get("asst_pending"):
    draft = "".join(session.stream_reply())
    session.resolve_pending(draft)

st.write(f"stage={st.session_state.asst_stage}")

msg = st.text_input("msg", key="msg")
if st.button("send", key="send") and msg.strip():
    session.ask(msg.strip())
    st.rerun()

if st.button("up", key="up"):
    session.feedback(True)
    st.rerun()
if st.button("down", key="down"):
    session.feedback(False)
    st.rerun()
if st.button("more", key="more"):
    session.tell_me_more()
    st.rerun()

if st.button("prepare_ticket", key="prepare_ticket"):
    session.prepare_ticket()
    st.rerun()
if st.button("link_dup", key="link_dup"):
    session.link_duplicate()
    st.rerun()
if st.button("file_ticket", key="file_ticket"):
    session.file_ticket(
        name="Jane", email="jane@example.com",
        subject="Cannot void a payment", summary="The Void button is greyed out.",
    )
    st.rerun()
if st.button("reset", key="reset"):
    session.reset()
    st.rerun()
