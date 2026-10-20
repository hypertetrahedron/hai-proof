# Working with me on features

When I ask for a feature and leave design decisions to a conversation, interview me before you build it.

- Ask one question at a time and wait for my answer. Prefer a short open question to a menu of options you invented; offer options only when they help me answer.
- I know what I want but I won't think to mention most details unless you ask about them. Don't assume that what I haven't said doesn't matter.
- Work through the design systematically, not just the obvious parts: names and entry points; defaults; how it interacts with existing options and features; edge cases (empty, zero, missing, duplicate, very large, unusual input); what counts as invalid input and exactly what happens then (error type, message, what is or isn't changed); lifecycle behaviour (completion, cleanup, updates, round trips); and compatibility with existing behaviour.
- Before you start implementing, ask me whether there is anything else about the behaviour I care about.
- Then summarise the agreed design in a few lines, and build exactly that, with tests for each decision.
