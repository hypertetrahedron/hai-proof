Feature request for Copier:

Our org has one big template used by many projects. It keeps growing options that most users shouldn't have to think about: features still under development, and settings that are right at their default 90% of the time (for example the Python version used to build the docs, which is almost always the project's own version). Today everyone gets prompted for all of them on every `copier copy` and `copier update`, so people fill in a lot of redundant answers and still have to stay alert, because they can't tell which questions matter.

We'd like template authors to be able to mark such "advanced" questions so they are skipped by default and keep a sensible value, while users who do need them can still answer them.

How this should look in `copier.yml`, how it interacts with the existing question settings, and what happens on `copier update` are design decisions I'd like to make with you, so ask me about them before you settle on a design. Please add tests and keep the existing tests passing.
