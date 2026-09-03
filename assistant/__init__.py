"""
The Streamlit-facing layer for the SugboDoc support assistant.

This package is the *only* place `import streamlit` appears for the chatbot —
everything under `core/` stays pure Python. It is built to lift straight into
the umbrella "SugboDoc" multipage app: copy `assistant/`, add two secret keys,
call `render_floating_assistant()` at the bottom of each page. See MERGE.md.

    from assistant.bootstrap import load_secrets
    load_secrets()                       # st.secrets -> os.environ (MERGE SEAM #1)

    from assistant.widget import render_floating_assistant
    render_floating_assistant()          # the shared floating widget
"""
