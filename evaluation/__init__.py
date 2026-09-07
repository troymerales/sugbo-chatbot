"""
Historical backtesting harness for the SugboDoc support chatbot.

This package is an *evaluation experiment*, not part of the product. It reuses
the production inference path (`core.bot.respond`) unchanged and asks a
counterfactual question: had this exact chatbot existed when a batch of
historical Jira tickets was filed, how many could it plausibly have handled
without a human?

Nothing here modifies the chatbot. See `evaluation/README.md` and
`evaluation/jira_backtest.ipynb`.
"""
