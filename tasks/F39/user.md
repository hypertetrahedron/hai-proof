I maintain a large Copier template shared by many teams. Most of its questions matter to everyone, but some are "advanced": experimental features, or settings like the docs Python version that almost nobody changes. I want those out of the default questionnaire without taking them away from the people who need them.

The design I want:

- A new per-question key in `copier.yml` called `ask`, defaulting to true. Not `hide`/`hidden`, and not a special variable used inside `when`: `when` says whether a question applies at all, `ask` says whether to prompt for it, and I want those kept separate.
- `ask` works like `when`: a boolean, or a string that can be templated (for example `ask: "{{ main_branch != 'main' }}"`) and is converted to a boolean the same way `when` is.
- A question with `ask: false` is not prompted. Its value is still recorded in the answers file: the answer passed with `--data` if there is one, otherwise its previous answer, otherwise its default. That holds even without `--defaults`; skipping it must never stop the run or need an interactive terminal. If it has no default and no answer, nothing is recorded for it and that's fine.
- On `copier update`, a question with `ask: false` keeps its previous answer and is not prompted again, whether or not `--skip-answered` is given. It does not go back to the default. This is the big difference from `when: false`, which discards the previous answer, and I want `when: false` to keep doing exactly that.
- The existing `--ask PATTERN` option (glob patterns, matched against question names) overrides `ask: false`: a matching question is prompted as usual, on copy and on update, even with `--skip-answered`.
- `when: false` always wins: such a question is never prompted, even if `--ask` matches it, and its answer is not recorded.
- Questions without `ask` behave exactly as today.
- Document `ask` next to `when` in the question docstring/docs. A short example: an `enable_experimental_feature_x` bool with `default: false` and `ask: false`.
