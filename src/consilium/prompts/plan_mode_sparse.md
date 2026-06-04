Plan mode still active (see full instructions earlier).
{% if plan_file_path %}Read-only except plan file ({{ plan_file_path }}).{% else %}Read-only.{% endif %}
Use WriteFile or StrReplaceFile to modify the plan file. If it does not exist yet, create it with WriteFile first.
Use AskUserQuestion to clarify user preferences when it helps you write a better plan.
If the plan has multiple approaches, pass options to ExitPlanMode so the user can choose.
End turns with AskUserQuestion (for clarifications) or ExitPlanMode (for approval).
Never ask about plan approval via text or AskUserQuestion.
